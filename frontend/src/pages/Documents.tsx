import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { del, get, patch, post, type FileOut, type Project } from '../lib/api'
import { useAuth } from '../lib/auth'
import { APP_LABEL, canEdit, editorFor, editorPath, newFilePath, type ArtApp } from '../lib/artcraft'

/**
 * 📁 Documenti, stile Finder: cartelle create dall'utente (annidabili, drag & drop), i progetti come cartelle automatiche,
 * e la cartella "APP" (stile iOS) con le applicazioni: nuovo documento Word, foglio Excel, presentazione, mappa, PDF, posta.
 * Posizione corrente nell'URL: ?folder=<id> (cartella propria) oppure ?project=<id> (file di un progetto).
 */

interface Folder { id: string; name: string; parent_id: string | null; color: string; files: number; subfolders: number }

/** Le app: icona (tile colorata), etichetta, cosa fa il click. */
const APPS: { key: string; app?: ArtApp; label: string; glyph: string; cls: string; name?: string; feature: string }[] = [
  { key: 'word', app: 'wordcraft', label: 'Documento', glyph: 'W', cls: 'app-word', name: 'documento.docx', feature: 'wordcraft_web' },
  { key: 'excel', app: 'gridcraft', label: 'Foglio', glyph: 'X', cls: 'app-excel', name: 'foglio.xlsx', feature: 'gridcraft_web' },
  { key: 'deck', app: 'deckcraft', label: 'Presentazione', glyph: 'P', cls: 'app-deck', name: 'presentazione.pptx', feature: 'deckcraft_web' },
  { key: 'map', app: 'ideacraft', label: 'Mappa', glyph: '◎', cls: 'app-map', name: 'mappa.ideacraft.json', feature: 'ideacraft_web' },
  { key: 'pdf', app: 'pdfcraft', label: 'PDF', glyph: 'PDF', cls: 'app-pdf', feature: 'pdfcraft_web' },
  { key: 'mail', label: 'Posta', glyph: '✉', cls: 'app-mail', feature: 'mailcraft_web' },
]

/** Icona del file in base al tipo (stesse tinte delle app). */
function FileIcon({ name, mime }: { name: string; mime: string }) {
  const app = editorFor(name)
  const low = name.toLowerCase()
  const cls = app === 'wordcraft' ? 'app-word' : app === 'gridcraft' ? 'app-excel' : app === 'deckcraft' ? 'app-deck' : app === 'ideacraft' ? 'app-map' : app === 'pdfcraft' ? 'app-pdf' : ''
  const glyph = app === 'wordcraft' ? 'W' : app === 'gridcraft' ? 'X' : app === 'deckcraft' ? 'P' : app === 'ideacraft' ? '◎' : app === 'pdfcraft' ? 'PDF' : ''
  if (mime.startsWith('image/') || /\.(png|jpe?g|gif|webp|svg)$/.test(low)) return <span className="file-icon generic">🖼️</span>
  if (!cls) return <span className="file-icon generic">{mime.startsWith('video/') ? '🎬' : mime.startsWith('audio/') ? '🎵' : /\.(zip|tar|gz)$/.test(low) ? '🗜️' : '📄'}</span>
  return <span className={`file-icon doc ${cls}`}><span className="file-icon-corner" /><b>{glyph}</b></span>
}

export default function Documents() {
  const { me } = useAuth()
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const folderId = params.get('folder') || ''
  const projectId = params.get('project') || ''
  const [files, setFiles] = useState<FileOut[]>([])
  const [projFiles, setProjFiles] = useState<FileOut[]>([])
  const [folders, setFolders] = useState<Folder[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [filter, setFilter] = useState('')
  const [err, setErr] = useState('')
  const [appsOpen, setAppsOpen] = useState(false)
  const [menu, setMenu] = useState<{ kind: 'file' | 'folder'; id: string; x: number; y: number } | null>(null)
  const [moveFor, setMoveFor] = useState<FileOut | null>(null)
  const [dragOver, setDragOver] = useState('')
  const [selected, setSelected] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const feats = me?.features || {}

  const load = () => Promise.all([
    get<FileOut[]>('/files').then(setFiles),
    get<Folder[]>('/folders').then(setFolders),
    get<Project[]>('/projects').then(setProjects).catch(() => {}),
  ]).catch((e) => setErr(e.message))
  useEffect(() => { load() }, [])
  useEffect(() => {
    if (!projectId) { setProjFiles([]); return }
    get<FileOut[]>(`/files?project_id=${projectId}`).then(setProjFiles).catch((e) => setErr(e.message))
  }, [projectId])
  useEffect(() => { const close = () => setMenu(null); window.addEventListener('click', close); return () => window.removeEventListener('click', close) }, [])

  // ---- navigazione ----
  const go = (p: { folder?: string; project?: string }) => { setSelected(''); setParams(p.folder ? { folder: p.folder } : p.project ? { project: p.project } : {}) }
  const byId = useMemo(() => Object.fromEntries(folders.map((f) => [f.id, f])), [folders])
  const crumbs = useMemo(() => {
    const out: { label: string; folder?: string; project?: string }[] = [{ label: 'Documenti' }]
    if (projectId) out.push({ label: `📁 ${projects.find((p) => p.id === projectId)?.name ?? 'Progetto'}`, project: projectId })
    const chain: Folder[] = []
    let cur = byId[folderId]
    while (cur) { chain.unshift(cur); cur = cur.parent_id ? byId[cur.parent_id] : undefined as any }
    chain.forEach((f) => out.push({ label: f.name, folder: f.id }))
    return out
  }, [folderId, projectId, byId, projects])
  const current = byId[folderId]

  // ---- contenuto della cartella corrente ----
  const q = filter.trim().toLowerCase()
  const shownFolders = projectId ? [] : folders.filter((f) => (f.parent_id || '') === folderId).filter((f) => !q || f.name.toLowerCase().includes(q))
  const shownFiles = (projectId ? projFiles : files.filter((f) => (f.folder_id || '') === folderId))
    .filter((f) => !q || f.filename.toLowerCase().includes(q))
  const searching = !!q && !projectId
  const searchHits = searching ? files.filter((f) => f.filename.toLowerCase().includes(q)) : []

  // ---- azioni ----
  async function upload(list: FileList | null) {
    if (!list) return
    for (const f of Array.from(list)) {
      const fd = new FormData()
      fd.append('file', f)
      if (folderId) fd.append('folder_id', folderId)
      if (projectId) fd.append('project_id', projectId)
      try { await post('/files', fd) } catch (e: any) { setErr(e.message) }
    }
    if (fileInput.current) fileInput.current.value = ''
    load()
  }
  async function newFolder() {
    const name = prompt('Nome della nuova cartella', 'Nuova cartella')
    if (!name?.trim()) return
    try { await post('/folders', { name: name.trim(), parent_id: folderId || null }); load() } catch (e: any) { setErr(e.message) }
  }
  async function renameFolder(f: Folder) {
    const name = prompt('Nuovo nome della cartella', f.name)
    if (!name?.trim() || name.trim() === f.name) return
    try { await patch(`/folders/${f.id}`, { name: name.trim() }); load() } catch (e: any) { setErr(e.message) }
  }
  async function deleteFolder(f: Folder) {
    if (!confirm(`Eliminare la cartella "${f.name}"? I file che contiene tornano nella cartella superiore.`)) return
    try { await del(`/folders/${f.id}`); load() } catch (e: any) { setErr(e.message) }
  }
  async function renameFile(f: FileOut) {
    const ext = (f.filename.match(/(\.ideacraft)?\.[^.]+$/) || [''])[0]
    const typed = prompt('Nuovo nome del file', f.filename.replace(/(\.ideacraft)?\.[^.]+$/, ''))
    if (!typed?.trim()) return
    try { await patch(`/files/${f.id}`, { filename: typed.trim().replace(/(\.ideacraft)?\.[^.]+$/, '') + ext }); load() } catch (e: any) { setErr(e.message) }
  }
  async function removeFile(f: FileOut) {
    if (!confirm(`Eliminare "${f.filename}"?`)) return
    try { await del(`/files/${f.id}`); load() } catch (e: any) { setErr(e.message) }
  }
  async function moveFile(f: FileOut, target: string) {
    if ((f.folder_id || '') === target) return
    try { await patch(`/files/${f.id}`, { folder_id: target }); load() } catch (e: any) { setErr(e.message) }
  }
  async function moveFolder(f: Folder, target: string) {
    if (f.id === target || (f.parent_id || '') === target) return
    try { await patch(`/folders/${f.id}`, { parent_id: target }); load() } catch (e: any) { setErr(e.message) }
  }
  function openFile(f: FileOut) {
    if (canEdit(f.filename, feats)) nav(editorPath(f.id, f.filename))
    else window.open(f.url, '_blank')
  }
  async function launch(a: typeof APPS[number]) {
    setAppsOpen(false)
    if (a.key === 'mail') { nav('/mail'); return }
    if (a.key === 'pdf') {
      try {
        const f = await post<FileOut>('/files/blank-pdf', { filename: 'documento.pdf', folder_id: folderId || null, project_id: projectId || null })
        nav(editorPath(f.id, f.filename))
      } catch (e: any) { setErr(e.message) }
      return
    }
    nav(newFilePath(a.app!, { folderId: folderId || null, projectId: projectId || null, name: a.name }))
  }

  // ---- drag & drop ----
  const onDragStart = (e: React.DragEvent, kind: 'file' | 'folder', id: string) => { e.dataTransfer.setData('text/familai', `${kind}:${id}`); e.dataTransfer.effectAllowed = 'move' }
  const onDropTo = (target: string) => (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setDragOver('')
    const d = e.dataTransfer.getData('text/familai'); if (!d) return
    const [kind, id] = d.split(':')
    if (kind === 'file') { const f = files.find((x) => x.id === id); if (f) moveFile(f, target) }
    else { const f = byId[id]; if (f) moveFolder(f, target) }
  }
  const dropProps = (target: string) => ({
    onDragOver: (e: React.DragEvent) => { if (e.dataTransfer.types.includes('text/familai')) { e.preventDefault(); e.stopPropagation(); setDragOver(target || 'root') } },
    onDragLeave: () => setDragOver(''),
    onDrop: onDropTo(target),
  })

  const apps = APPS.filter((a) => (feats as any)[a.feature])
  const projName = (id: string | null) => projects.find((p) => p.id === id)?.name
  const owner = (f: FileOut) => f.owner_id === me?.user.id
  const menuFile = menu?.kind === 'file' ? [...files, ...projFiles].find((f) => f.id === menu.id) : undefined
  const menuFolder = menu?.kind === 'folder' ? byId[menu.id] : undefined

  return (
    <div className="page finder" onClick={() => setSelected('')}>
      <div className="finder-bar row between wrap">
        <nav className="crumbs">
          {crumbs.map((c, i) => (
            <span key={i} className="row" style={{ gap: 4 }}>
              {i > 0 && <span className="muted">›</span>}
              {i < crumbs.length - 1
                ? <button className="crumb" {...dropProps(c.folder || '')} onClick={(e) => { e.stopPropagation(); go(c) }}>{c.label}</button>
                : <b className="crumb current">{c.label}</b>}
            </span>
          ))}
        </nav>
        <div className="row" style={{ gap: 6 }}>
          <input placeholder="Cerca…" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ maxWidth: 200 }} />
          {!projectId && <button className="ghost" onClick={(e) => { e.stopPropagation(); newFolder() }}>📁 Nuova cartella</button>}
          <button className="ghost" onClick={(e) => { e.stopPropagation(); fileInput.current?.click() }}>📎 Carica</button>
          <input ref={fileInput} type="file" multiple hidden onChange={(e) => upload(e.target.files)} />
        </div>
      </div>
      {err && <div className="error">{err}</div>}

      {searching ? (
        <>
          <p className="muted small">Risultati per «{filter}» in tutte le cartelle</p>
          <div className="finder-grid">
            {searchHits.map(renderFile)}
            {searchHits.length === 0 && <p className="muted small">Nessun file.</p>}
          </div>
        </>
      ) : (
        <div className="finder-grid" {...(folderId || !projectId ? dropProps(current?.parent_id || '') : {})}>
          {/* cartella APP (solo alla radice) */}
          {!folderId && !projectId && apps.length > 0 && (
            <button className="tile folder-tile app-folder" onClick={(e) => { e.stopPropagation(); setAppsOpen(true) }} title="Applicazioni">
              <span className="ios-folder">
                {apps.slice(0, 9).map((a) => <span key={a.key} className={`mini-app ${a.cls}`}>{a.glyph}</span>)}
              </span>
              <span className="tile-name">APP</span>
            </button>
          )}
          {/* progetti come cartelle automatiche (radice) */}
          {!folderId && !projectId && projects.map((p) => (
            <button key={p.id} className="tile folder-tile" onClick={(e) => { e.stopPropagation(); go({ project: p.id }) }} title={`Progetto ${p.name}`}>
              <span className="folder-icon project"><span className="folder-tab" /></span>
              <span className="tile-name">{p.name}</span>
              <small className="muted">progetto</small>
            </button>
          ))}
          {/* cartelle dell'utente */}
          {shownFolders.map((f) => (
            <button key={f.id} className={`tile folder-tile ${dragOver === f.id ? 'drop' : ''}`} draggable onDragStart={(e) => onDragStart(e, 'folder', f.id)} {...dropProps(f.id)}
              onClick={(e) => { e.stopPropagation(); go({ folder: f.id }) }} onContextMenu={(e) => { e.preventDefault(); setMenu({ kind: 'folder', id: f.id, x: e.clientX, y: e.clientY }) }}>
              <span className="folder-icon" style={f.color ? { ['--folder' as any]: f.color } : undefined}><span className="folder-tab" /></span>
              <span className="tile-name">{f.name}</span>
              <small className="muted">{f.files + f.subfolders === 0 ? 'vuota' : `${f.files} file${f.subfolders ? ` · ${f.subfolders} cartelle` : ''}`}</small>
              <span className="tile-menu" onClick={(e) => { e.stopPropagation(); setMenu({ kind: 'folder', id: f.id, x: e.clientX, y: e.clientY }) }}>⋯</span>
            </button>
          ))}
          {/* file */}
          {shownFiles.map(renderFile)}
          {shownFolders.length === 0 && shownFiles.length === 0 && (folderId || projectId) && <p className="muted small" style={{ gridColumn: '1 / -1' }}>Cartella vuota. Trascina qui dei file o usa 📎 Carica.</p>}
        </div>
      )}

      {/* menu contestuale */}
      {menu && menuFile && (
        <ul className="ctx-menu" style={{ left: menu.x, top: menu.y }} onClick={(e) => e.stopPropagation()}>
          <li onClick={() => { setMenu(null); openFile(menuFile) }}>{canEdit(menuFile.filename, feats) ? '✏️ Apri nell\'editor' : '👁 Apri'}</li>
          <li onClick={() => { setMenu(null); window.open(menuFile.url, '_blank') }}>⬇ Scarica</li>
          {owner(menuFile) && <li onClick={() => { setMenu(null); renameFile(menuFile) }}>✎ Rinomina</li>}
          {owner(menuFile) && <li onClick={() => { setMenu(null); setMoveFor(menuFile) }}>📁 Sposta in…</li>}
          {menuFile.conversation_id && <li onClick={() => { setMenu(null); nav(`/c/${menuFile.conversation_id}`) }}>💬 Vai alla chat</li>}
          {owner(menuFile) && <li className="danger" onClick={() => { setMenu(null); removeFile(menuFile) }}>🗑 Elimina</li>}
        </ul>
      )}
      {menu && menuFolder && (
        <ul className="ctx-menu" style={{ left: menu.x, top: menu.y }} onClick={(e) => e.stopPropagation()}>
          <li onClick={() => { setMenu(null); go({ folder: menuFolder.id }) }}>📂 Apri</li>
          <li onClick={() => { setMenu(null); renameFolder(menuFolder) }}>✎ Rinomina</li>
          <li className="danger" onClick={() => { setMenu(null); deleteFolder(menuFolder) }}>🗑 Elimina cartella</li>
        </ul>
      )}

      {/* "Sposta in…" */}
      {moveFor && (
        <div className="modal-bg" onClick={() => setMoveFor(null)}>
          <div className="modal stack" onClick={(e) => e.stopPropagation()}>
            <h3>Sposta «{moveFor.filename}»</h3>
            <ul className="move-list">
              <li onClick={() => { moveFile(moveFor, ''); setMoveFor(null) }}>📁 Documenti (radice)</li>
              {folders.map((f) => <li key={f.id} onClick={() => { moveFile(moveFor, f.id); setMoveFor(null) }} style={{ paddingLeft: 12 + 14 * depth(f, byId) }}>📁 {f.name}</li>)}
            </ul>
            <button className="ghost" onClick={() => setMoveFor(null)}>Annulla</button>
          </div>
        </div>
      )}

      {/* cartella APP aperta, stile iOS */}
      {appsOpen && (
        <div className="ios-overlay" onClick={() => setAppsOpen(false)}>
          <div className="ios-panel" onClick={(e) => e.stopPropagation()}>
            <h3>APP</h3>
            <div className="ios-apps">
              {apps.map((a) => (
                <button key={a.key} className="ios-app" onClick={() => launch(a)} title={a.app ? APP_LABEL[a.app] : 'MailCraft'}>
                  <span className={`app-icon ${a.cls}`}>{a.glyph}</span>
                  <span>{a.label}</span>
                </button>
              ))}
            </div>
            <p className="muted small">{folderId ? `I nuovi file nascono in «${current?.name}».` : projectId ? 'I nuovi file nascono in questo progetto.' : 'I nuovi file nascono in Documenti.'} App open source, niente installazioni, i file restano qui.</p>
          </div>
        </div>
      )}
    </div>
  )

  function renderFile(f: FileOut) {
    return (
      <button key={f.id} className={`tile file-tile ${selected === f.id ? 'selected' : ''}`} draggable={owner(f)} onDragStart={(e) => onDragStart(e, 'file', f.id)}
        onClick={(e) => { e.stopPropagation(); if (selected === f.id) openFile(f); else setSelected(f.id) }} onDoubleClick={() => openFile(f)}
        onContextMenu={(e) => { e.preventDefault(); setMenu({ kind: 'file', id: f.id, x: e.clientX, y: e.clientY }) }} title={`${f.filename} · ${(f.size / 1024).toFixed(0)} KB`}>
        <FileIcon name={f.filename} mime={f.mime} />
        <span className="tile-name">{f.filename}</span>
        <small className="muted">{new Date(f.created_at).toLocaleDateString()}{f.project_id && !projectId && projName(f.project_id) ? ` · ${projName(f.project_id)}` : ''}{!owner(f) ? ' · condiviso' : ''}</small>
        <span className="tile-menu" onClick={(e) => { e.stopPropagation(); setMenu({ kind: 'file', id: f.id, x: e.clientX, y: e.clientY }) }}>⋯</span>
      </button>
    )
  }
}

function depth(f: Folder, byId: Record<string, Folder>): number {
  let d = 0; let cur = f
  while (cur.parent_id && byId[cur.parent_id]) { d++; cur = byId[cur.parent_id] }
  return d
}

