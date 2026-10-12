import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { get, type FileOut } from '../lib/api'
import { useAuth } from '../lib/auth'
import { APP_ICON, APP_LABEL, editorFor, type ArtApp } from '../lib/artcraft'

/**
 * Editor a tutta pagina: WordCraft (documenti) o GridCraft (fogli di calcolo), app open source in WebAssembly in un iframe.
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

  const src = useMemo(() => {
    if (!fileId) return ''
    const saveQ = new URLSearchParams({ file_id: fileId })
    const cid = params.get('conversation_id'); const pid = params.get('project_id')
    if (cid) saveQ.set('conversation_id', cid)
    if (pid) saveQ.set('project_id', pid)
    const q = new URLSearchParams()
    if (!isNew) {
      q.set('open', `/files/${fileId}`)
      q.set('name', name || 'documento')
    } else if (name) {
      q.set('name', name)
    }
    if (canWrite) q.set('save', `/api/files/wordcraft-save?${saveQ.toString()}`)
    return `/${app}/?${q.toString()}`
  }, [fileId, isNew, name, canWrite, params, app])

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
        </div>
        <div className="row">
          {!isNew && <a className="ghost btn-link" href={`/files/${fileId}`} target="_blank" rel="noreferrer">⬇ Scarica</a>}
          <button className="ghost" onClick={() => nav('/documents')}>Chiudi</button>
        </div>
      </header>
      {err && <div className="error">{err}</div>}
      {ready ? (
        <iframe className="editor-frame" src={src} title={APP_LABEL[app]} allow="clipboard-read; clipboard-write"
          onError={() => setErr(`L'editor non si è caricato: il container ${app}-web è attivo?`)} />
      ) : <div className="editor-frame center muted">Caricamento…</div>}
      <p className="muted small editor-hint">
        Salva con <b>File › Salva</b> (o Ctrl/Cmd+S) dentro l'editor: il file viene aggiornato qui su FamilAI, non scaricato.
        <b> File › Esporta</b> (PDF, CSV…) crea un nuovo file accanto a questo. Serve un browser con WebGPU o WebGL2.
      </p>
    </div>
  )
}
