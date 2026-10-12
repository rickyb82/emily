import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { del, get, post, type FileOut, type Project } from '../lib/api'
import { useAuth } from '../lib/auth'
import { APP_ICON, canEdit, editorFor, editorPath, newFilePath } from '../lib/artcraft'

/** I documenti dell'utente (caricati, generati dall'assistente, scritti nell'editor) con apertura in WordCraft. */
export default function Documents() {
  const { me } = useAuth()
  const nav = useNavigate()
  const [files, setFiles] = useState<FileOut[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [filter, setFilter] = useState('')
  const [onlyDocs, setOnlyDocs] = useState(true)
  const [err, setErr] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  const load = () => get<FileOut[]>('/files').then(setFiles).catch((e) => setErr(e.message))
  useEffect(() => { load(); get<Project[]>('/projects').then(setProjects).catch(() => {}) }, [])

  async function upload(list: FileList | null) {
    if (!list) return
    for (const f of Array.from(list)) {
      const fd = new FormData()
      fd.append('file', f)
      try { await post('/files', fd) } catch (e: any) { setErr(e.message) }
    }
    if (fileInput.current) fileInput.current.value = ''
    load()
  }
  async function remove(f: FileOut) {
    if (!confirm(`Eliminare "${f.filename}"?`)) return
    try { await del(`/files/${f.id}`); load() } catch (e: any) { setErr(e.message) }
  }

  const wc = !!me?.features?.wordcraft_web
  const gc = !!me?.features?.gridcraft_web
  const pc = !!me?.features?.pdfcraft_web
  const dc = !!me?.features?.deckcraft_web
  const web = wc || gc || pc || dc
  const feats = me?.features
  const shown = files
    .filter((f) => !onlyDocs || editorFor(f.filename))
    .filter((f) => !filter || f.filename.toLowerCase().includes(filter.toLowerCase()))
  const projName = (id: string | null) => projects.find((p) => p.id === id)?.name

  return (
    <div className="page">
      <h2>📝 Documenti</h2>
      <p className="muted">
        {web ? `Scrivi e modifica ${[wc && 'documenti Word (WordCraft)', gc && 'fogli di calcolo Excel (GridCraft)', pc && 'PDF (PdfCraft)', dc && 'presentazioni PowerPoint (DeckCraft)'].filter(Boolean).join(', ')} direttamente qui: app open source, niente installazioni, i file restano in casa.`
             : "Gli editor non sono attivi (./familai.sh wordcraft|gridcraft|pdfcraft|deckcraft up): qui trovi comunque i tuoi file."}
      </p>
      {err && <div className="error">{err}</div>}
      <div className="row wrap" style={{ gap: 8, marginBottom: 12 }}>
        {wc && <button className="primary" onClick={() => nav(newFilePath('wordcraft'))}>＋ Documento</button>}
        {gc && <button className="primary" onClick={() => nav(newFilePath('gridcraft'))}>＋ Foglio di calcolo</button>}
        {dc && <button className="primary" onClick={() => nav(newFilePath('deckcraft'))}>＋ Presentazione</button>}
        <button className="ghost" onClick={() => fileInput.current?.click()}>📎 Carica</button>
        <input ref={fileInput} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />
        <input placeholder="Cerca…" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ maxWidth: 220 }} />
        <label className="row small muted" style={{ gap: 4 }}><input type="checkbox" checked={onlyDocs} onChange={(e) => setOnlyDocs(e.target.checked)} /> solo documenti</label>
      </div>
      {shown.length === 0 && <p className="muted small">Nessun file.</p>}
      <ul className="file-list">
        {shown.map((f) => (
          <li key={f.id} className="row between wrap" style={{ gap: 8 }}>
            <span>
              {canEdit(f.filename, feats)
                ? <Link to={editorPath(f.id, f.filename)} title="Apri nell'editor"><b>{APP_ICON[editorFor(f.filename)!]} {f.filename}</b></Link>
                : <a href={f.url} target="_blank" rel="noreferrer"><b>{f.filename}</b></a>}
              <small className="muted"> · {(f.size / 1024).toFixed(0)} KB · {new Date(f.created_at).toLocaleDateString()}
                {f.kind === 'generated' && ' · creato qui'}{f.project_id && projName(f.project_id) && ` · 📁 ${projName(f.project_id)}`}
                {f.conversation_id && <> · <Link to={`/c/${f.conversation_id}`}>chat</Link></>}</small>
            </span>
            <span className="row" style={{ gap: 4 }}>
              {canEdit(f.filename, feats) && <Link className="ghost btn-link small" to={editorPath(f.id, f.filename)}>✏️ Modifica</Link>}
              <a className="ghost btn-link small" href={f.url} target="_blank" rel="noreferrer">⬇</a>
              {f.owner_id === me?.user.id && <button className="icon" title="Elimina" onClick={() => remove(f)}>🗑</button>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
