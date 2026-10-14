import { useEffect, useMemo, useState } from 'react'
import { get, post } from '../lib/api'
import { useAuth } from '../lib/auth'

/**
 * 🛟 Assistenza: la web app RemoteCraft (gestionale dell'assistenza remota + server RustDesk) a tutta pagina.
 * Il token del tecnico viaggia dopo # (non arriva al proxy); l'app parla con il suo server su /remotecraft/api (?server=).
 */
export default function Remote() {
  const { me } = useAuth()
  const [token, setToken] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetch('/remotecraft/api/health', { cache: 'no-store' })
      .then(async (r) => {
        const ct = r.headers.get('content-type') || ''
        if (!r.ok || ct.includes('html')) throw new Error(`il server RemoteCraft non risponde su /remotecraft/ (HTTP ${r.status}): container attivo? \`./familai.sh remotecraft up\`, poi \`./familai.sh update\` per ricaricare il proxy`)
        return get<{ token: string }>('/remote/session')
      })
      .then((r) => setToken(r.token))
      .catch((e) => setErr(e.message))
  }, [])

  const src = useMemo(() => {
    if (!token) return ''
    const q = new URLSearchParams({ server: `${window.location.origin}/remotecraft` })
    const h = new URLSearchParams({ token, lang: 'it' })
    return `/remotecraft/?${q.toString()}#${h.toString()}`
  }, [token])

  async function logout() {
    if (!confirm('Revocare i token di assistenza di questo utente su tutti i dispositivi? Al prossimo accesso rientri automaticamente.')) return
    setBusy(true)
    try { await post('/remote/logout', {}); const r = await get<{ token: string }>('/remote/session'); setToken(r.token) } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  if (!me?.features?.remotecraft_web) {
    return (
      <div className="page">
        <h2>🛟 Assistenza</h2>
        <p className="muted">L'assistenza remota non è attiva su questo server. Un amministratore può avviarla con <code>./familai.sh remotecraft up</code>.</p>
      </div>
    )
  }
  return (
    <div className="editor-layout">
      <header className="chat-header">
        <div className="title">🛟 Assistenza <small className="muted">· RemoteCraft · clienti, PC, interventi, GDPR</small></div>
        <div className="row">
          <a className="ghost btn-link" href={src} target="_blank" rel="noreferrer" title="Apri in una scheda a parte">⧉</a>
          <button className="ghost" disabled={busy} onClick={logout} title="Revoca i token di questo utente">Scollega</button>
        </div>
      </header>
      {err && <div className="error">{err}</div>}
      {src ? (
        <iframe className="editor-frame" src={src} title="RemoteCraft" allow="clipboard-read; clipboard-write" />
      ) : !err && <div className="editor-frame center muted">Caricamento…</div>}
      <p className="muted small editor-hint">
        Telefonata in arrivo: scrivi l'ID RustDesk che il cliente legge e <b>Ctrl+Invio</b> avvia il cronometro e apre il client RustDesk. In chat: "avvia un intervento per il PC 123 456 789", "quante ore ho fatto per Lunaria a settembre?". <b>/</b> cerca, <b>?</b> aiuto.
      </p>
    </div>
  )
}
