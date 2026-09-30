import { useEffect, useState } from 'react'
import { startAuthentication, startRegistration } from '@simplewebauthn/browser'
import { get, post } from '../lib/api'
import { useAuth } from '../lib/auth'

/** Pagina mostrata a un adulto che deve registrare (o verificare) la passkey prima di usare l'app. */
export default function Enroll() {
  const { me, refresh, logout } = useAuth()
  const [codes, setCodes] = useState<string[] | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const needsVerify = me && me.user.has_passkey && !me.mfa_verified
  const [emailMfa, setEmailMfa] = useState(false)
  const [code, setCode] = useState('')
  const [sent, setSent] = useState('')
  useEffect(() => {
    get('/auth/features').then((f) => setEmailMfa(f.email_mfa)).catch(() => {})
  }, [])
  async function emailFlow() {
    setErr('')
    setBusy(true)
    try {
      if (!sent) {
        const r = await post('/auth/mfa/email/send')
        setSent(r.hint)
      } else {
        await post('/auth/mfa/email/verify', { code })
        await refresh()
      }
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function register() {
    setErr('')
    setBusy(true)
    try {
      const options = await post('/auth/webauthn/register/options')
      const credential = await startRegistration({ optionsJSON: options })
      const r = await post('/auth/webauthn/register/verify', { credential, name: navigator.platform || 'Passkey' })
      if (r.recovery_codes?.length) setCodes(r.recovery_codes)
      else await refresh()
    } catch (e: any) {
      setErr(e.message || 'Registrazione annullata')
    } finally {
      setBusy(false)
    }
  }

  async function verify() {
    setErr('')
    setBusy(true)
    try {
      const options = await post('/auth/webauthn/authenticate/options')
      const credential = await startAuthentication({ optionsJSON: options })
      await post('/auth/webauthn/authenticate/verify', { credential })
      await refresh()
    } catch (e: any) {
      setErr(e.message || 'Verifica annullata')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card stack">
        <h1>🔐 Sicurezza account</h1>
        {codes ? (
          <>
            <p><b>Salva questi codici di recupero</b> in un posto sicuro: servono se perdi la passkey. Non verranno mostrati di nuovo.</p>
            <pre className="codes">{codes.join('\n')}</pre>
            <button onClick={() => refresh()}>Ho salvato i codici, continua</button>
          </>
        ) : needsVerify ? (
          <>
            <p>Conferma l'accesso con la tua passkey.</p>
            {err && <div className="error">{err}</div>}
            <button onClick={verify} disabled={busy}>Usa la passkey</button>
            {emailMfa && (
              <>
                {sent && <input placeholder={`Codice inviato a ${sent}`} value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" />}
                <button className="ghost" onClick={emailFlow} disabled={busy}>{sent ? 'Verifica codice' : 'Ricevi un codice via email'}</button>
              </>
            )}
          </>
        ) : (
          <>
            <p>Per proteggere l'accesso da remoto, FamilAI richiede agli adulti una <b>passkey</b> (Face ID, Touch ID, Windows Hello o chiave di sicurezza) come secondo fattore.</p>
            {err && <div className="error">{err}</div>}
            <button onClick={register} disabled={busy}>{busy ? 'In attesa…' : 'Registra passkey su questo dispositivo'}</button>
          </>
        )}
        <button className="ghost" onClick={logout}>Esci</button>
      </div>
    </div>
  )
}
