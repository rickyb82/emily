import { useEffect, useState } from 'react'
import { del, get, post } from '../lib/api'

interface Member { id: string; display_name: string; avatar: string; role: string }
interface Share { id: string; target_user_id: string | null; permission: string }

export default function ShareDialog({ type, id, onClose }: { type: 'conversation' | 'project' | 'file'; id: string; onClose: () => void }) {
  const [members, setMembers] = useState<Member[]>([])
  const [shares, setShares] = useState<Share[]>([])
  const [err, setErr] = useState('')

  async function load() {
    setShares(await get(`/shares?resource_type=${type}&resource_id=${id}`))
  }
  useEffect(() => {
    get('/shares/members').then(setMembers)
    load()
  }, [id])

  async function share(target: string | null, permission: string) {
    setErr('')
    try {
      await post('/shares', { resource_type: type, resource_id: id, target_user_id: target, permission })
      await load()
    } catch (e: any) {
      setErr(e.message)
    }
  }
  async function unshare(s: Share) {
    await del(`/shares/${s.id}`)
    await load()
  }
  const current = (target: string | null) => shares.find((s) => s.target_user_id === target)
  const rows: { id: string | null; label: string }[] = [{ id: null, label: '👪 Tutta la famiglia' }, ...members.map((m) => ({ id: m.id, label: `${m.avatar} ${m.display_name}` }))]

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Condividi</h3>
        {err && <div className="error">{err}</div>}
        <table className="share-table">
          <tbody>
            {rows.map((r) => {
              const s = current(r.id)
              return (
                <tr key={r.id ?? 'all'}>
                  <td>{r.label}</td>
                  <td>
                    <select value={s?.permission ?? 'none'} onChange={(e) => (e.target.value === 'none' ? s && unshare(s) : share(r.id, e.target.value))}>
                      <option value="none">—</option>
                      <option value="read">può vedere</option>
                      {type !== 'file' && <option value="write">può modificare</option>}
                    </select>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        <button className="ghost" onClick={onClose}>Chiudi</button>
      </div>
    </div>
  )
}
