import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message } from '../lib/api'
import { useEffect, useState } from 'react'
import { isSpeaking, plainText, speak, stopSpeaking, ttsEnabled } from '../lib/speech'

const TOOL_LABELS: Record<string, string> = {
  web_search: '🔎 Ricerca web',
  generate_image: '🎨 Generazione immagine',
  generate_video: '🎬 Generazione video',
  read_document: '📄 Lettura documento',
  search_documents: '📚 Ricerca nei documenti',
  create_artifact: '📦 Creazione artifact',
  update_artifact: '📦 Aggiornamento artifact',
  run_code: '⚙️ Esecuzione codice',
  ask_model: '🤝 Consulto un altro modello',
}
export const toolLabel = (n: string) => TOOL_LABELS[n] ?? (n.startsWith('mcp__') ? `🔌 ${n.split('__').slice(1).join(' / ')}` : `🛠 ${n}`)

export default function MessageView({ m, authorName, onOpenArtifact }: { m: Message; authorName?: string; onOpenArtifact?: (a: any) => void }) {
  if (m.role === 'tool') {
    return (
      <div className="msg tool">
        {m.content.map((b: any, i: number) => <ToolStep key={i} b={b} onOpenArtifact={onOpenArtifact} />)}
      </div>
    )
  }
  const text = m.content.filter((b: any) => b.type === 'text').map((b: any) => b.text).join('\n')
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
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
          {m.streaming && <span className="cursor">▍</span>}
        </div>
      )}
      {m.flagged && <div className="flag">⚑ segnalato dal filtro contenuti</div>}
      {m.role === 'assistant' && !m.streaming && m.usage?.model && (
        <div className="route-badge" title={m.usage.route_reason ? `Router: ${m.usage.route_reason}` : ''}>
          {m.usage.provider === 'ollama' ? '🏠 locale' : '☁️ cloud'} · {m.usage.model}
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


/** Riassunto leggibile dell'input di un tool (la parte che interessa all'utente). */
function inputSummary(name: string, input: any): string {
  if (!input || typeof input !== 'object') return ''
  if (name === 'web_search') return `"${input.query ?? ''}"`
  if (name === 'generate_image' || name === 'generate_video') return `"${String(input.prompt ?? '').slice(0, 120)}"`
  if (name === 'create_artifact') return `${input.title ?? ''}${input.kind ? ` (${input.kind})` : ''}`
  if (name === 'update_artifact') return input.title ?? input.artifact_id ?? ''
  if (name === 'run_code') return `${input.language ?? ''}${input.code ? ` · ${String(input.code).split('\n').length} righe` : ''}`
  if (name === 'read_document' || name === 'search_documents') return input.query ? `"${input.query}"` : (input.file_id ?? '')
  if (name === 'ask_model') return `→ ${input.provider ?? ''}${input.model ? ` (${input.model})` : ''}: "${String(input.prompt ?? '').slice(0, 100)}"`
  const first = Object.entries(input)[0]
  return first ? `${first[0]}: ${String(first[1]).slice(0, 100)}` : ''
}

/** Un passo dell'agente (chiamata a un tool o a un altro modello), con stato live e dettagli espandibili. */
function ToolStep({ b, onOpenArtifact }: { b: any; onOpenArtifact?: (a: any) => void }) {
  const [open, setOpen] = useState(false)
  const running = b.status === 'running'
  const err = !!b.is_error
  const summary = inputSummary(b.name, b.input)
  return (
    <div className={`step ${running ? 'running' : err ? 'error' : 'done'}`}>
      <button className="step-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="step-icon">{running ? <span className="spinner" /> : err ? '⚠️' : '✓'}</span>
        <span className="step-label">{toolLabel(b.name)}</span>
        {summary && <span className="step-summary" title={summary}>{summary}</span>}
        <span className="step-caret">{open ? '▾' : '▸'}</span>
      </button>
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
          <a key={j} className="chip" href={a.url} target="_blank" rel="noreferrer">📄 {a.filename}</a>
        ) : null,
      )}
      {open && (
        <div className="step-body">
          {b.input && Object.keys(b.input).length > 0 && (
            <details><summary>Parametri</summary><pre>{JSON.stringify(b.input, null, 1).slice(0, 4000)}</pre></details>
          )}
          {running ? <div className="muted small">In esecuzione…</div> : <pre>{String(b.content ?? '').slice(0, 6000) || '(nessun output)'}</pre>}
        </div>
      )}
    </div>
  )
}
