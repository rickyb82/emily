import { useEffect, useRef, useState } from 'react'
import { del, get, post } from '../lib/api'
import { useAuth } from '../lib/auth'

interface Member { id: string; display_name: string; avatar: string; role: string; email: string; username: string }
interface Share { id: string; target_user_id: string | null; permission: string }

/**
 * Condivisione: si scrive il nome o l'email della persona e i suggerimenti arrivano in tempo reale (GET /shares/members?q=),
 * come in un client di posta; sotto, l'elenco di chi ha gia' accesso con il permesso modificabile.
 */
export default function ShareDialog({ type, id, onClose }: { type: 'conversation' | 'project' | 'file'; id: string; onClose: () => void }) {
  const { me } = useAuth()
  const org = !!me?.features?.org_mode
  const [shares, setShares] = useState<Share[]>([])
  const [people, setPeople] = useState<Record<string, Member>>({})
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<Member[]>([])
  const [sel, setSel] = useState(0)
  const [perm, setPerm] = useState<'read' | 'write'>('read')
  const [err, setErr] = useState('')
  const timer = useRef<number>()

  async function load() {
    const list = await get<Share[]>(`/shares?resource_type=${type}&resource_id=${id}`)
    setShares(list)
    const missing = list.filter((s) => s.target_user_id && !people[s.target_user_id])
    if (missing.length) {
      const all = await get<Member[]>('/shares/members')
      setPeople((p) => ({ ...p, ...Object.fromEntries(all.map((m) => [m.id, m])) }))
    }
  }
  useEffect(() => { load() }, [id])

  // ricerca con piccolo debounce: ogni lettera interroga il server
  useEffect(() => {
    window.clearTimeout(timer.current)
    if (!q.trim()) { setHits([]); return }
    timer.current = window.setTimeout(() => {
      get<Member[]>(`/shares/members?q=${encodeURIComponent(q.trim())}`).then((r) => { setHits(r.filter((m) => !shares.some((s) => s.target_user_id === m.id))); setSel(0) }).catch(() => setHits([]))
    }, 150)
    return () => window.clearTimeout(timer.current)
  }, [q, shares])

  async function share(target: string | null, permission: string) {
    setErr('')
    try {
      await post('/shares', { resource_type: type, resource_id: id, target_user_id: target, permission })
      setQ(''); setHits([])
      await load()
    } catch (e: any) { setErr(e.message) }
  }
  async function unshare(s: Share) { await del(`/shares/${s.id}`); await load() }

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, hits.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)) }
    else if (e.key === 'Enter' && hits[sel]) { e.preventDefault(); share(hits[sel].id, perm) }
    else if (e.key === 'Escape') { setQ(''); setHits([]) }
  }
  const everyone = shares.find((s) => s.target_user_id === null)
  const label = (s: Share) => s.target_user_id === null ? (org ? '🏢 Tutta l\'organizzazione' : '👪 Tutta la famiglia')
    : people[s.target_user_id] ? `${people[s.target_user_id].avatar} ${people[s.target_user_id].display_name}` : '…'

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal stack" onClick={(e) => e.stopPropagation()}>
        <h3>Condividi</h3>
        {err && <div className="error">{err}</div>}
        <div className="share-search">
          <div className="row" style={{ gap: 6 }}>
            <input autoFocus placeholder="Nome o email della persona…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} style={{ flex: 1 }} />
            <select value={perm} onChange={(e) => setPerm(e.target.value as any)}>
              <option value="read">può vedere</option>
              {type !== 'file' && <option value="write">può modificare</option>}
            </select>
          </div>
          {hits.length > 0 && (
            <ul className="suggest">
              {hits.map((m, i) => (
                <li key={m.id} className={i === sel ? 'active' : ''} onMouseEnter={() => setSel(i)} onMouseDown={(e) => { e.preventDefault(); share(m.id, perm) }}>
                  <span className="kid-avatar small">{m.avatar}</span>
                  <span><b>{m.display_name}</b><br /><small className="muted">{m.email || m.username}{m.role === 'child' ? ' · bambino/a' : ''}</small></span>
                </li>
              ))}
            </ul>
          )}
          {q.trim() && hits.length === 0 && <small className="muted">Nessuno corrisponde a «{q}».</small>}
        </div>
        <div className="share-list">
          <div className="row between">
            <span>{org ? '🏢 Tutta l\'organizzazione' : '👪 Tutta la famiglia'}</span>
            <select value={everyone?.permission ?? 'none'} onChange={(e) => (e.target.value === 'none' ? everyone && unshare(everyone) : share(null, e.target.value))}>
              <option value="none">—</option>
              <option value="read">può vedere</option>
              {type !== 'file' && <option value="write">può modificare</option>}
            </select>
          </div>
          {shares.filter((s) => s.target_user_id).map((s) => (
            <div key={s.id} className="row between">
              <span>{label(s)}</span>
              <span className="row" style={{ gap: 4 }}>
                <select value={s.permission} onChange={(e) => share(s.target_user_id, e.target.value)}>
                  <option value="read">può vedere</option>
                  {type !== 'file' && <option value="write">può modificare</option>}
                </select>
                <button className="icon" title="Togli l'accesso" onClick={() => unshare(s)}>✕</button>
              </span>
            </div>
          ))}
          {shares.length === 0 && <small className="muted">Per ora lo vedi solo tu.</small>}
        </div>
        <button className="ghost" onClick={onClose}>Chiudi</button>
      </div>
    </div>
  )
}
