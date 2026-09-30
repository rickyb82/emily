import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { del, get, post, type Conversation } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function Shell({ children }: { children: ReactNode }) {
  const { me, logout } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const id = loc.pathname.startsWith('/c/') ? loc.pathname.split('/')[2] : undefined
  const [convs, setConvs] = useState<Conversation[]>([])
  const [open, setOpen] = useState(false)

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

  async function remove(c: Conversation) {
    if (!confirm(`Eliminare "${c.title}"?`)) return
    await del(`/chat/conversations/${c.id}`)
    await load()
    if (id === c.id) nav('/')
  }

  const isChild = me?.user.role === 'child'
  return (
    <div className={`shell ${open ? 'open' : ''}`}>
      <aside className="sidebar">
        <div className="brand">
          <span>🏠 FamilAI</span>
          <button className="icon" onClick={() => setOpen(false)}>✕</button>
        </div>
        <button className="primary wide" onClick={newChat}>＋ Nuova chat</button>
        <nav className="navlinks">
          <NavLink to="/projects" onClick={() => setOpen(false)}>📁 Progetti</NavLink>
          <NavLink to="/settings" onClick={() => setOpen(false)}>⚙️ Impostazioni</NavLink>
          {me?.user.role === 'admin' && <NavLink to="/admin" onClick={() => setOpen(false)}>👪 Famiglia</NavLink>}
        </nav>
        <div className="conv-list">
          {convs.map((c) => (
            <div key={c.id} className={`conv-item ${id === c.id ? 'active' : ''}`}>
              <NavLink to={`/c/${c.id}`} onClick={() => setOpen(false)} title={c.title}>
                {c.shared ? '🔗 ' : ''}{c.title}
                {c.shared && <small className="muted"> · {c.owner_name}</small>}
              </NavLink>
              {!c.shared && <button className="icon" onClick={() => remove(c)} title="Elimina">🗑</button>}
            </div>
          ))}
        </div>
        <div className="userbox">
          <span className="kid-avatar small">{me?.user.avatar}</span>
          <div>
            <div>{me?.user.display_name}</div>
            <small className="muted">{isChild ? 'bambino/a' : me?.user.role === 'admin' ? 'amministratore' : 'adulto'} · {me?.family_name}</small>
          </div>
          <button className="icon" onClick={logout} title="Esci">⏻</button>
        </div>
      </aside>
      <main className="main">
        <button className="icon menu-btn" onClick={() => setOpen(true)}>☰</button>
        {children}
      </main>
    </div>
  )
}
