import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { get, patch, post, streamMessage, type Conversation, type FileOut, type Message } from '../lib/api'
import { useAuth } from '../lib/auth'
import MessageView, { toolLabel } from '../components/MessageView'
import ShareDialog from '../components/ShareDialog'
import ArtifactPanel, { type ArtifactData } from '../components/ArtifactPanel'

interface ToolInfo { name: string; description: string; kind: string; group: string }
const GROUP_LABEL: Record<string, string> = { web_search: '🔎 Ricerca web', generate_image: '🎨 Immagini', generate_video: '🎬 Video', read_document: '📄 Documenti', artifacts: '📦 Artifact', run_code: '⚙️ Esecuzione codice', mcp: '🔌 MCP' }

export default function Chat() {
  const { id } = useParams()
  const nav = useNavigate()
  const { me } = useAuth()
  const [conv, setConv] = useState<Conversation | null>(null)
  const [access, setAccess] = useState('owner')
  const [ownerName, setOwnerName] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [text, setText] = useState('')
  const [files, setFiles] = useState<FileOut[]>([])
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [gotText, setGotText] = useState(false)   // true appena arriva il primo token
  const [err, setErr] = useState('')
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [enabledTools, setEnabledTools] = useState<Set<string>>(new Set())
  const [share, setShare] = useState(false)
  const [artifacts, setArtifacts] = useState<ArtifactData[]>([])
  const [openArtifact, setOpenArtifact] = useState<ArtifactData | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  function upsertArtifact(a: ArtifactData, open = true) {
    setArtifacts((l) => (l.some((x) => x.id === a.id) ? l.map((x) => (x.id === a.id ? a : x)) : [...l, a]))
    if (open) setOpenArtifact(a)
  }
  const abort = useRef<AbortController | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    get('/chat/providers').then((r) => {
      setTools(r.tools)
      setEnabledTools(new Set<string>(r.tools.map((t: ToolInfo) => t.group)))
    })
  }, [])

  useEffect(() => {
    setErr('')
    setOpenArtifact(null)
    setArtifacts([])
    if (!id) {
      setConv(null)
      setMessages([])
      return
    }
    get<ArtifactData[]>(`/artifacts?conversation_id=${id}`).then(setArtifacts).catch(() => {})
    get(`/chat/conversations/${id}`)
      .then((r) => {
        setConv(r.conversation)
        setAccess(r.access)
        setOwnerName(r.owner_name)
        setMessages(r.messages)
      })
      .catch((e) => setErr(e.message))
  }, [id])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, status, busy])

  useEffect(() => {
    const h = (e: Event) => {
      const d = (e as CustomEvent).detail
      setConv((c) => (c && d && c.id === d.id ? { ...c, title: d.title } : c))
    }
    window.addEventListener('familai:renamed', h)
    return () => window.removeEventListener('familai:renamed', h)
  }, [])

  async function ensureConversation(): Promise<Conversation> {
    if (conv) return conv
    const c = await post<Conversation>('/chat/conversations', {})
    setConv(c)
    window.dispatchEvent(new Event('familai:conversations'))
    nav(`/c/${c.id}`, { replace: true })
    return c
  }

  async function send(e?: FormEvent) {
    e?.preventDefault()
    if (busy || (!text.trim() && files.length === 0)) return
    const c = await ensureConversation()
    const body = { text, file_ids: files.map((f) => f.id), provider: c.provider, model: c.model, tools: Array.from(enabledTools) }
    setText('')
    setFiles([])
    await runTurn(c, 'messages', body)
  }

  /** Rigenera l'ultima risposta, eventualmente con un altro provider/modello. */
  async function regenerate(provider?: string, model?: string) {
    if (!conv || busy) return
    await runTurn(conv, 'regenerate', { provider: provider ?? conv.provider, model: model ?? conv.model, tools: Array.from(enabledTools) })
  }

  async function runTurn(c: Conversation, action: 'messages' | 'regenerate', body: any) {
    setErr('')
    setBusy(true)
    setGotText(false)
    setStatus('')
    let current: Message | null = null
    abort.current = new AbortController()
    try {
      await streamMessage(
        c.id,
        body,
        (ev) => {
          if (ev.type === 'regenerating') {
            // tronca tutto ciò che segue l'ultimo messaggio dell'utente (gli id locali dei tool non coincidono con il DB)
            setMessages((m) => {
              const i = m.map((x) => x.role).lastIndexOf('user')
              return i >= 0 ? m.slice(0, i + 1) : m
            })
            setConv((cv) => (cv ? { ...cv, provider: ev.provider, model: ev.model } : cv))
            setStatus(`↻ Rigenero con ${ev.model}…`)
          } else if (ev.type === 'user_message') {
            setMessages((m) => [...m, ev.message])
          } else if (ev.type === 'status') {
            setStatus(ev.text || '')
          } else if (ev.type === 'text_delta') {
            setStatus('')
            setGotText(true)
            if (!current) {
              current = { id: 'tmp-' + Date.now(), role: 'assistant', author_id: null, content: [{ type: 'text', text: '' }], created_at: '', flagged: false, usage: {}, streaming: true }
              const cur = current
              setMessages((m) => [...m, cur])
            }
            current.content[0].text += ev.text
            const snapshot = { ...current, content: [{ ...current.content[0] }] }
            setMessages((m) => m.map((x) => (x.id === snapshot.id ? snapshot : x)))
          } else if (ev.type === 'rag') {
            const names = Array.from(new Set(ev.hits.map((h: any) => h.filename)))
            setStatus(`📚 Trovati ${ev.hits.length} passaggi in: ${names.join(', ')}`)
          } else if (ev.type === 'tool_start') {
            setStatus(`${toolLabel(ev.name)}…`)
            setGotText(false)
            if (current) {
              const finished = { ...current, streaming: false }
              setMessages((m) => m.map((x) => (x.id === finished.id ? finished : x)))
              current = null
            }
          } else if (ev.type === 'tool_result') {
            setStatus('')
            for (const a of ev.artifacts || []) if (a.type === 'artifact') upsertArtifact(a)
            const tm: Message = { id: 'tool-' + ev.tool_use_id, role: 'tool', author_id: null, created_at: '', flagged: false, usage: {}, content: [ev] }
            setMessages((m) => [...m, tm])
          } else if (ev.type === 'error') {
            setErr(ev.error)
          } else if (ev.type === 'done') {
            setStatus('')
            if (ev.message) {
              const done = ev.message
              const tmpId = current?.id   // catturato ora: l'updater di React gira dopo (e due volte in StrictMode)
              setMessages((m) => (tmpId && m.some((x) => x.id === tmpId) ? m.map((x) => (x.id === tmpId ? done : x)) : [...m, done]))
              current = null
            }
            window.dispatchEvent(new Event('familai:conversations'))
          }
        },
        abort.current.signal,
        action,
      )
    } catch (e: any) {
      if (e.name !== 'AbortError') setErr(e.message)
    } finally {
      setBusy(false)
      setStatus('')
      setGotText(false)
    }
  }

  async function upload(list: FileList | null) {
    if (!list) return
    for (const f of Array.from(list)) {
      const fd = new FormData()
      fd.append('file', f)
      if (conv) fd.append('conversation_id', conv.id)
      try {
        const out = await post<FileOut>('/files', fd)
        setFiles((x) => [...x, out])
      } catch (e: any) {
        setErr(e.message)
      }
    }
    if (fileInput.current) fileInput.current.value = ''
  }

  async function changeModel(provider: string, model: string) {
    if (!conv) {
      const c = await post<Conversation>('/chat/conversations', { provider, model })
      setConv(c)
      nav(`/c/${c.id}`, { replace: true })
      window.dispatchEvent(new Event('familai:conversations'))
      return
    }
    const c = await patch<Conversation>(`/chat/conversations/${conv.id}`, { provider, model })
    setConv(c)
    const hasAnswer = messages.some((m) => m.role === 'assistant')
    if (hasAnswer && confirm(`Modello cambiato in ${model}. Vuoi rigenerare l'ultima risposta con il nuovo modello? La cronologia della chat viene comunque passata al nuovo modello dai prossimi messaggi.`)) {
      await regenerate(c.provider, c.model)
    }
  }

  const provider = me?.providers.find((p) => p.id === (conv?.provider ?? me.providers[0]?.id))
  const canWrite = access === 'owner' || access === 'write'
  const isChild = me?.user.role === 'child'

  return (
    <div className={`chat-layout ${openArtifact ? 'with-panel' : ''}`}>
    <div className="chat">
      <header className="chat-header">
        <div className="title" title={canWrite && conv ? 'Clicca per rinominare' : undefined} style={canWrite && conv ? { cursor: 'text' } : undefined}
          onClick={async () => {
            if (!conv || !canWrite) return
            const title = prompt('Nuovo nome della chat', conv.title)
            if (!title || title.trim() === conv.title) return
            const c = await patch<Conversation>(`/chat/conversations/${conv.id}`, { title: title.trim().slice(0, 200) })
            setConv(c)
            window.dispatchEvent(new Event('familai:conversations'))
          }}>
          {conv?.title ?? 'Nuova chat'} {ownerName && access !== 'owner' && <small className="muted">· di {ownerName}</small>}
        </div>
        <div className="row">
          {!isChild && me && (
            <select
              value={provider ? `${provider.id}|${conv?.model || provider.default_model}` : ''}
              onChange={(e) => {
                const [p, m] = e.target.value.split('|')
                changeModel(p, m)
              }}
              disabled={busy}
            >
              {me.providers.map((p) => (
                <optgroup key={p.id} label={p.label}>
                  {p.models.map((m) => (
                    <option key={m.id} value={`${p.id}|${m.id}`}>{m.label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          )}
          {artifacts.length === 1 && !openArtifact && (
            <button className="ghost" onClick={() => setOpenArtifact(artifacts[0])} title={artifacts[0].title}>📦 {artifacts[0].title.slice(0, 24)}</button>
          )}
          {artifacts.length > 1 && !openArtifact && (
            <select className="ghost-select" value="" title="Apri un artifact" onChange={(e) => { const a = artifacts.find((x) => x.id === e.target.value); if (a) setOpenArtifact(a) }}>
              <option value="" disabled>📦 {artifacts.length} artifact…</option>
              {artifacts.map((a, i) => <option key={a.id} value={a.id}>{i + 1}. {a.title}</option>)}
            </select>
          )}
          {conv && access === 'owner' && <button className="ghost" onClick={() => setShare(true)}>🔗 Condividi</button>}
        </div>
      </header>

      <div className="messages">
        {messages.length === 0 && (
          <div className="empty">
            <div className="big">{isChild ? '👋' : '🏠'}</div>
            <h2>{isChild ? `Ciao ${me?.user.display_name}! Cosa vuoi scoprire oggi?` : 'Come posso aiutarti?'}</h2>
            <p className="muted">{isChild ? 'Puoi farmi domande, chiedermi un disegno o aiuto con i compiti.' : 'Chiedi, allega documenti, genera immagini e video, cerca sul web.'}</p>
          </div>
        )}
        {messages.map((m) => (
          <MessageView key={m.id} m={m} onOpenArtifact={(a) => upsertArtifact(artifacts.find((x) => x.id === a.id) ?? a)} />
        ))}
        {busy && (!gotText || status) && <Working status={status} />}
        {err && <div className="error">{err}</div>}
        {!busy && canWrite && messages.some((m) => m.role === 'assistant') && (
          <div className="row" style={{ justifyContent: 'flex-start' }}>
            <button className="ghost small" onClick={() => regenerate()} title="Rigenera l'ultima risposta con il modello corrente">↻ Rigenera risposta</button>
          </div>
        )}
        <div ref={bottom} />
      </div>

      {canWrite ? (
        <form className="composer" onSubmit={send}>
          {files.length > 0 && (
            <div className="chips">
              {files.map((f) => (
                <span key={f.id} className="chip">📎 {f.filename} <button type="button" className="icon" onClick={() => setFiles(files.filter((x) => x.id !== f.id))}>✕</button></span>
              ))}
            </div>
          )}
          <div className="composer-row">
            <button type="button" className="icon" onClick={() => fileInput.current?.click()} title="Allega">📎</button>
            <input ref={fileInput} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={isChild ? 'Scrivi qui…' : 'Scrivi un messaggio (Invio per inviare, Shift+Invio per andare a capo)'}
              rows={1}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
            />
            {busy ? (
              <button type="button" className="ghost" onClick={() => abort.current?.abort()}>■</button>
            ) : (
              <button className="primary">➤</button>
            )}
          </div>
          {!isChild && tools.length > 0 && (
            <div className="tools-row">
              {Array.from(new Set(tools.map((t) => t.group))).map((g) => (
                <label key={g} className="tool-toggle" title={tools.filter((t) => t.group === g).map((t) => t.description).join('\n')}>
                  <input type="checkbox" checked={enabledTools.has(g)} onChange={(e) => {
                    const s = new Set(enabledTools)
                    e.target.checked ? s.add(g) : s.delete(g)
                    setEnabledTools(s)
                  }} />
                  {GROUP_LABEL[g] ?? g}
                </label>
              ))}
            </div>
          )}
        </form>
      ) : (
        <div className="composer muted center-text">Conversazione in sola lettura</div>
      )}
      {share && conv && <ShareDialog type="conversation" id={conv.id} onClose={() => setShare(false)} />}
    </div>
    {openArtifact && (
      <ArtifactPanel artifact={openArtifact} all={artifacts} canEdit={canWrite} onClose={() => setOpenArtifact(null)} onChange={(a) => upsertArtifact(a)} onSelect={(a) => setOpenArtifact(a)} />
    )}
    </div>
  )
}


/** Indicatore animato mostrato mentre il modello lavora: puntini, testo di stato e tempo trascorso. */
function Working({ status }: { status: string }) {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    const t0 = Date.now()
    const t = setInterval(() => setSecs(Math.floor((Date.now() - t0) / 1000)), 1000)
    return () => clearInterval(t)
  }, [])
  const fallback = secs < 6 ? 'Sto pensando' : secs < 20 ? 'Ci sto lavorando, ancora un momento' : secs < 60 ? 'Sto preparando una risposta lunga' : 'Sto ancora lavorando, la connessione è attiva'
  const label = status ? status.replace(/…+$/, '') : fallback
  return (
    <div className="working" role="status" aria-live="polite">
      <span className="dots"><i /><i /><i /></span>
      <span>{label}</span>
      {secs >= 3 && <span className="muted small">{secs}s</span>}
    </div>
  )
}
