import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { del, get, patch, post, type User } from '../lib/api'
import AdminProviders from './AdminProviders'
import AdminMcp from './AdminMcp'

type Tab = 'members' | 'providers' | 'supervision' | 'usage' | 'devices' | 'audit' | 'mcp'
const TOOLS = ['web_search', 'generate_image', 'generate_video', 'read_document', 'artifacts', 'run_code', 'mcp']
const TOOL_IT: Record<string, string> = { web_search: 'Ricerca web', generate_image: 'Immagini', generate_video: 'Video', read_document: 'Documenti (lettura + ricerca)', artifacts: 'Artifact (pagine/app/codice con anteprima)', run_code: 'Esecuzione codice (sandbox)', mcp: 'Server MCP' }
const PROVIDERS = ['anthropic', 'openai', 'gemini']
const DAYS = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']

export default function Admin() {
  const [tab, setTab] = useState<Tab>('members')
  const [version, setVersion] = useState('')
  useEffect(() => {
    get('/health').then((h) => setVersion(h.version)).catch(() => {})
  }, [])
  return (
    <div className="page stack">
      <h2>👪 Famiglia <small className="muted">FamilAI v{version}</small></h2>
      <div className="tabs">
        {(['members', 'providers', 'supervision', 'usage', 'devices', 'audit', 'mcp'] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
            {{ members: 'Membri', providers: 'Provider AI', supervision: 'Supervisione', usage: 'Utilizzo', devices: 'Dispositivi', audit: 'Eventi', mcp: 'MCP' }[t]}
          </button>
        ))}
      </div>
      {tab === 'members' && <Members />}
      {tab === 'providers' && <AdminProviders />}
      {tab === 'supervision' && <Supervision />}
      {tab === 'usage' && <Usage />}
      {tab === 'devices' && <Devices />}
      {tab === 'audit' && <Audit />}
      {tab === 'mcp' && <AdminMcp />}
    </div>
  )
}

// ---------------- Membri + policy ----------------
function Members() {
  const [members, setMembers] = useState<User[]>([])
  const [defaults, setDefaults] = useState<Record<string, any>>({})
  const [edit, setEdit] = useState<User | null>(null)
  const [adding, setAdding] = useState(false)
  const [err, setErr] = useState('')
  const load = () => get<User[]>('/admin/members').then(setMembers)
  useEffect(() => {
    load()
    get('/admin/policy-defaults').then(setDefaults)
  }, [])

  return (
    <div className="stack">
      {err && <div className="error">{err}</div>}
      <table className="table">
        <thead><tr><th>Membro</th><th>Ruolo</th><th>Fascia</th><th>Passkey</th><th></th></tr></thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.id} className={m.is_active ? '' : 'muted'}>
              <td>{m.avatar} {m.display_name} <small className="muted">{m.email ?? m.username}</small></td>
              <td>{{ admin: 'Amministratore', adult: 'Adulto', child: 'Bambino/a' }[m.role]}</td>
              <td>{m.role === 'child' ? defaults[m.age_group]?.label ?? m.age_group : '—'}</td>
              <td>{m.role !== 'child' ? (m.has_passkey ? '✅' : '⚠️ no') : '—'}</td>
              <td><button className="ghost" onClick={() => setEdit(m)}>Modifica</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div><button onClick={() => setAdding(true)}>＋ Aggiungi membro</button></div>
      {adding && <MemberForm defaults={defaults} onClose={() => { setAdding(false); load() }} onError={setErr} />}
      {edit && <MemberForm user={edit} defaults={defaults} onClose={() => { setEdit(null); load() }} onError={setErr} />}
    </div>
  )
}

function MemberForm({ user, defaults, onClose, onError }: { user?: User; defaults: Record<string, any>; onClose: () => void; onError: (s: string) => void }) {
  const [f, setF] = useState<any>({
    username: user?.username ?? '', display_name: user?.display_name ?? '', avatar: user?.avatar ?? '🙂',
    role: user?.role ?? 'child', age_group: user?.age_group ?? 'kid', birth_year: user?.birth_year ?? '',
    email: user?.email ?? '', password: '', pin: '', is_active: user?.is_active ?? true,
  })
  const [policy, setPolicy] = useState<any>(user ? { ...user.effective_policy } : { ...(defaults['kid'] ?? {}) })
  const [advanced, setAdvanced] = useState(!!user)
  const [active, setActive] = useState<{ id: string; label: string; models: { id: string; label: string }[] }[]>([])
  useEffect(() => {
    get('/admin/providers').then((r) => setActive(r.providers.filter((p: any) => p.active && p.model_key)))
  }, [])
  const isChild = f.role === 'child'
  useEffect(() => {
    if (!user) setPolicy({ ...(defaults[isChild ? f.age_group : 'adult'] ?? {}) })
  }, [f.role, f.age_group])

  const set = (k: string, v: any) => setF({ ...f, [k]: v })
  const setP = (k: string, v: any) => setPolicy({ ...policy, [k]: v })
  const toggleList = (k: string, v: string) => {
    const l: string[] = policy[k] ?? []
    setP(k, l.includes(v) ? l.filter((x) => x !== v) : [...l, v])
  }
  const win = policy.time_windows?.[0] ?? null

  async function save() {
    onError('')
    try {
      const cleanPolicy = { ...policy }
      delete cleanPolicy.label
      delete cleanPolicy.age_group
      if (user) {
        const body: any = { display_name: f.display_name, avatar: f.avatar, role: f.role, is_active: f.is_active, policy: cleanPolicy }
        if (isChild) body.age_group = f.age_group
        if (f.birth_year) body.birth_year = Number(f.birth_year)
        if (f.password) body.password = f.password
        if (f.pin) body.pin = f.pin
        await patch(`/admin/members/${user.id}`, body)
      } else {
        const body: any = { ...f, birth_year: f.birth_year ? Number(f.birth_year) : null }
        if (!body.email) delete body.email
        if (!body.password) delete body.password
        if (!body.pin) delete body.pin
        const u = await post<User>('/admin/members', body)
        await patch(`/admin/members/${u.id}`, { policy: cleanPolicy })
      }
      onClose()
    } catch (e: any) {
      onError(e.message)
    }
  }

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal wide stack" onClick={(e) => e.stopPropagation()}>
        <h3>{user ? `Modifica ${user.display_name}` : 'Nuovo membro'}</h3>
        <div className="grid2">
          <label>Nome visualizzato<input value={f.display_name} onChange={(e) => set('display_name', e.target.value)} /></label>
          <label>Avatar (emoji)<input value={f.avatar} onChange={(e) => set('avatar', e.target.value)} maxLength={4} /></label>
          {!user && <label>Username<input value={f.username} onChange={(e) => set('username', e.target.value)} /></label>}
          <label>Ruolo
            <select value={f.role} onChange={(e) => set('role', e.target.value)}>
              <option value="child">Bambino/a</option><option value="adult">Adulto</option><option value="admin">Amministratore</option>
            </select>
          </label>
          {isChild && (
            <label>Fascia d'età
              <select value={f.age_group} onChange={(e) => set('age_group', e.target.value)}>
                <option value="young">5–8 anni</option><option value="kid">9–12 anni</option><option value="teen">13–17 anni</option>
              </select>
            </label>
          )}
          <label>Anno di nascita<input type="number" value={f.birth_year} onChange={(e) => set('birth_year', e.target.value)} /></label>
          {isChild ? (
            <label>PIN {user && '(lascia vuoto per non cambiare)'}<input value={f.pin} onChange={(e) => set('pin', e.target.value)} inputMode="numeric" /></label>
          ) : (
            <>
              {!user && <label>Email<input type="email" value={f.email} onChange={(e) => set('email', e.target.value)} /></label>}
              <label>Password {user && '(vuota = invariata)'}<input type="password" value={f.password} onChange={(e) => set('password', e.target.value)} /></label>
            </>
          )}
          {user && <label className="row"><input type="checkbox" checked={f.is_active} onChange={(e) => set('is_active', e.target.checked)} /> Attivo</label>}
        </div>

        <details open={advanced} onToggle={(e) => setAdvanced((e.target as any).open)}>
          <summary>Permessi e limiti {isChild ? '(controllo genitori)' : ''}</summary>
          <div className="stack">
            <div><b>Strumenti consentiti:</b> {TOOLS.map((t) => (
              <label key={t} className="tool-toggle"><input type="checkbox" checked={(policy.allowed_tools ?? []).includes(t)} onChange={() => toggleList('allowed_tools', t)} /> {TOOL_IT[t]}</label>
            ))}</div>
            {isChild ? (
              <div className="grid2">
                <label>Provider AI (deciso dal genitore)
                  <select value={policy.provider ?? ''} onChange={(e) => setPolicy({ ...policy, provider: e.target.value, model: '', allowed_providers: e.target.value ? [e.target.value] : PROVIDERS })}>
                    <option value="">— primo disponibile —</option>
                    {active.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                  </select>
                </label>
                <label>Modello
                  <select value={policy.model ?? ''} onChange={(e) => setP('model', e.target.value)} disabled={!policy.provider}>
                    <option value="">— default del provider —</option>
                    {(active.find((p) => p.id === policy.provider)?.models ?? []).map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                  </select>
                </label>
              </div>
            ) : (
              <div><b>Provider consentiti:</b> {PROVIDERS.map((p) => (
                <label key={p} className="tool-toggle"><input type="checkbox" checked={(policy.allowed_providers ?? []).includes(p)} onChange={() => toggleList('allowed_providers', p)} /> {p}</label>
              ))}</div>
            )}
            <div className="grid3">
              <label>Messaggi/giorno (0=∞)<input type="number" value={policy.daily_message_limit ?? 0} onChange={(e) => setP('daily_message_limit', Number(e.target.value))} /></label>
              <label>Immagini/giorno<input type="number" value={policy.daily_image_limit ?? 0} onChange={(e) => setP('daily_image_limit', Number(e.target.value))} /></label>
              <label>Video/giorno<input type="number" value={policy.daily_video_limit ?? 0} onChange={(e) => setP('daily_video_limit', Number(e.target.value))} /></label>
              <label>Upload max (MB)<input type="number" value={policy.max_upload_mb ?? 20} onChange={(e) => setP('max_upload_mb', Number(e.target.value))} /></label>
            </div>
            <div className="stack">
              <label className="row"><input type="checkbox" checked={!!win} onChange={(e) => setP('time_windows', e.target.checked ? [{ days: [0, 1, 2, 3, 4, 5, 6], start: '08:00', end: '20:00' }] : [])} /> Limita gli orari di utilizzo</label>
              {win && (
                <div className="row wrap">
                  {DAYS.map((d, i) => (
                    <label key={d} className="tool-toggle"><input type="checkbox" checked={win.days.includes(i)} onChange={() => setP('time_windows', [{ ...win, days: win.days.includes(i) ? win.days.filter((x: number) => x !== i) : [...win.days, i] }])} /> {d}</label>
                  ))}
                  <input type="time" value={win.start} onChange={(e) => setP('time_windows', [{ ...win, start: e.target.value }])} />
                  <span>→</span>
                  <input type="time" value={win.end} onChange={(e) => setP('time_windows', [{ ...win, end: e.target.value }])} />
                </div>
              )}
            </div>
            <div className="row wrap">
              <label className="tool-toggle"><input type="checkbox" checked={!!policy.moderation} onChange={(e) => setP('moderation', e.target.checked)} /> Filtro contenuti</label>
              <label className="tool-toggle"><input type="checkbox" checked={!!policy.safe_search} onChange={(e) => setP('safe_search', e.target.checked)} /> Ricerca sicura</label>
              <label className="tool-toggle"><input type="checkbox" checked={!!policy.parent_can_view} onChange={(e) => setP('parent_can_view', e.target.checked)} /> I genitori possono vedere le chat</label>
              <label className="tool-toggle"><input type="checkbox" checked={policy.can_share !== false} onChange={(e) => setP('can_share', e.target.checked)} /> Può condividere</label>
              <label className="tool-toggle"><input type="checkbox" checked={policy.can_create_projects !== false} onChange={(e) => setP('can_create_projects', e.target.checked)} /> Può creare progetti</label>
            </div>
            <label>Parole bloccate aggiuntive (separate da virgola)
              <input value={(policy.blocked_words ?? []).join(', ')} onChange={(e) => setP('blocked_words', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))} />
            </label>
            <label>Istruzioni personalizzate per l'assistente
              <textarea rows={3} value={policy.custom_instructions ?? ''} onChange={(e) => setP('custom_instructions', e.target.value)} placeholder="Es. Edoardo fa la seconda elementare e adora i dinosauri." />
            </label>
          </div>
        </details>
        <div className="row">
          <button onClick={save}>Salva</button>
          <button className="ghost" onClick={onClose}>Annulla</button>
        </div>
      </div>
    </div>
  )
}

// ---------------- Supervisione ----------------
function Supervision() {
  const nav = useNavigate()
  const [kids, setKids] = useState<User[]>([])
  const [sel, setSel] = useState<string>('')
  const [convs, setConvs] = useState<any[]>([])
  const [flagged, setFlagged] = useState<any[]>([])
  const [err, setErr] = useState('')
  useEffect(() => {
    get<User[]>('/admin/members').then((m) => setKids(m.filter((x) => x.role === 'child')))
    get('/admin/supervision/flagged').then(setFlagged)
  }, [])
  useEffect(() => {
    if (!sel) return
    setErr('')
    get(`/admin/supervision/${sel}/conversations`).then(setConvs).catch((e) => setErr(e.message))
  }, [sel])
  return (
    <div className="stack">
      <h3>⚑ Messaggi segnalati (ultimi 7 giorni)</h3>
      {flagged.length === 0 ? <p className="muted">Nessuna segnalazione.</p> : (
        <table className="table"><thead><tr><th>Quando</th><th>Chi</th><th>Motivo</th><th>Testo</th></tr></thead>
          <tbody>{flagged.map((f) => (
            <tr key={f.message_id}><td>{new Date(f.created_at).toLocaleString()}</td><td>{f.user}</td><td>{f.reason}</td>
              <td><Link to={`/c/${f.conversation_id}`}>{f.text.slice(0, 120)}</Link></td></tr>
          ))}</tbody></table>
      )}
      <h3>Conversazioni dei bambini</h3>
      <select value={sel} onChange={(e) => setSel(e.target.value)}>
        <option value="">— scegli —</option>
        {kids.map((k) => <option key={k.id} value={k.id}>{k.avatar} {k.display_name}</option>)}
      </select>
      {err && <div className="error">{err}</div>}
      <ul className="file-list">
        {convs.map((c) => (
          <li key={c.id}><a href={`/c/${c.id}`} onClick={(e) => { e.preventDefault(); nav(`/c/${c.id}`) }}>{c.title}</a>
            <small className="muted"> · {new Date(c.updated_at).toLocaleString()} · {c.provider}{c.flagged ? ` · ⚑ ${c.flagged}` : ''}</small></li>
        ))}
      </ul>
    </div>
  )
}

// ---------------- Utilizzo ----------------
function Usage() {
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => {
    get('/admin/usage?days=30').then(setRows)
  }, [])
  const byUser: Record<string, any> = {}
  for (const r of rows) {
    const u = (byUser[r.user] ||= { message: 0, image: 0, video: 0, web_search: 0, tool: 0, tokens: 0 })
    u[r.kind] = (u[r.kind] ?? 0) + r.count
    u.tokens += r.input_tokens + r.output_tokens
  }
  return (
    <table className="table">
      <thead><tr><th>Membro (30 gg)</th><th>Messaggi</th><th>Immagini</th><th>Video</th><th>Ricerche</th><th>Altri tool</th><th>Token</th></tr></thead>
      <tbody>{Object.entries(byUser).map(([u, v]) => (
        <tr key={u}><td>{u}</td><td>{v.message}</td><td>{v.image}</td><td>{v.video}</td><td>{v.web_search}</td><td>{v.tool}</td><td>{v.tokens.toLocaleString()}</td></tr>
      ))}</tbody>
    </table>
  )
}

// ---------------- Dispositivi ----------------
function Devices() {
  const [rows, setRows] = useState<any[]>([])
  const load = () => get('/admin/devices').then(setRows)
  useEffect(() => {
    load()
  }, [])
  return (
    <div className="stack">
      <p className="muted">I bambini possono accedere con il PIN solo dai dispositivi approvati da un adulto (Impostazioni → Dispositivo per i bambini).</p>
      <table className="table">
        <thead><tr><th>Nome</th><th>Approvato</th><th>Ultimo uso</th><th></th></tr></thead>
        <tbody>{rows.map((d) => (
          <tr key={d.full_id} className={d.revoked ? 'muted' : ''}>
            <td>{d.name}</td><td>{new Date(d.created_at).toLocaleString()}</td><td>{d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : '—'}</td>
            <td>{d.revoked ? 'revocato' : <button className="ghost danger" onClick={() => post(`/admin/devices/${d.full_id}/revoke`).then(load)}>Revoca</button>}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  )
}

function Audit() {
  const [rows, setRows] = useState<any[]>([])
  useEffect(() => {
    get('/admin/audit').then(setRows)
  }, [])
  return (
    <table className="table">
      <thead><tr><th>Quando</th><th>Evento</th><th>Dettaglio</th><th>IP</th></tr></thead>
      <tbody>{rows.map((a) => (
        <tr key={a.id}><td>{new Date(a.created_at).toLocaleString()}</td><td>{a.event}</td><td>{a.detail}</td><td>{a.ip}</td></tr>
      ))}</tbody>
    </table>
  )
}

// evita warning "del non usato" se in futuro serve
void del
