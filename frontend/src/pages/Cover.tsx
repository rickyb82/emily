import { useEffect, useMemo, useState } from 'react'
import { get, post } from '../lib/api'
import { useAuth } from '../lib/auth'

/**
 * 📡 Copertura: la web app CoverCraft (verifica di copertura della connettività dal database dell'operatore) a tutta pagina.
 * Nessun token nel browser: l'app parla con /covercraft/api (?server=), che il backend inoltra al container con il token
 * di servizio e il nome dell'utente autenticato.
 */
export default function Cover() {
  const { me } = useAuth()
  const [sess, setSess] = useState<{ user: string; lang: string } | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetch('/covercraft/api/health', { cache: 'no-store' })
      .then(async (r) => {
        const ct = r.headers.get('content-type') || ''
        if (!r.ok || ct.includes('html')) throw new Error(`il server CoverCraft non risponde su /covercraft/ (HTTP ${r.status}): container attivo? \`./familai.sh covercraft up\`, poi \`./familai.sh update\` per ricaricare il proxy`)
        return get<{ user: string; lang: string }>('/covercraft/session')
      })
      .then((r) => setSess(r))
      .catch((e) => setErr(e.message))
  }, [])

  const src = useMemo(() => {
    if (!sess) return ''
    const q = new URLSearchParams({ server: `${window.location.origin}/covercraft`, user: sess.user, lang: sess.lang || 'it' })
    return `/covercraft/?${q.toString()}`
  }, [sess])

  async function reset() {
    setBusy(true)
    try { await post('/covercraft/logout', {}); const r = await get<{ user: string; lang: string }>('/covercraft/session'); setSess(r) } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  if (!me?.features?.covercraft_web) {
    return (
      <div className="page">
        <h2>📡 Copertura</h2>
        <p className="muted">La verifica copertura non è attiva su questo server. Un amministratore può avviarla con <code>./familai.sh covercraft up</code>.</p>
      </div>
    )
  }
  return (
    <div className="editor-layout">
      <header className="chat-header">
        <div className="title">📡 Copertura <small className="muted">· CoverCraft · fibra, rame, Open Fiber, Fastweb, ponti radio, celle</small></div>
        <div className="row">
          <a className="ghost btn-link" href={src} target="_blank" rel="noreferrer" title="Apri in una scheda a parte">⧉</a>
          <button className="ghost" disabled={busy} onClick={reset} title="Chiude la sessione dell'assistente e ricarica">↻</button>
        </div>
      </header>
      {err && <div className="error">{err}</div>}
      {src ? (
        <iframe className="editor-frame" src={src} title="CoverCraft" allow="clipboard-read; clipboard-write" />
      ) : !err && <div className="editor-frame center muted">Caricamento…</div>}
      <p className="muted small editor-hint">
        Scrivi comune, via e civico: ogni tecnologia ha un semaforo con accanto il valore originale della tabella. In chat: "che copertura c'è in via Marconi 12 a Quartu Sant'Elena?", "quali ponti radio arrivano lì?". Il database (netmap) si collega una volta dalle Impostazioni o con <code>./familai.sh covercraft db …</code>.
      </p>
    </div>
  )
}
