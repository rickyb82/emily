import { useEffect, useState } from 'react'
import { startRegistration } from '@simplewebauthn/browser'
import { del, get, post } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function Settings() {
  const { me, refresh } = useAuth()
  const [creds, setCreds] = useState<any[]>([])
  const [sessions, setSessions] = useState<any[]>([])
  const [codes, setCodes] = useState<string[] | null>(null)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [pw, setPw] = useState({ current_password: '', new_password: '' })
  const [deviceName, setDeviceName] = useState('')
  const isChild = me?.user.role === 'child'

  async function load() {
    if (isChild) return
    setCreds(await get('/auth/webauthn/credentials'))
    setSessions(await get('/auth/sessions'))
  }
  useEffect(() => {
    load()
  }, [])

  const run = async (fn: () => Promise<any>, ok = 'Fatto') => {
    setErr('')
    setMsg('')
    try {
      await fn()
      setMsg(ok)
      await load()
    } catch (e: any) {
      setErr(e.message)
    }
  }

  async function addPasskey() {
    const options = await post('/auth/webauthn/register/options')
    const credential = await startRegistration({ optionsJSON: options })
    const name = prompt('Nome per questa passkey (es. iPhone di Riccardo)') || 'Passkey'
    const r = await post('/auth/webauthn/register/verify', { credential, name })
    if (r.recovery_codes?.length) setCodes(r.recovery_codes)
    await refresh()
  }

  if (isChild) {
    const pol = me!.user.effective_policy
    return (
      <div className="page stack narrow">
        <h2>⚙️ Le mie impostazioni</h2>
        <p>Ciao {me!.user.display_name}! {me!.user.avatar}</p>
        <p className="muted">Puoi mandare fino a {pol.daily_message_limit || '∞'} messaggi e creare {pol.daily_image_limit || '∞'} immagini al giorno.</p>
        {pol.time_windows?.length > 0 && <p className="muted">Orari in cui puoi usare FamilAI: {pol.time_windows.map((w: any) => `${w.start}–${w.end}`).join(', ')}</p>}
      </div>
    )
  }

  return (
    <div className="page stack narrow">
      <h2>⚙️ Impostazioni</h2>
      {msg && <div className="ok">{msg}</div>}
      {err && <div className="error">{err}</div>}

      <section className="card stack">
        <h3>🔐 Passkey</h3>
        <ul className="file-list">
          {creds.map((c) => (
            <li key={c.id}>{c.name} <small className="muted">creata {new Date(c.created_at).toLocaleDateString()}</small>
              {creds.length > 1 && <button className="icon" onClick={() => run(() => del(`/auth/webauthn/credentials/${c.id}`))}>🗑</button>}
            </li>
          ))}
        </ul>
        <div className="row">
          <button onClick={() => run(addPasskey, 'Passkey aggiunta')}>＋ Aggiungi passkey</button>
          <button className="ghost" onClick={() => run(async () => setCodes((await post('/auth/recovery-codes/regenerate')).recovery_codes), 'Nuovi codici generati')}>Rigenera codici di recupero</button>
        </div>
        {codes && <pre className="codes">{codes.join('\n')}</pre>}
      </section>

      <section className="card stack">
        <h3>👧 Dispositivo per i bambini</h3>
        <p className="muted">Approvando questo dispositivo (browser), i bambini potranno accedere da qui con il loro PIN. Fallo solo su tablet/PC di casa.</p>
        <div className="row">
          <input placeholder="Nome dispositivo (es. iPad salotto)" value={deviceName} onChange={(e) => setDeviceName(e.target.value)} />
          <button disabled={!deviceName} onClick={() => run(() => post('/auth/device/trust', { name: deviceName }), 'Dispositivo approvato')}>Approva</button>
        </div>
      </section>

      <section className="card stack">
        <h3>🔑 Password</h3>
        <input type="password" placeholder="Password attuale" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} />
        <input type="password" placeholder="Nuova password (min 10 caratteri)" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} />
        <button onClick={() => run(() => post('/auth/password', pw), 'Password aggiornata')}>Cambia password</button>
      </section>

      <section className="card stack">
        <h3>💻 Sessioni attive</h3>
        <ul className="file-list">
          {sessions.map((s) => (
            <li key={s.id}>{s.current ? '● ' : ''}{s.ip} <small className="muted">{s.user_agent.slice(0, 60)} · {new Date(s.created_at).toLocaleString()}</small></li>
          ))}
        </ul>
        <button className="ghost" onClick={() => run(() => post('/auth/sessions/revoke-others'), 'Altre sessioni chiuse')}>Disconnetti gli altri dispositivi</button>
      </section>
    </div>
  )
}
