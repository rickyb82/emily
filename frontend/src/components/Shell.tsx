import { useEffect, useState, type ReactNode } from 'react'
import Brand from './Brand'
import Guide from '../pages/Guide'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { del, get, patch, post, type Conversation } from '../lib/api'
import { useAuth } from '../lib/auth'
import Approvals from './Approvals'

export default function Shell({ children }: { children: ReactNode }) {
  const { me, logout } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const id = loc.pathname.startsWith('/c/') ? loc.pathname.split('/')[2] : undefined
  const [convs, setConvs] = useState<Conversation[]>([])
  const [open, setOpen] = useState(false)
  // Barra laterale a scomparsa (desktop): ricordata tra una sessione e l'altra; l'editor la chiude da solo per fare spazio.
  const [collapsed, setCollapsed] = useState<boolean>(() => { try { return localStorage.getItem('familai:sidebar') === 'collapsed' } catch { return false } })
  const [autoCollapsed, setAutoCollapsed] = useState(false)
  const toggleSidebar = () => {
    const next = !collapsed
    setCollapsed(next); setAutoCollapsed(false)
    try { localStorage.setItem('familai:sidebar', next ? 'collapsed' : 'open') } catch {}
  }
  useEffect(() => {
    const inEditor = loc.pathname.startsWith('/editor') || loc.pathname.startsWith('/mail') || loc.pathname.startsWith('/remote') || loc.pathname.startsWith('/cover') || loc.pathname.startsWith('/quotes')
    if (inEditor && !collapsed) { setCollapsed(true); setAutoCollapsed(true) }
    else if (!inEditor && autoCollapsed) { setCollapsed(false); setAutoCollapsed(false) }
  }, [loc.pathname])  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b' && !e.shiftKey) { e.preventDefault(); toggleSidebar() } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [collapsed])  // eslint-disable-line react-hooks/exhaustive-deps

  async function load() {
    try {
      setConvs(await get<Conversation[]>('/chat/conversations'))
    } catch {}
  }
  useEffect(() => {
    load()
    const h = () => load()
    window.addEventListener('familai:conversations', h)
    return () => window.removeEventListener('familai:conversations', h)
  }, [])

  async function newChat() {
    const c = await post<Conversation>('/chat/conversations', {})
    await load()
    setOpen(false)
    nav(`/c/${c.id}`)
  }

  async function rename(c: Conversation) {
    const title = prompt('Nuovo nome della chat', c.title)
    if (!title || title.trim() === c.title) return
    await patch(`/chat/conversations/${c.id}`, { title: title.trim().slice(0, 200) })
    await load()
    window.dispatchEvent(new CustomEvent('familai:renamed', { detail: { id: c.id, title: title.trim() } }))
  }

  async function remove(c: Conversation) {
    if (!confirm(`Eliminare "${c.title}"?`)) return
    await del(`/chat/conversations/${c.id}`)
    await load()
    if (id === c.id) nav('/')
  }

  const isChild = me?.user.role === 'child'
  const [guide, setGuide] = useState(false)
  useEffect(() => { const h = () => setGuide(true); window.addEventListener('familai:guide', h); return () => window.removeEventListener('familai:guide', h) }, [])
  return (
    <div className={`shell ${open ? 'open' : ''} ${collapsed ? 'collapsed' : ''}`}>
      <aside className="sidebar">
        <div className="brand">
          <Brand />
          <span className="row" style={{ gap: 4 }}>
            {!isChild && <Approvals />}
            <button className="icon" onClick={() => setOpen(false)}>✕</button>
            <button className="icon collapse-btn" onClick={toggleSidebar} title="Nascondi la barra laterale (⌘/Ctrl+B)">◀</button>
          </span>
        </div>
        <button className="primary wide" onClick={newChat}>＋ Nuova chat</button>
        <nav className="navlinks">
          <NavLink to="/projects" onClick={() => setOpen(false)}>📁 Progetti</NavLink>
          {!isChild && (
            <div className="navgroup">
              <span className="navgroup-title">🧰 Produttività</span>
              <NavLink to="/documents" onClick={() => setOpen(false)}>📝 Documenti</NavLink>
              {me?.features?.mailcraft_web && <NavLink to="/mail" onClick={() => setOpen(false)}>✉️ Posta</NavLink>}
              {me?.features?.remotecraft_web && <NavLink to="/remote" onClick={() => setOpen(false)}>🛟 Assistenza</NavLink>}
              {me?.features?.covercraft_web && <NavLink to="/cover" onClick={() => setOpen(false)}>📡 Copertura</NavLink>}
              {me?.features?.quotecraft_web && <NavLink to="/quotes" onClick={() => setOpen(false)}>💶 Preventivi</NavLink>}
            </div>
          )}
        </nav>
        <div className="conv-list">
          {convs.map((c) => (
            <div key={c.id} className={`conv-item ${id === c.id ? 'active' : ''}`}>
              <NavLink to={`/c/${c.id}`} onClick={() => setOpen(false)} title={c.title}>
                {c.shared ? '🔗 ' : ''}{c.title}
                {c.shared && <small className="muted"> · {c.owner_name}</small>}
              </NavLink>
              {!c.shared && <button className="icon" onClick={() => rename(c)} title="Rinomina">✏️</button>}
              {!c.shared && <button className="icon" onClick={() => remove(c)} title="Elimina">🗑</button>}
            </div>
          ))}
        </div>
        {!isChild && (
          <nav className="navlinks bottom">
            <NavLink to="/settings" onClick={() => setOpen(false)}>⚙️ Impostazioni</NavLink>
            {me?.user.role === 'admin' && <NavLink to="/admin" onClick={() => setOpen(false)}>{me?.features?.org_mode ? '🏢 Organizzazione' : '👪 Famiglia'}</NavLink>}
          </nav>
        )}
        <div className="userbox">
          <span className="kid-avatar small">{me?.user.avatar}</span>
          <div>
            <div>{me?.user.display_name}</div>
            <small className="muted">{me?.user.role_label || (isChild ? 'bambino/a' : me?.user.role === 'admin' ? 'amministratore' : (me?.features?.org_mode ? 'utente' : 'adulto'))} · {me?.family_name && me.family_name !== 'Famiglia' ? me.family_name : (me?.features?.org_mode ? 'organizzazione' : 'famiglia')}</small>
          </div>
          <button className="icon" onClick={logout} title="Esci">⏻</button>
        </div>
      </aside>
      <main className="main">
        <button className="icon menu-btn" onClick={() => setOpen(true)}>☰</button>
        <button className="icon expand-btn" onClick={toggleSidebar} title="Mostra la barra laterale (⌘/Ctrl+B)">☰</button>
        {children}
      </main>
      <button className="guide-fab" onClick={() => setGuide(true)} title="Guida interattiva">?</button>
      {guide && (
        <div className="guide-modal-bg" onClick={() => setGuide(false)}>
          <div className="guide-modal" onClick={(e) => e.stopPropagation()}>
            <Guide onClose={() => setGuide(false)} />
          </div>
        </div>
      )}
    </div>
  )
}
