import { useEffect, useState } from 'react'
import { get, post, put } from '../lib/api'
import { useSearchParams } from 'react-router-dom'

interface KeyState { label: string; secret: boolean; configured: boolean; source: 'admin' | 'env' | 'none'; value: string }
interface Card {
  id: string; label: string; key: string; model_key: string | null; hint: string; testable: boolean
  key_state: KeyState; model_state: KeyState | null; active: boolean; models: { id: string; label: string }[]
}
interface Status { providers: Card[]; settings: Record<string, KeyState>; mock_active: boolean; google_redirect_uri: string }

const SMTP_PRESETS: Record<string, { label: string; host: string; port: string; security: string; user?: string }> = {
  brevo: { label: 'Brevo (ex Sendinblue) — 300/giorno gratis, EU', host: 'smtp-relay.brevo.com', port: '587', security: 'starttls' },
  smtp2go: { label: 'SMTP2GO — 1.000/mese gratis', host: 'mail.smtp2go.com', port: '587', security: 'starttls' },
  resend: { label: 'Resend — utente "resend", password = API key', host: 'smtp.resend.com', port: '465', security: 'ssl', user: 'resend' },
  mailgun: { label: 'Mailgun (EU)', host: 'smtp.eu.mailgun.org', port: '587', security: 'starttls' },
  sendgrid: { label: 'SendGrid — utente "apikey", password = API key', host: 'smtp.sendgrid.net', port: '587', security: 'starttls', user: 'apikey' },
  postmark: { label: 'Postmark', host: 'smtp.postmarkapp.com', port: '587', security: 'starttls' },
  gmail: { label: 'Gmail (password per le app)', host: 'smtp.gmail.com', port: '587', security: 'starttls' },
  outlook: { label: 'Outlook / Microsoft 365', host: 'smtp.office365.com', port: '587', security: 'starttls' },
  aruba: { label: 'Aruba', host: 'smtps.aruba.it', port: '465', security: 'ssl' },
  icloud: { label: 'iCloud Mail (password specifica per app)', host: 'smtp.mail.me.com', port: '587', security: 'starttls' },
}
const SOURCE_IT = { admin: 'impostata dal pannello', env: 'dal file .env', none: 'non configurata' }

export default function AdminProviders() {
  const [st, setSt] = useState<Status | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [tests, setTests] = useState<Record<string, any>>({})
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [mailTo, setMailTo] = useState('')
  const [mail, setMail] = useState<{ transport: string; sender: string; gmail_linked: boolean; gmail_email: string; gmail_redirect_uri: string; google_client_ready: boolean } | null>(null)
  const [params] = useSearchParams()
  const GMAIL_MSG: Record<string, string> = { ok: 'Account Google collegato: da ora le email partono tramite Gmail.', annullato: 'Collegamento Google annullato.', scaduto: 'Sessione scaduta, riprova.', errore: 'Google non ha completato il collegamento, riprova.', norefresh: 'Google non ha rilasciato il permesso permanente: rimuovi FamilAI da myaccount.google.com/permissions e ricollega.' }
  const loadMail = () => get('/admin/email/status').then(setMail).catch(() => {})
  const [mailResult, setMailResult] = useState<{ ok: boolean; text: string } | null>(null)

  const load = () => get<Status>('/admin/providers').then(setSt)
  useEffect(() => {
    load()
    loadMail()
    const g = params.get('gmail')
    if (g) setMailResult({ ok: g === 'ok', text: GMAIL_MSG[g] ?? g })
  }, [])

  async function save(keys: string[]) {
    const values: Record<string, string> = {}
    for (const k of keys) if (k in draft) values[k] = draft[k]
    if (Object.keys(values).length === 0) return
    setBusy('save')
    setErr('')
    try {
      setSt(await put<Status>('/admin/providers', { values }))
      setDraft((d) => {
        const n = { ...d }
        keys.forEach((k) => delete n[k])
        return n
      })
      setMsg('Impostazioni salvate e provider ricaricati')
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy('')
    }
  }

  async function test(id: string) {
    setBusy('test-' + id)
    setTests((t) => ({ ...t, [id]: undefined }))
    try {
      const r = await post(`/admin/providers/${id}/test`)
      setTests((t) => ({ ...t, [id]: r }))
    } catch (e: any) {
      setTests((t) => ({ ...t, [id]: { ok: false, detail: e.message } }))
    } finally {
      setBusy('')
    }
  }

  async function remove(key: string) {
    if (!confirm('Rimuovere la chiave salvata dal pannello? (resta eventualmente quella del file .env)')) return
    setBusy('save')
    try {
      setSt(await put<Status>('/admin/providers', { values: { [key]: '' } }))
    } finally {
      setBusy('')
    }
  }

  if (!st) return <p className="muted">…</p>
  const s = st.settings

  return (
    <div className="stack">
      <p className="muted">Le chiavi vengono salvate cifrate nel database (con la SECRET_KEY del server) e applicate subito, senza riavvio. Una chiave inserita qui ha la precedenza su quella del file <code>.env</code>.</p>
      {st.mock_active && <div className="error">Nessun provider AI configurato: è attivo solo il provider di prova "mock".</div>}
      {msg && <div className="ok">{msg}</div>}
      {err && <div className="error">{err}</div>}
      <div><button className="ghost" disabled={busy !== ''} onClick={async () => { setBusy('save'); try { setSt(await put<Status>('/admin/providers', { values: {} })); setMsg('Elenco modelli aggiornato dai provider') } catch (e: any) { setErr(e.message) } finally { setBusy('') } }}>🔄 Aggiorna elenco modelli</button> <small className="muted">I modelli nei menu vengono letti direttamente dalle API dei provider.</small></div>

      {st.providers.map((c) => {
        const t = tests[c.id]
        return (
          <section key={c.id} className="card stack">
            <div className="row between">
              <h3 style={{ margin: 0 }}>{c.active ? '🟢' : c.key_state.configured ? '🟡' : '⚪'} {c.label}</h3>
              <small className="muted">{c.hint}</small>
            </div>
            <div className="grid2">
              <label>
                Chiave API <small className="muted">({SOURCE_IT[c.key_state.source]}{c.key_state.value ? `: ${c.key_state.value}` : ''})</small>
                <input type="password" autoComplete="off" placeholder={c.key_state.configured ? 'Inserisci per sostituire' : 'Incolla la chiave'}
                  value={draft[c.key] ?? ''} onChange={(e) => setDraft({ ...draft, [c.key]: e.target.value })} />
              </label>
              {c.model_key && c.model_state && (
                <label>
                  Modello di default <small className="muted">({c.model_state.value})</small>
                  <input list={`models-${c.id}`} placeholder={c.model_state.value}
                    value={draft[c.model_key] ?? ''} onChange={(e) => setDraft({ ...draft, [c.model_key!]: e.target.value })} />
                  <datalist id={`models-${c.id}`}>{c.models.map((m) => <option key={m.id} value={m.id} />)}</datalist>
                </label>
              )}
            </div>
            <div className="row wrap">
              <button disabled={busy !== '' || !(c.key in draft || (c.model_key && c.model_key in draft))} onClick={() => save([c.key, ...(c.model_key ? [c.model_key] : [])])}>Salva</button>
              {c.testable && <button className="ghost" disabled={busy !== '' || !c.key_state.configured} onClick={() => test(c.id)}>{busy === 'test-' + c.id ? 'Verifica…' : '🔌 Prova connessione'}</button>}
              {c.key_state.source === 'admin' && <button className="ghost danger" disabled={busy !== ''} onClick={() => remove(c.key)}>Rimuovi chiave</button>}
              {t && <span className={t.ok ? 'ok' : 'error'}>{t.ok ? `✓ OK (${t.latency_ms} ms) — ${t.detail}` : `✗ ${t.detail}`}</span>}
            </div>
          </section>
        )
      })}

      <section className="card stack">
        <h3 style={{ margin: 0 }}>📧 Email</h3>
        <p className="muted small">Serve per l'invito ai nuovi membri, "password dimenticata" e il codice via email al posto della passkey.</p>
        {mailResult && <div className={mailResult.ok ? 'ok' : 'error'}>{mailResult.text}</div>}
        <div className="card stack" style={{ background: 'var(--bg)' }}>
          <b>Opzione 1 (consigliata): collega un account Google</b>
          {mail?.gmail_linked ? (
            <div className="row wrap">
              <span>🟢 Collegato: <b>{mail.gmail_email}</b>{mail.transport === 'gmail_oauth' && <small className="muted"> · canale attivo</small>}</span>
              <button className="ghost danger" disabled={busy !== ''} onClick={async () => { setBusy('gm'); try { await post('/admin/email/google/unlink'); await loadMail() } finally { setBusy('') } }}>Scollega</button>
            </div>
          ) : (
            <div className="stack">
              <small className="muted">Accedi con l'account Gmail di famiglia e concedi il permesso di invio: niente password per le app. Richiede Client ID/secret nella scheda "Accesso con Google" e, nel client Google, anche questo URI di reindirizzamento: <code>{mail?.gmail_redirect_uri}</code>. Finché l'app Google è in modalità "Test", aggiungi l'account tra gli utenti di test della schermata di consenso.</small>
              <div><button disabled={busy !== '' || !mail?.google_client_ready} title={!mail?.google_client_ready ? 'Prima configura Accesso con Google' : ''} onClick={async () => { const r = await get('/admin/email/google/start'); window.location.href = r.url }}>Collega account Google</button></div>
            </div>
          )}
        </div>
        <b>Opzione 2: server SMTP (servizio esterno o provider di posta)</b>
        <div className="row wrap">
          <label style={{ flex: '1 1 320px' }}>Servizio esterno preimpostato
            <select value="" onChange={(e) => { const p = SMTP_PRESETS[e.target.value]; if (p) setDraft({ ...draft, smtp_host: p.host, smtp_port: p.port, smtp_security: p.security, ...(p.user ? { smtp_user: p.user } : {}) }) }}>
              <option value="">Scegli un servizio… (compila server, porta e sicurezza)</option>
              {Object.entries(SMTP_PRESETS).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}
            </select>
          </label>
        </div>
        <details><summary className="muted small">Quale scegliere?</summary>
          <p className="muted small"><b>Brevo</b> (ex Sendinblue, azienda europea): 300 email/giorno gratis, attivazione in pochi minuti, ideale per una famiglia. <b>SMTP2GO</b>: 1.000/mese gratis, molto semplice. <b>Resend</b>, <b>Mailgun</b>, <b>SendGrid</b>, <b>Postmark</b>: ottimi ma richiedono di verificare un dominio tuo per il mittente. Con tutti questi servizi l'utente e la password SMTP sono quelli che il servizio ti mostra nella sezione "SMTP" del suo pannello (non la password dell'account), e il mittente deve essere un indirizzo verificato lì.</p>
        </details>
        <div className="grid3">
          <label>Server SMTP <small className="muted">({s.smtp_host.value || 'non impostato'})</small><input value={draft.smtp_host ?? ''} placeholder={s.smtp_host.value || 'smtp.gmail.com'} onChange={(e) => setDraft({ ...draft, smtp_host: e.target.value })} /></label>
          <label>Porta<input value={draft.smtp_port ?? ''} placeholder={s.smtp_port.value || '587'} onChange={(e) => setDraft({ ...draft, smtp_port: e.target.value })} /></label>
          <label>Sicurezza <small className="muted">({s.smtp_security.value})</small>
            <select value={draft.smtp_security ?? s.smtp_security.value} onChange={(e) => setDraft({ ...draft, smtp_security: e.target.value })}>
              <option value="starttls">STARTTLS (587)</option><option value="ssl">SSL (465)</option><option value="none">nessuna</option>
            </select>
          </label>
          <label>Utente SMTP <small className="muted">({s.smtp_user.value || '—'})</small><input value={draft.smtp_user ?? ''} placeholder={s.smtp_user.value || 'login SMTP del servizio'} onChange={(e) => setDraft({ ...draft, smtp_user: e.target.value })} /></label>
          <label>Password / chiave SMTP <small className="muted">({s.smtp_password.configured ? 'impostata' : 'non impostata'})</small><input type="password" autoComplete="off" value={draft.smtp_password ?? ''} onChange={(e) => setDraft({ ...draft, smtp_password: e.target.value.trim() })} /></label>
          <label>Mittente (indirizzo verificato) <small className="muted">({s.smtp_from.value || '—'})</small><input value={draft.smtp_from ?? ''} placeholder={s.smtp_from.value || 'familai@tuodominio.it'} onChange={(e) => setDraft({ ...draft, smtp_from: e.target.value })} /></label>
          <label>Nome mittente<input value={draft.smtp_from_name ?? ''} placeholder={s.smtp_from_name.value} onChange={(e) => setDraft({ ...draft, smtp_from_name: e.target.value })} /></label>
          <label>Canale di invio <small className="muted">({mail?.transport === 'none' ? 'nessuno configurato' : mail?.transport === 'gmail_oauth' ? 'Gmail collegato' : mail?.transport})</small>
            <select value={draft.mail_transport ?? s.mail_transport.value} onChange={(e) => setDraft({ ...draft, mail_transport: e.target.value })}>
              <option value="auto">auto (Gmail collegato se presente, altrimenti SMTP)</option><option value="gmail_oauth">solo Gmail collegato</option><option value="smtp">solo SMTP</option>
            </select>
          </label>
          <label>Codice email al posto della passkey <small className="muted">({s.email_mfa_fallback.value})</small>
            <select value={draft.email_mfa_fallback ?? s.email_mfa_fallback.value} onChange={(e) => setDraft({ ...draft, email_mfa_fallback: e.target.value })}>
              <option value="true">consentito</option><option value="false">solo passkey / codici di recupero</option>
            </select>
          </label>
        </div>
        <div className="row wrap">
          <button disabled={busy !== ''} onClick={() => save(['smtp_host', 'smtp_port', 'smtp_security', 'smtp_user', 'smtp_password', 'smtp_from', 'smtp_from_name', 'email_mfa_fallback', 'mail_transport']).then(loadMail)}>Salva</button>
          <input style={{ width: 260 }} type="email" placeholder="destinatario di prova (default: la tua email)" value={mailTo} onChange={(e) => setMailTo(e.target.value)} />
          <button className="ghost" disabled={busy !== '' || !mail || mail.transport === 'none'} title={!mail || mail.transport === 'none' ? 'Collega Google oppure compila Server SMTP e Mittente e premi Salva' : `Canale: ${mail.transport}`}
            onClick={async () => { setBusy('mail'); setMailResult(null); try { const r = await post('/admin/email/test', { to: mailTo || undefined }); setMailResult({ ok: true, text: `Email inviata a ${r.to}: controlla la casella (anche lo spam).` }) } catch (e: any) { setMailResult({ ok: false, text: e.message }) } finally { setBusy('') } }}>{busy === 'mail' ? 'Invio…' : '✉️ Invia email di prova'}</button>
        </div>
        {mail && mail.transport === 'none' && <small className="muted">Il pulsante si attiva quando un canale (Google collegato o SMTP salvato) è disponibile.</small>}
      </section>

      <section className="card stack">
        <h3 style={{ margin: 0 }}>🔑 Accesso con Google</h3>
        <p className="muted small">Permette ai membri adulti di entrare con il proprio account Google (l'email Google deve coincidere con quella del membro). È indipendente dall'account Gmail usato per l'SMTP. Crea un client OAuth "Applicazione web" su <b>console.cloud.google.com → API e servizi → Credenziali</b> e inserisci come URI di reindirizzamento autorizzati sia <code>{st.google_redirect_uri}</code> (login) sia <code>{mail?.gmail_redirect_uri}</code> (invio email).</p>
        <div className="grid2">
          <label>Client ID <small className="muted">({s.google_client_id.value || 'non impostato'})</small><input value={draft.google_client_id ?? ''} placeholder={s.google_client_id.value || '…apps.googleusercontent.com'} onChange={(e) => setDraft({ ...draft, google_client_id: e.target.value })} /></label>
          <label>Client secret <small className="muted">({s.google_client_secret.configured ? 'impostato' : 'non impostato'})</small><input type="password" autoComplete="off" value={draft.google_client_secret ?? ''} placeholder="GOCSPX-…" onChange={(e) => setDraft({ ...draft, google_client_secret: e.target.value })} /></label>
        </div>
        <div><button disabled={busy !== ''} onClick={() => save(['google_client_id', 'google_client_secret'])}>Salva</button></div>
      </section>

      <section className="card stack">
        <h3 style={{ margin: 0 }}>Altre impostazioni</h3>
        <div className="grid3">
          <label>Motore ricerca web <small className="muted">({s.web_search_provider.value})</small>
            <select value={draft.web_search_provider ?? s.web_search_provider.value} onChange={(e) => setDraft({ ...draft, web_search_provider: e.target.value })}>
              <option value="tavily">Tavily</option><option value="brave">Brave</option>
            </select>
          </label>
          <label>Provider immagini <small className="muted">({s.image_provider.value})</small>
            <select value={draft.image_provider ?? s.image_provider.value} onChange={(e) => setDraft({ ...draft, image_provider: e.target.value })}>
              <option value="auto">auto (OpenAI se presente, altrimenti Gemini)</option><option value="openai">OpenAI</option><option value="gemini">Gemini / Imagen</option>
            </select>
          </label>
          <label>Modello immagini OpenAI<input placeholder={s.image_model.value} value={draft.image_model ?? ''} onChange={(e) => setDraft({ ...draft, image_model: e.target.value })} /></label>
          <label>Modello immagini Gemini<input placeholder={s.gemini_image_model.value} value={draft.gemini_image_model ?? ''} onChange={(e) => setDraft({ ...draft, gemini_image_model: e.target.value })} /></label>
          <label>Modello video<input placeholder={s.video_model.value} value={draft.video_model ?? ''} onChange={(e) => setDraft({ ...draft, video_model: e.target.value })} /></label>
          <label>Embedding (RAG) <small className="muted">({s.embedding_provider.value})</small>
            <select value={draft.embedding_provider ?? s.embedding_provider.value} onChange={(e) => setDraft({ ...draft, embedding_provider: e.target.value })}>
              <option value="auto">auto</option><option value="openai">OpenAI</option><option value="gemini">Gemini</option><option value="none">solo parole chiave</option>
            </select>
          </label>
          <label>Modello embedding<input placeholder={s.embedding_model.value || 'default'} value={draft.embedding_model ?? ''} onChange={(e) => setDraft({ ...draft, embedding_model: e.target.value })} /></label>
        </div>
        <div><button disabled={busy !== ''} onClick={() => save(['web_search_provider', 'image_provider', 'image_model', 'gemini_image_model', 'video_model', 'embedding_provider', 'embedding_model'])}>Salva</button></div>
      </section>
    </div>
  )
}
