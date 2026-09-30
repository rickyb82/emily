import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { startAuthentication } from '@simplewebauthn/browser'
import { get, post } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function Login() {
  const { refresh } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [step, setStep] = useState<'password' | 'passkey' | 'recovery' | 'emailcode'>('password')
  const [code, setCode] = useState('')
  const [features, setFeatures] = useState<{ email: boolean; email_mfa: boolean }>({ email: false, email_mfa: false })
  const [hint, setHint] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    get('/auth/features').then(setFeatures).catch(() => {})
  }, [])

  async function sendEmailCode() {
    setErr('')
    setBusy(true)
    try {
      const r = await post('/auth/mfa/email/send')
      setHint(r.hint)
      setStep('emailcode')
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function submitEmailCode(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      await post('/auth/mfa/email/verify', { code })
      await refresh()
    } catch (ex: any) {
      setErr(ex.message)
    } finally {
      setBusy(false)
    }
  }
  async function submitPassword(e: FormEvent) {
    e.preventDefault()
    setErr('')
    setBusy(true)
    try {
      const r = await post('/auth/login', { email, password })
      if (r.status === 'mfa_required') {
        setStep('passkey')
        await doPasskey()
      } else {
        await refresh()
      }
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function doPasskey() {
    setErr('')
    setBusy(true)
    try {
      const options = await post('/auth/webauthn/authenticate/options')
      const credential = await startAuthentication({ optionsJSON: options })
      await post('/auth/webauthn/authenticate/verify', { credential })
      await refresh()
    } catch (e: any) {
      setErr(e.message || 'Verifica passkey annullata')
    } finally {
      setBusy(false)
    }
  }

  async function submitRecovery(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      await post('/auth/recovery', { code })
      await refresh()
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>🏠 FamilAI</h1>
        {step === 'password' && (
          <form onSubmit={submitPassword} className="stack">
            <p className="muted">Accesso adulti</p>
            <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
            <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            {err && <div className="error">{err}</div>}
            <button disabled={busy}>{busy ? '…' : 'Continua'}</button>
            {features.email && <Link to="/forgot" className="link-btn small">Password dimenticata?</Link>}
            <Link to="/kids" className="link-btn">👧 Sono un bambino: entra con il PIN</Link>
          </form>
        )}
        {step === 'passkey' && (
          <div className="stack">
            <p>🔐 Conferma con la tua passkey (impronta, volto o chiave di sicurezza).</p>
            {err && <div className="error">{err}</div>}
            <button onClick={doPasskey} disabled={busy}>{busy ? 'In attesa…' : 'Usa la passkey'}</button>
            {features.email_mfa && <button className="ghost" onClick={sendEmailCode} disabled={busy}>Ricevi un codice via email</button>}
            <button className="ghost" onClick={() => setStep('recovery')}>Usa un codice di recupero</button>
          </div>
        )}
        {step === 'emailcode' && (
          <form onSubmit={submitEmailCode} className="stack">
            <p>Ti abbiamo inviato un codice a {hint}. Vale 10 minuti.</p>
            <input placeholder="Codice a 6 cifre" value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" required autoFocus />
            {err && <div className="error">{err}</div>}
            <button disabled={busy}>Accedi</button>
            <button type="button" className="ghost" onClick={() => setStep('passkey')}>Torna alla passkey</button>
          </form>
        )}
        {step === 'recovery' && (
          <form onSubmit={submitRecovery} className="stack">
            <p>Inserisci uno dei codici di recupero.</p>
            <input placeholder="xxxx-xxxx-xxxx" value={code} onChange={(e) => setCode(e.target.value)} required autoFocus />
            {err && <div className="error">{err}</div>}
            <button disabled={busy}>Accedi</button>
            <button type="button" className="ghost" onClick={() => setStep('passkey')}>Torna alla passkey</button>
          </form>
        )}
      </div>
    </div>
  )
}
