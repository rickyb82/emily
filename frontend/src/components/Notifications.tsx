import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { get, post } from '../lib/api'
import { useLiveEvents } from '../lib/events'

interface Notice { id: string; kind: string; text: string; link: string; actor: string; read: boolean; created_at: string }

/** 🔔 Campanella: notifiche (condivisioni ricevute…) con contatore, elenco a tendina e avviso a comparsa in tempo reale. */
export default function Notifications() {
  const nav = useNavigate()
  const [items, setItems] = useState<Notice[]>([])
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const [toasts, setToasts] = useState<Notice[]>([])
  const load = () => get<{ unread: number; items: Notice[] }>('/notifications').then((r) => { setItems(r.items); setUnread(r.unread) }).catch(() => {})
  useEffect(() => { load() }, [])
  useLiveEvents((e) => {
    if (e.kind !== 'notification') return
    const n: Notice = { id: e.id, kind: e.nkind, text: e.text, link: e.link, actor: e.actor, read: false, created_at: new Date().toISOString() }
    setItems((l) => [n, ...l]); setUnread((u) => u + 1)
    setToasts((t) => [...t, n])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== n.id)), 8000)
    try { if ('Notification' in window && Notification.permission === 'granted') new Notification('Emily', { body: n.text }) } catch {}
  })
  useEffect(() => { if (!open) return; const close = () => setOpen(false); window.addEventListener('click', close); return () => window.removeEventListener('click', close) }, [open])
  async function toggle(e: React.MouseEvent) {
    e.stopPropagation()
    const next = !open; setOpen(next)
    if (next && unread > 0) { try { await post('/notifications/read'); setUnread(0); setItems((l) => l.map((n) => ({ ...n, read: true }))) } catch {} }
  }
  const go = (n: Notice) => { setOpen(false); if (n.link) nav(n.link) }
  const icon = (k: string) => k.startsWith('share_file') ? '📄' : k.startsWith('share_conversation') ? '💬' : k.startsWith('share_project') ? '📁' : '🔔'
  return (
    <>
      <button className={`icon bell ${unread ? 'has' : ''}`} onClick={toggle} title="Notifiche">🔔{unread > 0 && <span className="bell-count">{unread > 9 ? '9+' : unread}</span>}</button>
      {open && (
        <div className="bell-menu" onClick={(e) => e.stopPropagation()}>
          <div className="row between"><b>Notifiche</b>{'Notification' in window && Notification.permission === 'default' && <button className="ghost small" onClick={() => Notification.requestPermission()}>attiva avvisi del browser</button>}</div>
          {items.length === 0 && <p className="muted small">Nessuna notifica.</p>}
          <ul>
            {items.slice(0, 30).map((n) => (
              <li key={n.id} className={n.read ? '' : 'unread'} onClick={() => go(n)}>
                <span className="bell-ico">{icon(n.kind)}</span>
                <span><span>{n.text}</span><br /><small className="muted">{new Date(n.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}</small></span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="toasts">
        {toasts.map((n) => (
          <div key={n.id} className="toast" onClick={() => { setToasts((t) => t.filter((x) => x.id !== n.id)); go(n) }}>
            <span className="bell-ico">{icon(n.kind)}</span><span>{n.text}</span>
          </div>
        ))}
      </div>
    </>
  )
}
