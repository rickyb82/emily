import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { get, type FileOut } from '../lib/api'
import { useAuth } from '../lib/auth'

/**
 * Editor di documenti: WordCraft (word processor open source, WebAssembly) in un iframe a tutta pagina.
 * ?file=<id> apre quel file del server; con &new=1 e' un documento nuovo (l'id lo ha scelto il browser):
 * File > Salva nell'editor spedisce il file a /api/files/wordcraft-save, che lo crea o lo sovrascrive.
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

  useEffect(() => {
    if (isNew || !fileId) return
    get<FileOut[]>('/files').then((all) => {
      const f = all.find((x) => x.id === fileId)
      if (f) {
        setFile(f)
        setCanWrite(f.owner_id === me?.user.id)
      }
    }).catch(() => {})
    // anche un file non in elenco (es. di un progetto condiviso) si apre: il download controlla i permessi
  }, [fileId, isNew, me?.user.id])

  const src = useMemo(() => {
    if (!fileId) return ''
    const saveQ = new URLSearchParams({ file_id: fileId })
    const cid = params.get('conversation_id'); const pid = params.get('project_id')
    if (cid) saveQ.set('conversation_id', cid)
    if (pid) saveQ.set('project_id', pid)
    const q = new URLSearchParams()
    if (!isNew) {
      q.set('open', `/files/${fileId}`)
      q.set('name', file?.filename || params.get('name') || 'documento.docx')
    } else if (params.get('name')) {
      q.set('name', params.get('name')!)
    }
    if (canWrite) q.set('save', `/api/files/wordcraft-save?${saveQ.toString()}`)
    return `/wordcraft/?${q.toString()}`
  }, [fileId, isNew, file?.filename, canWrite, params])

  if (!me?.features?.wordcraft_web) {
    return (
      <div className="page">
        <h2>📝 Editor documenti</h2>
        <p className="muted">L'editor WordCraft non è attivo su questo server. Un amministratore può avviarlo con <code>./familai.sh wordcraft up</code>.</p>
      </div>
    )
  }
  if (!fileId) return <div className="page"><p className="error">Nessun documento indicato.</p><Link to="/documents">← Documenti</Link></div>

  return (
    <div className="editor-layout">
      <header className="chat-header">
        <div className="title">📝 {isNew ? 'Nuovo documento' : (file?.filename || 'Documento')}
          {!canWrite && <small className="muted"> · sola lettura (Salva scarica una copia)</small>}
        </div>
        <div className="row">
          {!isNew && <a className="ghost btn-link" href={`/files/${fileId}`} target="_blank" rel="noreferrer">⬇ Scarica</a>}
          <button className="ghost" onClick={() => nav('/documents')}>Chiudi</button>
        </div>
      </header>
      {err && <div className="error">{err}</div>}
      <iframe className="editor-frame" src={src} title="WordCraft" allow="clipboard-read; clipboard-write"
        onError={() => setErr("L'editor non si è caricato: il container wordcraft-web è attivo?")} />
      <p className="muted small editor-hint">
        Salva con <b>File › Salva</b> (o Ctrl/Cmd+S) dentro l'editor: il file viene aggiornato qui su FamilAI, non scaricato.
        <b> File › Esporta</b> in PDF crea un nuovo file accanto a questo. Serve un browser con WebGPU o WebGL2.
      </p>
    </div>
  )
}
