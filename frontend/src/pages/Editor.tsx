import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { get, type FileOut } from '../lib/api'
import { useAuth } from '../lib/auth'
import { APP_ICON, APP_LABEL, UI_LANG, editorFor, type ArtApp } from '../lib/artcraft'

/**
 * Editor a tutta pagina: WordCraft (documenti), GridCraft (fogli di calcolo) o PdfCraft (PDF), app open source in WebAssembly in un iframe.
 * ?file=<id> apre quel file del server (l'app la decide l'estensione); con &new=1&app=... e' un file nuovo (l'id lo ha
 * scelto il browser). File > Salva nell'editor spedisce il file a /api/files/wordcraft-save, che lo crea o lo sovrascrive.
 */
export default function Editor() {
  const { me } = useAuth()
  const [params] = useSearchParams()
  const nav = useNavigate()
  const fileId = params.get('file') || ''
  const isNew = params.get('new') === '1'
  const [file, setFile] = useState<FileOut | null>(null)
  const [err, setErr] = useState('')
  const [canWrite, setCanWrite] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const name = file?.filename || params.get('name') || ''
  const app: ArtApp = (params.get('app') as ArtApp) || editorFor(name) || 'wordcraft'

  useEffect(() => {
    if (isNew || !fileId) return
    get<FileOut[]>('/files').then((all) => {
      const f = all.find((x) => x.id === fileId)
      if (f) {
        setFile(f)
        setCanWrite(f.owner_id === me?.user.id)
      }
    }).catch(() => {}).finally(() => setLoaded(true))
    // anche un file non in elenco (es. di un progetto condiviso) si apre: il download controlla i permessi
  }, [fileId, isNew, me?.user.id])
  const ready = isNew || loaded
  const [dirty, setDirty] = useState(false)
  const [saved, setSaved] = useState('')
  const frame = useRef<HTMLIFrameElement>(null)

  // PdfCraft parla con la pagina che lo incornicia via postMessage (host=parent): riceviamo i salvataggi e li
  // scriviamo sul server, come fanno WordCraft/GridCraft con ?save=.
  useEffect(() => {
    if (app !== 'pdfcraft') return
    const onMsg = async (ev: MessageEvent) => {
      if (ev.origin !== window.location.origin || ev.source !== frame.current?.contentWindow) return
      const d = ev.data || {}
      if (d.type === 'pdfcraft:dirty') setDirty(!!d.dirty)
      else if (d.type === 'pdfcraft:failed') setErr(`PdfCraft non si è avviato: ${d.error || ''}`)
      else if (d.type === 'pdfcraft:save') {
        if (!canWrite) {
          const blob = new Blob([d.bytes], { type: 'application/pdf' })
          const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = d.name || 'documento.pdf'; a.click()
          return
        }
        const saveQ = new URLSearchParams({ file_id: fileId })
        const cid = params.get('conversation_id'); const pid = params.get('project_id')
        if (cid) saveQ.set('conversation_id', cid)
        if (pid) saveQ.set('project_id', pid)
        try {
          const r = await fetch(`/api/files/wordcraft-save?${saveQ.toString()}`, { method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(d.name || name || 'documento.pdf') }, body: d.bytes })
          if (!r.ok) throw new Error(`HTTP ${r.status}`)
          setSaved(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))
          setErr('')
        } catch (e: any) {
          setErr(`Salvataggio non riuscito: ${e.message}`)
        }
      }
    }
    window.addEventListener('message', onMsg)
    return () => window.removeEventListener('message', onMsg)
  }, [app, canWrite, fileId, name, params])

  const src = useMemo(() => {
    if (!fileId) return ''
    const saveQ = new URLSearchParams({ file_id: fileId })
    const cid = params.get('conversation_id'); const pid = params.get('project_id')
    if (cid) saveQ.set('conversation_id', cid)
    if (pid) saveQ.set('project_id', pid)
    const q = new URLSearchParams({ lang: UI_LANG })
    if (app === 'pdfcraft') {
      // PdfCraft: parametri nativi (nessuna patch): ?file= apre dal server, host=parent manda i salvataggi alla pagina
      q.set('file', `/files/${fileId}`)
      q.set('host', 'parent')
      if (me?.user.display_name) q.set('author', me.user.display_name)
      return `/pdfcraft/?${q.toString()}`
    }
    if (!isNew) {
      q.set('open', `/files/${fileId}`)
      q.set('name', name || 'documento')
    } else if (name) {
      q.set('name', name)
    }
    if (canWrite) q.set('save', `/api/files/wordcraft-save?${saveQ.toString()}`)
    return `/${app}/?${q.toString()}`
  }, [fileId, isNew, name, canWrite, params, app, me?.user.display_name])

  if (!me?.features?.[`${app}_web`]) {
    return (
      <div className="page">
        <h2>{APP_ICON[app]} Editor</h2>
        <p className="muted">L'editor {APP_LABEL[app]} non è attivo su questo server. Un amministratore può avviarlo con <code>./familai.sh {app} up</code>.</p>
      </div>
    )
  }
  if (!fileId) return <div className="page"><p className="error">Nessun documento indicato.</p><Link to="/documents">← Documenti</Link></div>

  return (
    <div className="editor-layout">
      <header className="chat-header">
        <div className="title">{APP_ICON[app]} {isNew ? (app === 'gridcraft' ? 'Nuovo foglio di calcolo' : 'Nuovo documento') : (file?.filename || 'Documento')}
          <small className="muted"> · {APP_LABEL[app]}</small>
          {!canWrite && <small className="muted"> · sola lettura (Salva scarica una copia)</small>}
          {app === 'pdfcraft' && dirty && <small className="muted"> · modifiche non salvate</small>}
          {app === 'pdfcraft' && saved && !dirty && <small className="muted"> · salvato {saved}</small>}
        </div>
        <div className="row">
          {!isNew && <a className="ghost btn-link" href={`/files/${fileId}`} target="_blank" rel="noreferrer">⬇ Scarica</a>}
          <button className="ghost" onClick={() => nav('/documents')}>Chiudi</button>
        </div>
      </header>
      {err && <div className="error">{err}</div>}
      {ready ? (
        <iframe ref={frame} className="editor-frame" src={src} title={APP_LABEL[app]} allow="clipboard-read; clipboard-write"
          onError={() => setErr(`L'editor non si è caricato: il container ${app}-web è attivo?`)} />
      ) : <div className="editor-frame center muted">Caricamento…</div>}
      <p className="muted small editor-hint">
        Salva con <b>File › Salva</b> (o Ctrl/Cmd+S) dentro l'editor: il file viene aggiornato qui su FamilAI, non scaricato.
        {app !== 'pdfcraft' && <><b> File › Esporta</b> (PDF, CSV…) crea un nuovo file accanto a questo.</>} Serve un browser con WebGPU o WebGL2.
      </p>
    </div>
  )
}
