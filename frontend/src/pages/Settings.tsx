import { useEffect, useState } from 'react'
import { startRegistration } from '@simplewebauthn/browser'
import { del, get, post } from '../lib/api'
import { useAuth } from '../lib/auth'
import TotpSetup from '../components/TotpSetup'

export default function Settings() {
  const { me, refresh } = useAuth()
  const [creds, setCreds] = useState<any[]>([])
  const [sessions, setSessions] = useState<any[]>([])
  const [codes, setCodes] = useState<string[] | null>(null)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const [pw, setPw] = useState({ current_password: '', new_password: '' })
  const [deviceName, setDeviceName] = useState('')
  const [totpSetup, setTotpSetup] = useState(false)
  const [mem, setMem] = useState<any[]>([])
  const isChild = me?.user.role === 'child'

  async function load() {
    get('/auth/memory/me').then(setMem).catch(() => {})
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
        {pol.time_windows?.length > 0 && <p className="muted">Orari in cui puoi usare Emily: {pol.time_windows.map((w: any) => `${w.start}–${w.end}`).join(', ')}</p>}
      </div>
    )
  }

  return (
    <div className="page stack narrow">
      <h2>⚙️ Impostazioni</h2>
      {msg && <div className="ok">{msg}</div>}
      {err && <div className="error">{err}</div>}

      <section className="card stack">
        <h3>🔐 Secondo fattore</h3>
        <p className="muted small">{me?.features?.passkeys !== false ? 'Serve almeno uno tra passkey e app authenticator. Puoi tenerli entrambi: al login scegli quale usare.' : 'Il secondo fattore è l\'app authenticator (codice a 6 cifre).'}</p>
        <h4>📱 App authenticator</h4>
        {me?.user.has_totp ? (
          <div className="row">
            <span>✅ Attiva</span>
            <button className="ghost" onClick={() => { if (confirm("Disattivare l'app authenticator?" + (creds.length ? '' : ' Resterai senza secondo fattore e dovrai attivarne uno al prossimo accesso.'))) run(async () => { await del('/auth/totp'); await refresh() }, 'App authenticator disattivata') }}>Disattiva</button>
          </div>
        ) : totpSetup ? (
          <TotpSetup onDone={async (rc) => { setTotpSetup(false); if (rc.length) setCodes(rc); await refresh(); setMsg('App authenticator attivata') }} onCancel={() => setTotpSetup(false)} />
        ) : (
          <div className="row"><button onClick={() => setTotpSetup(true)}>＋ Attiva app authenticator</button></div>
        )}
        <h4>🔑 Passkey</h4>
        <ul className="file-list">
          {creds.map((c) => (
            <li key={c.id}>{c.name} <small className="muted">creata {new Date(c.created_at).toLocaleDateString()}</small>
              {(creds.length > 1 || me?.user.has_totp) && <button className="icon" onClick={() => run(() => del(`/auth/webauthn/credentials/${c.id}`))}>🗑</button>}
            </li>
          ))}
        </ul>
        <div className="row">
          {me?.features?.passkeys !== false && <button onClick={() => run(addPasskey, 'Passkey aggiunta')}>＋ Aggiungi passkey</button>}
          <button className="ghost" onClick={() => run(async () => setCodes((await post('/auth/recovery-codes/regenerate')).recovery_codes), 'Nuovi codici generati')}>Rigenera codici di recupero</button>
        </div>
        {codes && <pre className="codes">{codes.join('\n')}</pre>}
      </section>

      <section className="card stack">
        <h3>🧠 Cosa ricorda di te{me?.features?.org_mode ? '' : ' e della famiglia'}</h3>
        <p className="muted">Fatti che l'assistente usa per personalizzare le risposte. Puoi cancellare quelli che ti riguardano; l'amministratore gestisce tutto dalla pagina Famiglia → Memoria. In chat puoi dire "ricordati che…" o "dimentica…".</p>
        {mem.length === 0 ? <small className="muted">Ancora nulla.</small> : (
          <ul className="file-list">
            {mem.map((m) => (
              <li key={m.id}>{m.text} <small className="muted">({m.scope === 'family' ? (me?.features?.org_mode ? 'tutti' : 'famiglia') : 'solo tu'}{m.status === 'pending' ? ' · in attesa di approvazione' : ''})</small>
                {(m.mine || me?.user.role === 'admin') && <button className="icon" title="Cancella" onClick={() => run(() => del(`/auth/memory/${m.id}`), 'Voce cancellata')}>🗑</button>}
              </li>
            ))}
          </ul>
        )}
      </section>

      {!me?.features?.org_mode && <section className="card stack">
        <h3>👧 Dispositivo per i bambini</h3>
        <p className="muted">Approvando questo dispositivo (browser), i bambini potranno accedere da qui con il loro PIN. Fallo solo su tablet/PC di casa.</p>
        <div className="row">
          <input placeholder="Nome dispositivo (es. iPad salotto)" value={deviceName} onChange={(e) => setDeviceName(e.target.value)} />
          <button disabled={!deviceName} onClick={() => run(() => post('/auth/device/trust', { name: deviceName }), 'Dispositivo approvato')}>Approva</button>
        </div>
      </section>}

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
