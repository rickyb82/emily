import { useEffect, useMemo, useState } from 'react'
import { get, post } from '../lib/api'
import { useAuth } from '../lib/auth'

/**
 * 💶 Preventivi: la web app QuoteCraft (listino, preventivi diretta/wholesale, documenti su carta intestata, invio via MailCraft).
 * Il token di servizio non arriva al browser: token di frame firmato da Emily e proxy /quotecraft/api che aggiunge utente,
 * ruolo (admin per gli amministratori dell'app) e identità MailCraft.
 */
export default function Quote() {
  const { me } = useAuth()
  const [sess, setSess] = useState<{ user: string; lang: string; token: string; admin?: boolean } | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetch('/quotecraft/api/health', { cache: 'no-store' })
      .then(async (r) => {
        const ct = r.headers.get('content-type') || ''
        if (!r.ok || ct.includes('html')) throw new Error(`il server QuoteCraft non risponde su /quotecraft/ (HTTP ${r.status}): container attivo? \`./familai.sh quotecraft up\`, poi \`./familai.sh update\` per ricaricare il proxy`)
        return get<{ user: string; lang: string; token: string; admin?: boolean }>('/quotecraft/session')
      })
      .then((r) => setSess(r))
      .catch((e) => setErr(e.message))
  }, [])

  const src = useMemo(() => {
    if (!sess) return ''
    // il token e' quello di frame coniato da Emily (identifica la sessione dell'utente, scade da solo), non quello di servizio
    const q = new URLSearchParams({ server: `${window.location.origin}/quotecraft`, user: sess.user, lang: sess.lang || 'it', token: sess.token })
    if (!sess.admin) q.set('settings', 'off')   // nasconde le Impostazioni a chi non amministra i preventivi (il server rifiuta comunque i comandi senza il ruolo admin)
    return `/quotecraft/?${q.toString()}`
  }, [sess])

  async function reset() {
    setBusy(true)
    try { await post('/quotecraft/logout', {}); const r = await get<{ user: string; lang: string; token: string; admin?: boolean }>('/quotecraft/session'); setSess(r) } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  if (!me?.features?.quotecraft_web) {
    return (
      <div className="page">
        <h2>💶 Preventivi</h2>
        <p className="muted">I preventivi non sono attivi su questo server. Un amministratore può avviarla con <code>./familai.sh quotecraft up</code>.</p>
      </div>
    )
  }
  return (
    <div className="editor-layout">
      <header className="chat-header">
        <div className="title">💶 Preventivi <small className="muted">· QuoteCraft · listino, preventivi, documenti, invio</small></div>
        <div className="row">
          <a className="ghost btn-link" href={src} target="_blank" rel="noreferrer" title="Apri in una scheda a parte">⧉</a>
          <button className="ghost" disabled={busy} onClick={reset} title="Chiude la sessione dell'assistente e ricarica">↻</button>
        </div>
      </header>
      {err && <div className="error">{err}</div>}
      {src ? (
        <iframe className="editor-frame" src={src} title="QuoteCraft" allow="clipboard-read; clipboard-write" />
      ) : !err && <div className="editor-frame center muted">Caricamento…</div>}
      <p className="muted small editor-hint">
        Scegli canale (diretta o wholesale), cliente e voci dal listino: totali una tantum, canone e valore del contratto si aggiornano da soli. «Genera i documenti» produce PDF e DOCX sulla carta intestata, «Invia via mail» li spedisce dal tuo account di posta. In chat: "fammi un preventivo per 3 sedi in FTTH a Rossi Srl". {me?.features?.admin_apps?.includes('quotecraft') || me?.user?.role === 'admin' ? <>Listino, carta intestata e dati azienda sono nelle Impostazioni.</> : <>Listino e carta intestata li gestisce l'amministratore dei preventivi.</>}
      </p>
    </div>
  )
}
