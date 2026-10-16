import Markdown from './Markdown'
import { Link } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { canEdit, editorPath } from '../lib/artcraft'
import type { Message } from '../lib/api'
import { useEffect, useState } from 'react'
import ShareDialog from './ShareDialog'
import { isSpeaking, plainText, speak, stopSpeaking, ttsEnabled } from '../lib/speech'
import { appIcon, fmtDuration, stepInput, stepOutcome, stepTitle, turnSummary } from '../lib/steps'

const TOOL_LABELS: Record<string, string> = {
  web_search: '🔎 Ricerca web',
  generate_image: '🎨 Generazione immagine',
  generate_video: '🎬 Generazione video',
  read_document: '📄 Lettura documento',
  search_documents: '📚 Ricerca nei documenti',
  create_artifact: '📦 Creazione artifact',
  update_artifact: '📦 Aggiornamento artifact',
  list_artifacts: '📦 Elenco artifact',
  delete_artifact: '🗑 Eliminazione artifact',
  run_code: '⚙️ Esecuzione codice',
  write_document: '📝 Documento con WordCraft',
  write_spreadsheet: '📊 Foglio con GridCraft',
  pdf_tool: '📕 PDF con PdfCraft',
  write_presentation: '📽️ Presentazione con DeckCraft',
  mind_map: '🧠 Mappa mentale con IdeaCraft',
  ask_model: '🤝 Consulto un altro modello',
  remember: '🧠 Memorizzo',
  forget: '🧠 Dimentico',
}
export const toolLabel = (n: string) => TOOL_LABELS[n] ?? (n.startsWith('mcp__') ? `🔌 ${n.split('__').slice(1).join(' / ')}` : `🛠 ${n}`)

export default function MessageView({ m, authorName, onOpenArtifact }: { m: Message; authorName?: string; onOpenArtifact?: (a: any) => void }) {
  if (m.role === 'tool') {
    return <ActivityGroup steps={[m]} onOpenArtifact={onOpenArtifact} />
  }
  const text = m.content.filter((b: any) => b.type === 'text').map((b: any) => b.text).join('\n')
  const thinking = (m as any).thinking || m.content.filter((b: any) => b.type === 'thinking').map((b: any) => b.thinking || b.text || '').join('\n')
  const images = m.content.filter((b: any) => b.type === 'image' && b.file_id)
  // messaggio dell'assistente fatto solo di chiamate a tool: lo mostrano gia' gli step sotto
  if (m.role === 'assistant' && !text.trim() && images.length === 0 && !m.streaming) return null
  return (
    <div className={`msg ${m.role} ${m.flagged ? 'flagged' : ''}`}>
      {authorName && <div className="author">{authorName}</div>}
      {images.map((b: any) => (
        <img key={b.file_id} className="attach-image" src={`/files/${b.file_id}`} alt={b.filename || ''} />
      ))}
      {m.role === 'user' ? (
        <div className="bubble">{text}</div>
      ) : (
        <div className="markdown">
          {thinking && <Thinking text={thinking} live={!!m.streaming && !text.trim()} />}
          <Markdown className="">{text}</Markdown>
          {m.streaming && <span className="cursor">▍</span>}
        </div>
      )}
      {m.flagged && <div className="flag">⚑ segnalato dal filtro contenuti</div>}
      {m.role === 'assistant' && !m.streaming && m.usage?.model && (
        <div className="route-badge" title={m.usage.route_reason ? `Router: ${m.usage.route_reason}` : ''}>
          {m.usage.provider === 'ollama' || m.usage.provider === 'custom' ? '🏠 locale' : '☁️ cloud'} · {m.usage.model}
          {m.usage.routed && <> · router: {m.usage.route_reason || 'scelta automatica'}</>}
          {(m.usage.input_tokens || m.usage.output_tokens) ? <> · {(m.usage.input_tokens ?? 0) + (m.usage.cache_read_tokens ?? 0) + (m.usage.cache_write_tokens ?? 0)} → {m.usage.output_tokens ?? 0} token</> : null}
          {(m.usage.cache_read_tokens ?? 0) > 0 && <> ({Math.round(100 * m.usage.cache_read_tokens / Math.max(1, (m.usage.input_tokens ?? 0) + m.usage.cache_read_tokens + (m.usage.cache_write_tokens ?? 0)))}% da cache)</>}
        </div>
      )}
      {m.role === 'assistant' && !m.streaming && text.trim() && <SpeakButton text={text} />}
    </div>
  )
}

/** Legge il messaggio con la voce naturale del backend (se configurata). */
function SpeakButton({ text }: { text: string }) {
  const [enabled, setEnabled] = useState(false)
  const [state, setState] = useState<'idle' | 'loading' | 'playing'>('idle')
  const [err, setErr] = useState('')
  useEffect(() => { ttsEnabled().then(setEnabled) }, [])
  useEffect(() => () => { if (state === 'playing') stopSpeaking() }, [state])
  if (!enabled) return null
  async function toggle() {
    if (state === 'playing' && isSpeaking()) { stopSpeaking(); setState('idle'); return }
    setErr('')
    setState('loading')
    try {
      const p = speak(plainText(text))
      setState('playing')
      await p
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setState('idle')
    }
  }
  return (
    <div className="speak-row">
      <button className="ghost small" onClick={toggle} disabled={state === 'loading'} title={state === 'playing' ? 'Ferma' : 'Leggi ad alta voce'}>
        {state === 'loading' ? '⏳' : state === 'playing' ? '⏹ Ferma' : '🔊 Leggi'}
      </button>
      {err && <small className="error">{err}</small>}
    </div>
  )
}


/** Tutte le chiamate a tool di un turno in un'unica timeline. Mentre lavora e' aperta e mostra gli ultimi passaggi (i vecchi si
 * ripiegano in "altri N"); finito il turno si richiude in una riga discreta, cliccabile per riaprirla. Un errore recuperato (un passo
 * dopo e' riuscito) non colora il blocco: arancio solo se il turno finisce con un errore. I risultati restano sempre visibili. */
export function ActivityGroup({ steps, onOpenArtifact, live }: { steps: Message[]; onOpenArtifact?: (a: any) => void; live?: boolean }) {
  const [userOpen, setUserOpen] = useState<boolean | null>(null)
  const [showAll, setShowAll] = useState(false)
  const [, tick] = useState(0)
  const blocks: any[] = steps.flatMap((m) => m.content)
  const running = blocks.find((b) => b.status === 'running')
  const active = !!running || !!live
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => tick((x) => x + 1), 1000)
    return () => clearInterval(t)
  }, [active])
  if (blocks.length === 0) return null
  const open = userOpen ?? active
  const lastErr = blocks.length > 0 && blocks[blocks.length - 1].is_error && !running
  const errors = blocks.filter((b) => b.is_error).length
  const { live: liveLabel, done: doneLabel } = turnSummary(blocks)
  const t0 = blocks[0].started_at as number | undefined
  const tEnd = blocks.reduce((m, b) => Math.max(m, b.ended_at || 0), 0) || undefined
  const elapsed = t0 ? (active ? Date.now() - t0 : tEnd ? tEnd - t0 : undefined) : undefined
  const headline = running
    ? `${liveLabel} · ${stepTitle(running.name).toLowerCase()}${stepInput(running.name, running.input) ? ` ${stepInput(running.name, running.input)}` : ''}`
    : live ? `${liveLabel} · elaboro i risultati` : doneLabel
  const LIMIT = 3
  const hidden = !showAll && active && blocks.length > LIMIT ? blocks.length - LIMIT : 0
  const shown = hidden ? blocks.slice(hidden) : blocks
  const withArtifacts = blocks.filter((b) => (b.artifacts || []).length > 0)
  return (
    <div className={`msg tool activity ${active ? 'running' : lastErr ? 'error' : 'done'} ${open ? 'open' : ''}`}>
      <button className="activity-head" onClick={() => setUserOpen(!open)} aria-expanded={open} title={open ? 'Nascondi i passaggi' : 'Mostra cosa ho fatto'}>
        <span className="activity-dot">{active ? <span className="spinner" /> : <i className={lastErr ? 'warn' : ''} />}</span>
        <span className="activity-text">{headline}</span>
        {!active && errors > 0 && !lastErr && <span className="activity-note">{errors === 1 ? '1 tentativo ripetuto' : `${errors} tentativi ripetuti`}</span>}
        {elapsed !== undefined && <span className="activity-time">{fmtDuration(elapsed)}</span>}
        <span className="step-caret">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="timeline">
          {hidden > 0 && <button className="tl-more" onClick={() => setShowAll(true)}>▸ altri {hidden} {hidden === 1 ? 'passaggio' : 'passaggi'}</button>}
          {shown.map((b, i) => <TimelineRow key={b.tool_use_id || i} b={b} onOpenArtifact={onOpenArtifact} />)}
        </div>
      )}
      {!open && withArtifacts.map((b, i) => <StepArtifacts key={b.tool_use_id || i} b={b} onOpenArtifact={onOpenArtifact} />)}
    </div>
  )
}

/** Una riga della timeline: titolo in italiano, cosa ha chiesto, com'e' andata, durata; clic per i dettagli tecnici. */
function TimelineRow({ b, onOpenArtifact }: { b: any; onOpenArtifact?: (a: any) => void }) {
  const [open, setOpen] = useState(false)
  const running = b.status === 'running'
  const err = !!b.is_error
  const what = stepInput(b.name, b.input)
  const how = running ? '' : stepOutcome(b.name, b.content, err)
  const dur = b.started_at && b.ended_at ? fmtDuration(b.ended_at - b.started_at) : ''
  return (
    <div className={`tl-row ${running ? 'run' : err ? 'warn' : 'ok'} ${open ? 'open' : ''}`}>
      <button className="tl-line" onClick={() => setOpen((o) => !o)} aria-expanded={open} title={b.name}>
        <span className="tl-icon">{running ? <span className="spinner" /> : appIcon(b.name)}</span>
        <span className="tl-title">{stepTitle(b.name)}</span>
        {what && <span className="tl-what">{what}</span>}
        {how && <span className="tl-how">{err ? '✕ ' : '→ '}{how}</span>}
        {running && <span className="tl-how muted">in corso…</span>}
        {dur && <span className="tl-ms">{dur}</span>}
      </button>
      <StepArtifacts b={b} onOpenArtifact={onOpenArtifact} />
      {open && (
        <div className="step-body">
          <div className="muted small" style={{ marginBottom: 4 }}>{b.name}</div>
          {b.input && Object.keys(b.input).length > 0 && (
            <details><summary>Parametri</summary><pre>{JSON.stringify(b.input, null, 1).slice(0, 4000)}</pre></details>
          )}
          {running ? <div className="muted small">In esecuzione…</div> : <pre>{String(b.content ?? '').slice(0, 6000) || '(nessun output)'}</pre>}
        </div>
      )}
    </div>
  )
}

/** I risultati visibili di un passo: immagini e video generati, schede artifact, file scaricabili. */
function StepArtifacts({ b, onOpenArtifact }: { b: any; onOpenArtifact?: (a: any) => void }) {
  const [shareFile, setShareFile] = useState<string | null>(null)
  const feats = useAuth().me?.features
  if (!(b.artifacts || []).length) return null
  return (
    <div className="step-artifacts">
      {(b.artifacts || []).map((a: any, j: number) =>
        a.type === 'image' ? (
          <a key={j} href={a.url} target="_blank" rel="noreferrer"><img className="gen-image" src={a.url} alt="immagine generata" /></a>
        ) : a.type === 'video' ? (
          <video key={j} className="gen-video" src={a.url} controls />
        ) : a.type === 'artifact' ? (
          <button key={j} className="artifact-card" onClick={() => onOpenArtifact?.(a)}>
            <span className="big">📦</span>
            <span><b>{a.title}</b><br /><small className="muted">{a.kind}{a.language ? ` · ${a.language}` : ''} · v{a.version} · clicca per aprire</small></span>
          </button>
        ) : a.type === 'file' ? (
          <span key={j} className="chip">
            <a href={a.url} target="_blank" rel="noreferrer">📄 {a.filename}</a>
            {a.file_id && canEdit(a.filename, feats) && <Link to={editorPath(a.file_id, a.filename)} title="Apri nell'editor" style={{ marginLeft: 6 }}>✏️ Modifica</Link>}
            {a.file_id && <button className="icon" title="Condividi il file con altri utenti (lettura o modifica)" style={{ marginLeft: 4 }} onClick={() => setShareFile(a.file_id)}>🔗</button>}
          </span>
        ) : a.type === 'artifact_deleted' ? (
          <div key={j} className="muted small" style={{ padding: '0 10px 8px' }}>🗑 Eliminato: {a.title}</div>
        ) : null,
      )}
      {shareFile && <ShareDialog type="file" id={shareFile} onClose={() => setShareFile(null)} />}
    </div>
  )
}

/** Ragionamento del modello: aperto mentre pensa, poi ripiegato in una riga cliccabile. */
function Thinking({ text, live }: { text: string; live: boolean }) {
  const [open, setOpen] = useState<boolean | null>(null)
  const isOpen = open ?? live
  const words = text.trim().split(/\s+/).length
  return (
    <div className={`thinking ${live ? 'live' : ''}`}>
      <button className="thinking-head" onClick={() => setOpen(!isOpen)} aria-expanded={isOpen}>
        <span>💭 {live ? 'Sto ragionando…' : `Ragionamento (${words} parole)`}</span>
        <span className="step-caret">{isOpen ? '▾' : '▸'}</span>
      </button>
      {isOpen && <div className="thinking-body">{text}{live && <span className="cursor">▍</span>}</div>}
    </div>
  )
}
