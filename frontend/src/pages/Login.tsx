import { useEffect, useState, type FormEvent } from 'react'
import Brand from '../components/Brand'
import { Link, useSearchParams } from 'react-router-dom'
import { startAuthentication } from '@simplewebauthn/browser'
import { get, post } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function Login() {
  const { refresh } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [step, setStep] = useState<'password' | 'passkey' | 'recovery' | 'emailcode' | 'totp'>('password')
  const [methods, setMethods] = useState<{ passkey: boolean; totp: boolean }>({ passkey: true, totp: false })
  const [code, setCode] = useState('')
  const [features, setFeatures] = useState<{ email: boolean; email_mfa: boolean; google: boolean; org_mode?: boolean }>({ email: false, email_mfa: false, google: false })
  const [params] = useSearchParams()
  const GOOGLE_ERRORS: Record<string, string> = {
    google_non_configurato: "L'accesso con Google non è configurato.",
    google_annullato: 'Accesso con Google annullato.',
    google_stato_non_valido: 'Sessione di accesso scaduta, riprova.',
    google_errore_token: 'Google non ha confermato l\'accesso, riprova.',
    google_email_non_verificata: 'Email Google non verificata.',
    google_utente_non_registrato: 'Questa email Google non corrisponde a nessun membro della famiglia: chiedi all\'amministratore di aggiungerti con lo stesso indirizzo.',
  }
  const [hint, setHint] = useState('')
  const [err, setErr] = useState(GOOGLE_ERRORS[params.get('error') ?? ''] ?? '')
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
        const m = r.methods ?? { passkey: true, totp: false }
        setMethods(m)
        setCode('')
        if (m.passkey) {
          setStep('passkey')
          await doPasskey()
        } else {
          setStep('totp')
        }
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

  async function submitTotp(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      await post('/auth/totp/verify', { code })
      await refresh()
    } catch (ex: any) {
      setErr(ex.message)
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
        <h1><Brand size="large" /></h1>
        {step === 'password' && (
          <form onSubmit={submitPassword} className="stack">
            <p className="muted">{features.org_mode ? 'Accesso Enterprise' : 'Accesso adulti'}</p>
            <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
            <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            {err && <div className="error">{err}</div>}
            <button disabled={busy}>{busy ? '…' : 'Continua'}</button>
            {features.google && (
              <a className="google-btn" href="/api/auth/google/start">
                <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.5l6.7-6.7C35.6 2.6 30.2 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.8 6C12.3 13.1 17.6 9.5 24 9.5z"/><path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z"/><path fill="#FBBC05" d="M10.4 28.8A14.5 14.5 0 0 1 9.5 24c0-1.7.3-3.3.8-4.8l-7.8-6A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.8l7.8-6z"/><path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.9 2.3-8.4 2.3-6.4 0-11.7-3.6-13.6-8.7l-7.8 6C6.5 42.6 14.6 48 24 48z"/></svg>
                Accedi con Google
              </a>
            )}
            {features.email && <Link to="/forgot" className="link-btn small">Password dimenticata?</Link>}
            {!features.org_mode && <Link to="/kids" className="link-btn">👧 Sono un bambino: entra con il PIN</Link>}
          </form>
        )}
        {step === 'passkey' && (
          <div className="stack">
            <p>🔐 Conferma con la tua passkey (impronta, volto o chiave di sicurezza).</p>
            {err && <div className="error">{err}</div>}
            <button onClick={doPasskey} disabled={busy}>{busy ? 'In attesa…' : 'Usa la passkey'}</button>
            {methods.totp && <button className="ghost" onClick={() => { setErr(''); setCode(''); setStep('totp') }} disabled={busy}>Usa l'app authenticator</button>}
            {features.email_mfa && <button className="ghost" onClick={sendEmailCode} disabled={busy}>Ricevi un codice via email</button>}
            <button className="ghost" onClick={() => setStep('recovery')}>Usa un codice di recupero</button>
          </div>
        )}
        {step === 'totp' && (
          <form onSubmit={submitTotp} className="stack">
            <p>📱 Inserisci il codice a 6 cifre della tua app authenticator.</p>
            <input placeholder="Codice a 6 cifre" value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" required autoFocus />
            {err && <div className="error">{err}</div>}
            <button disabled={busy || code.replace(/\D/g, '').length < 6}>Accedi</button>
            {methods.passkey && <button type="button" className="ghost" onClick={() => { setStep('passkey'); doPasskey() }}>Usa la passkey</button>}
            {features.email_mfa && <button type="button" className="ghost" onClick={sendEmailCode} disabled={busy}>Ricevi un codice via email</button>}
            <button type="button" className="ghost" onClick={() => { setCode(''); setStep('recovery') }}>Usa un codice di recupero</button>
          </form>
        )}
        {step === 'emailcode' && (
          <form onSubmit={submitEmailCode} className="stack">
            <p>Ti abbiamo inviato un codice a {hint}. Vale 10 minuti.</p>
            <input placeholder="Codice a 6 cifre" value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" required autoFocus />
            {err && <div className="error">{err}</div>}
            <button disabled={busy}>Accedi</button>
            <button type="button" className="ghost" onClick={() => setStep(methods.passkey ? 'passkey' : 'password')}>Indietro</button>
          </form>
        )}
        {step === 'recovery' && (
          <form onSubmit={submitRecovery} className="stack">
            <p>Inserisci uno dei codici di recupero.</p>
            <input placeholder="xxxx-xxxx-xxxx" value={code} onChange={(e) => setCode(e.target.value)} required autoFocus />
            {err && <div className="error">{err}</div>}
            <button disabled={busy}>Accedi</button>
            <button type="button" className="ghost" onClick={() => setStep(methods.passkey ? 'passkey' : 'password')}>Indietro</button>
          </form>
        )}
      </div>
    </div>
  )
}
