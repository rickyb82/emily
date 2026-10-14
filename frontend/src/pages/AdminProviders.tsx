import { useEffect, useState } from 'react'
import { get, post, put } from '../lib/api'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../lib/auth'

interface KeyState { label: string; secret: boolean; configured: boolean; source: 'admin' | 'env' | 'none'; value: string }
interface Card {
  id: string; label: string; key: string; model_key: string | null; hint: string; testable: boolean; kind?: 'url'
  key_state: KeyState; model_state: KeyState | null; active: boolean; models: { id: string; label: string }[]
}
interface Status { providers: Card[]; settings: Record<string, KeyState>; mock_active: boolean; only_mock: boolean; google_redirect_uri: string; image_models: string[] }

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
  const { me, refresh } = useAuth()
  const [st, setSt] = useState<Status | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [tests, setTests] = useState<Record<string, any>>({})
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [mailTo, setMailTo] = useState('')
  const [mail, setMail] = useState<{ transport: string; sender: string; gmail_linked: boolean; gmail_email: string; gmail_redirect_uri: string; google_client_ready: boolean } | null>(null)
  const [params] = useSearchParams()
  const GMAIL_MSG: Record<string, string> = { ok: 'Account Google collegato: da ora le email partono tramite Gmail.', annullato: 'Collegamento Google annullato.', scaduto: 'Sessione scaduta, riprova.', errore: 'Google non ha completato il collegamento, riprova.', norefresh: 'Google non ha rilasciato il permesso permanente: rimuovi Emily da myaccount.google.com/permissions e ricollega.' }
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
      {st.only_mock && <div className="error">Nessun provider AI configurato: è attivo solo il provider di prova "mock".</div>}
      {st.mock_active && !st.only_mock && <small className="muted">Il provider di prova "mock" è attivo (modalità sviluppo) accanto a quelli reali.</small>}
      {msg && <div className="ok">{msg}</div>}
      {err && <div className="error">{err}</div>}
      <div><button className="ghost" disabled={busy !== ''} onClick={async () => { setBusy('save'); try { setSt(await put<Status>('/admin/providers', { values: {} })); setMsg('Elenco modelli aggiornato dai provider') } catch (e: any) { setErr(e.message) } finally { setBusy('') } }}>🔄 Aggiorna elenco modelli</button> <small className="muted">I modelli nei menu vengono letti direttamente dalle API dei provider.</small></div>

      <UserModels st={st} draft={draft} setDraft={setDraft} save={save} busy={busy} meLock={me?.model_lock || ''} onLock={async (m) => { await post('/auth/model-lock', { model: m }); await refresh() }} />

      <h3 style={{ margin: '8px 0 0' }}>🔌 Provider e chiavi</h3>
      {st.providers.map((c) => {
        const t = tests[c.id]
        return (
          <section key={c.id} className="card stack">
            <div className="row between">
              <h3 style={{ margin: 0 }}>{c.active ? '🟢' : c.key_state.configured ? '🟡' : '⚪'} {c.label}</h3>
              <small className="muted">{c.hint}</small>
            </div>
            <div className="grid2">
              {c.kind === 'url' ? (
                <label>
                  Indirizzo del server <small className="muted">({c.key_state.configured ? c.key_state.value : 'non configurato'})</small>
                  <input type="url" autoComplete="off" placeholder={c.id === 'custom' ? 'http://192.168.4.2:8000' : c.id === 'comfyui' ? 'http://192.168.4.2:8188' : 'http://host.docker.internal:11434'}
                    value={draft[c.key] ?? ''} onChange={(e) => setDraft({ ...draft, [c.key]: e.target.value.trim() })} />
                </label>
              ) : (
                <label>
                  Chiave API <small className="muted">({SOURCE_IT[c.key_state.source]}{c.key_state.value ? `: ${c.key_state.value}` : ''})</small>
                  <input type="password" autoComplete="off" placeholder={c.key_state.configured ? 'Inserisci per sostituire' : 'Incolla la chiave'}
                    value={draft[c.key] ?? ''} onChange={(e) => setDraft({ ...draft, [c.key]: e.target.value })} />
                </label>
              )}
              {c.model_key && c.model_state && (
                <label>
                  Modello di default <small className="muted">({c.model_state.value || 'primo disponibile'}{c.models.length ? ` · ${c.models.length} trovati` : ' · elenco non ancora letto'})</small>
                  {c.models.length > 0 ? (
                    <select value={draft[c.model_key] ?? c.model_state.value ?? ''} onChange={(e) => setDraft({ ...draft, [c.model_key!]: e.target.value })}>
                      {!c.models.some((m) => m.id === (c.model_state!.value || '')) && <option value={c.model_state.value || ''}>{c.model_state.value || '— primo disponibile —'}</option>}
                      {c.models.map((m) => <option key={m.id} value={m.id}>{m.label || m.id}</option>)}
                    </select>
                  ) : (
                    <>
                      <input list={`presets-${c.id}`} placeholder={c.model_state.value || (c.id === 'comfyui' ? 'flux-dev' : 'es. openai/gpt-oss-120b')}
                        value={draft[c.model_key] ?? ''} onChange={(e) => setDraft({ ...draft, [c.model_key!]: e.target.value })} />
                      {c.id === 'comfyui' && <datalist id="presets-comfyui"><option value="flux-dev" /><option value="flux-schnell" /><option value="flux-dev-gguf" /><option value="flux-schnell-gguf" /><option value="sdxl" /><option value="sd35" /></datalist>}
                    </>
                  )}
                </label>
              )}
            </div>
            <div className="row wrap">
              <button disabled={busy !== '' || !(c.key in draft || (c.model_key && c.model_key in draft))} onClick={() => save([c.key, ...(c.model_key ? [c.model_key] : [])])}>Salva</button>
              {c.testable && <button className="ghost" disabled={busy !== '' || !c.key_state.configured} onClick={() => test(c.id)}>{busy === 'test-' + c.id ? 'Verifica…' : '🔌 Prova connessione'}</button>}
              {c.model_key && c.key_state.configured && <button className="ghost" disabled={busy !== ''} title="Rilegge l'elenco dei modelli dal provider" onClick={async () => { setBusy('save'); try { setSt(await put<Status>('/admin/providers', { values: {} })); setMsg(`Elenco modelli di ${c.label} aggiornato`) } catch (e: any) { setErr(e.message) } finally { setBusy('') } }}>🔄 Modelli</button>}
              {c.key_state.source === 'admin' && <button className="ghost danger" disabled={busy !== ''} onClick={() => remove(c.key)}>{c.kind === 'url' ? 'Disattiva' : 'Rimuovi chiave'}</button>}
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
        <p className="muted small">Raggruppate per tema; apri il gruppo che ti serve. Il pulsante Salva in fondo salva tutto.</p>
        <details className="settings-group" open><summary>🌐 Ricerca web</summary><div className="grid3">
          <label>Motore ricerca web <small className="muted">({s.web_search_provider.value})</small>
            <select value={draft.web_search_provider ?? s.web_search_provider.value} onChange={(e) => setDraft({ ...draft, web_search_provider: e.target.value })}>
              <option value="auto">auto (SearXNG in casa se attivo; Claude nativo con Claude; poi OpenAI/Gemini/Tavily/Brave)</option>
              <option value="searxng">SearXNG (in casa: Google/Bing/DDG aggregati, nessuna chiave)</option>
              <option value="openai">OpenAI (web search via API Responses)</option>
              <option value="gemini">Gemini (grounding Google Search)</option>
              <option value="tavily">Tavily</option><option value="brave">Brave</option>
            </select>
          </label>
          <label>Indirizzo SearXNG <small className="muted">({s.searxng_url.value || 'non attivo'})</small>
            <input placeholder="http://searxng:8080 (servizio del compose)" value={draft.searxng_url ?? ''} onChange={(e) => setDraft({ ...draft, searxng_url: e.target.value.trim() })} />
          </label>
          <label>Ricerca web: lettura pagine <small className="muted">({s.web_search_summarize.value})</small>
            <select value={draft.web_search_summarize ?? s.web_search_summarize.value} onChange={(e) => setDraft({ ...draft, web_search_summarize: e.target.value })}>
              <option value="auto">leggi le prime pagine e riassumile con il modello locale (se c'è)</option><option value="none">solo titoli e snippet</option>
            </select>
          </label>
          <label>Ricerca nativa di Claude <small className="muted">({s.anthropic_native_search.value})</small>
            <select value={draft.anthropic_native_search ?? s.anthropic_native_search.value} onChange={(e) => setDraft({ ...draft, anthropic_native_search: e.target.value })}>
              <option value="true">attiva quando il modello è Claude</option><option value="false">disattiva (usa sempre il motore sopra)</option>
            </select>
          </label>
        </div></details>
        <details className="settings-group"><summary>🖼️ Immagini e video</summary><div className="grid3">
          <label>Provider immagini <small className="muted">({s.image_provider.value})</small>
            <select value={draft.image_provider ?? s.image_provider.value} onChange={(e) => setDraft({ ...draft, image_provider: e.target.value })}>
              <option value="auto">auto (ComfyUI in casa se c'è, poi OpenAI, poi Gemini)</option><option value="comfyui">ComfyUI (locale: Flux / SDXL)</option><option value="openai">OpenAI</option><option value="gemini">Gemini / Imagen</option>
            </select>
          </label>
          <label>Modello immagini OpenAI <small className="muted">({s.image_model.value})</small>
            <select value={draft.image_model ?? s.image_model.value} onChange={(e) => setDraft({ ...draft, image_model: e.target.value })}>
              {Array.from(new Set([s.image_model.value, ...st.image_models])).filter(Boolean).map((m) => <option key={m} value={m}>{m}{st.image_models.includes(m) ? '' : ' (non trovato nel tuo account!)'}</option>)}
            </select>
          </label>
          <label>Modello immagini Gemini<input placeholder={s.gemini_image_model.value} value={draft.gemini_image_model ?? ''} onChange={(e) => setDraft({ ...draft, gemini_image_model: e.target.value })} /></label>
          <label>Provider video <small className="muted">({s.video_provider.value})</small>
            <select value={draft.video_provider ?? s.video_provider.value} onChange={(e) => setDraft({ ...draft, video_provider: e.target.value })}>
              <option value="auto">auto (ComfyUI se ha Wan 2.2, altrimenti Veo)</option><option value="comfyui">ComfyUI (Wan 2.2, in casa)</option><option value="gemini">Gemini / Veo</option>
            </select>
          </label>
          <label>Video ComfyUI: risoluzione <small className="muted">(Mac 832x480 · L40S 1280x704)</small><input placeholder={s.comfyui_video_size.value} value={draft.comfyui_video_size ?? ''} onChange={(e) => setDraft({ ...draft, comfyui_video_size: e.target.value.trim() })} /></label>
          <label>Video ComfyUI: frame <small className="muted">(49 = 2 s, 81 = 3 s, 121 = 5 s a 24 fps)</small><input type="number" min={9} step={4} placeholder={s.comfyui_video_frames.value} value={draft.comfyui_video_frames ?? ''} onChange={(e) => setDraft({ ...draft, comfyui_video_frames: e.target.value })} /></label>
          <label>Modello video Veo<input placeholder={s.video_model.value} value={draft.video_model ?? ''} onChange={(e) => setDraft({ ...draft, video_model: e.target.value })} /></label>
        </div></details>
        <details className="settings-group"><summary>🧭 Router Auto e server LLM di casa</summary><div className="grid3">
          <label>Router Auto (locale + cloud) <small className="muted">({s.router_mode.value})</small>
            <select value={draft.router_mode ?? s.router_mode.value} onChange={(e) => setDraft({ ...draft, router_mode: e.target.value })}>
              <option value="locale">prima il locale (risponde sempre il modello di casa; cloud solo se lo chiedi o per immagini/video/codice)</option>
              <option value="balanced">bilanciato (locale se il router è sicuro)</option>
              <option value="economico">economico (locale quando possibile)</option>
              <option value="qualita">qualità (cloud in caso di dubbio)</option>
              <option value="off">disattivato (niente voce "Auto")</option>
            </select>
          </label>
          <label>Modello locale del router <small className="muted">({s.router_model.value})</small>
            <input list="models-ollama" placeholder={s.router_model.value} value={draft.router_model ?? ''} onChange={(e) => setDraft({ ...draft, router_model: e.target.value })} />
          </label>
          <label>Provider locale del router <small className="muted">({s.router_local_provider.value})</small>
            <select value={draft.router_local_provider ?? s.router_local_provider.value} onChange={(e) => setDraft({ ...draft, router_local_provider: e.target.value })}>
              <option value="auto">auto (server LLM di casa se presente, altrimenti Ollama)</option><option value="custom">Server LLM di casa</option><option value="ollama">Ollama</option>
            </select>
          </label>
          <label>Nome del server LLM di casa<input placeholder={s.custom_llm_label.value} value={draft.custom_llm_label ?? ''} onChange={(e) => setDraft({ ...draft, custom_llm_label: e.target.value })} /></label>
          <label>Chiave API server LLM di casa <small className="muted">({s.custom_llm_key.configured ? 'impostata' : 'non necessaria se il server non la richiede'})</small>
            <input type="password" autoComplete="off" value={draft.custom_llm_key ?? ''} onChange={(e) => setDraft({ ...draft, custom_llm_key: e.target.value.trim() })} />
          </label>
          <label>Provider cloud del router <small className="muted">({s.router_cloud_provider.value})</small>
            <select value={draft.router_cloud_provider ?? s.router_cloud_provider.value} onChange={(e) => setDraft({ ...draft, router_cloud_provider: e.target.value })}>
              <option value="auto">auto (Claude, poi OpenAI, poi Gemini)</option><option value="anthropic">Claude</option><option value="openai">OpenAI</option><option value="gemini">Gemini</option>
            </select>
          </label>
        </div></details>
        <details className="settings-group"><summary>🔊 Voce (TTS)</summary><div className="grid3">
          <label>Voce naturale (TTS) <small className="muted">({s.tts_provider.value})</small>
            <select value={draft.tts_provider ?? s.tts_provider.value} onChange={(e) => setDraft({ ...draft, tts_provider: e.target.value })}>
              <option value="auto">auto (OpenAI se presente, altrimenti Gemini)</option><option value="openai">OpenAI</option><option value="gemini">Gemini</option><option value="none">disattivata</option>
            </select>
          </label>
          <label>Voce OpenAI <small className="muted">({s.tts_voice_openai.value})</small>
            <select value={draft.tts_voice_openai ?? s.tts_voice_openai.value} onChange={(e) => setDraft({ ...draft, tts_voice_openai: e.target.value })}>
              {['nova', 'coral', 'sage', 'shimmer', 'alloy', 'ash', 'ballad', 'echo', 'fable', 'onyx', 'verse'].map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </label>
          <label>Modello voce OpenAI<input placeholder={s.tts_model_openai.value} value={draft.tts_model_openai ?? ''} onChange={(e) => setDraft({ ...draft, tts_model_openai: e.target.value })} /></label>
          <label>Voce Gemini <small className="muted">({s.tts_voice_gemini.value})</small>
            <select value={draft.tts_voice_gemini ?? s.tts_voice_gemini.value} onChange={(e) => setDraft({ ...draft, tts_voice_gemini: e.target.value })}>
              {['Kore', 'Puck', 'Zephyr', 'Charon', 'Fenrir', 'Leda', 'Aoede', 'Orus', 'Callirrhoe', 'Autonoe'].map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </label>
          <label>Modello voce Gemini<input placeholder={s.tts_model_gemini.value} value={draft.tts_model_gemini ?? ''} onChange={(e) => setDraft({ ...draft, tts_model_gemini: e.target.value })} /></label>
          <label className="wide">Stile della voce <small className="muted">(istruzioni in linguaggio naturale; vuoto = voce calda e chiara, adatta ai bambini)</small>
            <input placeholder="es. Parla lentamente e con allegria, come una maestra" value={draft.tts_style ?? s.tts_style.value} onChange={(e) => setDraft({ ...draft, tts_style: e.target.value })} />
          </label>
        </div></details>
        <details className="settings-group"><summary>💬 Comportamento in chat</summary><div className="grid3">
          <label>Ragionamento OpenAI <small className="muted">({s.openai_reasoning_effort.value})</small>
            <select value={draft.openai_reasoning_effort ?? s.openai_reasoning_effort.value} onChange={(e) => setDraft({ ...draft, openai_reasoning_effort: e.target.value })}>
              <option value="auto">auto (si adatta al modello)</option><option value="none">nessuno (più veloce ed economico)</option><option value="low">basso</option><option value="medium">medio</option><option value="high">alto (più lento)</option>
            </select>
          </label>
          <label>Ragionamento visibile <small className="muted">({s.thinking_mode.value})</small>
            <select value={draft.thinking_mode ?? s.thinking_mode.value} onChange={(e) => setDraft({ ...draft, thinking_mode: e.target.value })}>
              <option value="cloud">Claude e Gemini mostrano il ragionamento (consigliato)</option><option value="all">anche i modelli locali (Qwen3 pensa prima di rispondere: più lento)</option><option value="off">spento</option>
            </select>
          </label>
          <label>Risposte lunghe <small className="muted">({s.auto_continue.value})</small>
            <select value={draft.auto_continue ?? s.auto_continue.value} onChange={(e) => setDraft({ ...draft, auto_continue: e.target.value })}>
              <option value="true">continua da solo se si interrompe (fino a 256k token totali, MAX_TOTAL_OUTPUT_TOKENS)</option><option value="false">si ferma e chiede di continuare</option>
            </select>
          </label>
          <label>Compattazione chat lunghe <small className="muted">({s.compaction_enabled.value})</small>
            <select value={draft.compaction_enabled ?? s.compaction_enabled.value} onChange={(e) => setDraft({ ...draft, compaction_enabled: e.target.value })}>
              <option value="true">attiva: oltre ~24k token i messaggi vecchi vengono riassunti e archiviati nel RAG della chat</option><option value="false">disattivata (si invia sempre tutta la cronologia)</option>
            </select>
          </label>
        </div></details>
        <details className="settings-group"><summary>🧠 Memoria e RAG</summary><div className="grid3">
          <label>Memoria di famiglia <small className="muted">({s.memory_enabled.value})</small>
            <select value={draft.memory_enabled ?? s.memory_enabled.value} onChange={(e) => setDraft({ ...draft, memory_enabled: e.target.value })}>
              <option value="true">attiva (estrazione dalle chat + approvazione)</option><option value="false">disattivata</option>
            </select>
          </label>
          <label>Memoria: approvazione automatica <small className="muted">({s.memory_auto_approve.value})</small>
            <select value={draft.memory_auto_approve ?? s.memory_auto_approve.value} onChange={(e) => setDraft({ ...draft, memory_auto_approve: e.target.value })}>
              <option value="false">no: approvo tutto io (consigliato all'inizio)</option><option value="true">sì per le voci sicure degli adulti (fiducia alta); i bambini restano in coda</option>
            </select>
          </label>
          <label>Memoria: modello per l'estrazione <small className="muted">({s.memory_model.value})</small>
            <input placeholder="auto (locale se c'è, altrimenti il più economico) — oppure es. openai/gpt-4.1-mini" value={draft.memory_model ?? ''} onChange={(e) => setDraft({ ...draft, memory_model: e.target.value })} />
          </label>
          <label>Embedding (RAG) <small className="muted">({s.embedding_provider.value})</small>
            <select value={draft.embedding_provider ?? s.embedding_provider.value} onChange={(e) => setDraft({ ...draft, embedding_provider: e.target.value })}>
              <option value="auto">auto (Ollama in locale se c'è, poi OpenAI, poi Gemini)</option><option value="ollama">Ollama (locale, es. bge-m3)</option><option value="openai">OpenAI</option><option value="gemini">Gemini</option><option value="none">solo parole chiave</option>
            </select>
          </label>
          <label>Modello embedding <small className="muted">(Ollama: bge-m3 consigliato per l'italiano; cambiandolo va rifatta l'indicizzazione)</small><input placeholder={s.embedding_model.value || 'bge-m3 / text-embedding-3-small / gemini-embedding-001'} value={draft.embedding_model ?? ''} onChange={(e) => setDraft({ ...draft, embedding_model: e.target.value })} /></label>
        </div></details>
        <div><button disabled={busy !== ''} onClick={() => save(['openai_reasoning_effort', 'web_search_provider', 'searxng_url', 'web_search_summarize', 'anthropic_native_search', 'image_provider', 'image_model', 'gemini_image_model', 'video_model', 'video_provider', 'comfyui_video_size', 'comfyui_video_frames', 'router_mode', 'router_model', 'router_cloud_provider', 'router_local_provider', 'custom_llm_label', 'custom_llm_key', 'memory_enabled', 'memory_auto_approve', 'memory_model', 'compaction_enabled', 'auto_continue', 'thinking_mode', 'tts_provider', 'tts_model_openai', 'tts_voice_openai', 'tts_model_gemini', 'tts_voice_gemini', 'tts_style', 'embedding_provider', 'embedding_model'])}>Salva</button></div>
      </section>
    </div>
  )
}


/** 🎛 Modelli per gli utenti: l'elenco (e il default) che i non amministratori trovano nel menu della chat; blocco personale dell'admin. */
function UserModels({ st, draft, setDraft, save, busy, meLock, onLock }: { st: Status; draft: Record<string, string>; setDraft: (d: Record<string, string>) => void; save: (k: string[]) => Promise<void>; busy: string; meLock: string; onLock: (m: string) => Promise<void> }) {
  const parse = (v: string): string[] => { try { const a = JSON.parse(v || '[]'); return Array.isArray(a) ? a.filter((x) => typeof x === 'string') : [] } catch { return [] } }
  const saved = parse(st.settings.user_models_json?.value || '')
  const list = draft.user_models_json !== undefined ? parse(draft.user_models_json) : saved
  const def = draft.user_default_model ?? (st.settings.user_default_model?.value || '')
  const active = st.providers.filter((p) => p.active && p.model_key && p.id !== 'comfyui')
  const routerOn = (st.settings.router_mode?.value || 'locale') !== 'off' && active.some((p) => p.id === 'ollama' || p.id === 'custom') && active.length > 1
  const groups = [...(routerOn ? [{ id: 'auto', label: 'Auto (locale + cloud)', models: [{ id: 'auto', label: 'decide il router' }] }] : []), ...active.map((p) => ({ id: p.id, label: p.label, models: p.models }))]
  const setList = (next: string[]) => {
    const d: Record<string, string> = { ...draft, user_models_json: JSON.stringify(next) }
    if (def && !next.includes(def)) d.user_default_model = next[0] || ''
    setDraft(d)
  }
  const toggle = (k: string) => setList(list.includes(k) ? list.filter((x) => x !== k) : [...list, k])
  const [lockDraft, setLockDraft] = useState(meLock)
  useEffect(() => setLockDraft(meLock), [meLock])
  const dirty = draft.user_models_json !== undefined || draft.user_default_model !== undefined
  return (
    <section className="card stack">
      <h3 style={{ margin: 0 }}>🎛 Modelli per gli utenti</h3>
      <p className="muted small">Gli utenti (non amministratori) trovano nel menu della chat <b>solo</b> i modelli spuntati qui; il pallino segna quello proposto nelle nuove chat. Se non spunti nulla, ogni provider offre solo il suo modello di default. Gli amministratori vedono sempre tutti i modelli.</p>
      {groups.length === 0 && <p className="muted">Nessun provider attivo: configura una chiave qui sotto.</p>}
      <div className="models-grid">
        {groups.map((g) => (
          <div key={g.id} className="models-col">
            <b>{g.label}</b>
            {g.models.length === 0 && <small className="muted">elenco modelli non ancora letto (🔄 Modelli)</small>}
            {g.models.map((m) => {
              const k = `${g.id}/${m.id}`
              const on = list.includes(k)
              return (
                <label key={k} className="row" style={{ gap: 6 }} title={k}>
                  <input type="checkbox" checked={on} onChange={() => toggle(k)} />
                  <input type="radio" name="user-default" disabled={!on} checked={def === k} onChange={() => setDraft({ ...draft, user_default_model: k })} title="Proposto nelle nuove chat" />
                  <span style={{ opacity: on ? 1 : .7 }}>{m.label || m.id}</span>
                </label>
              )
            })}
          </div>
        ))}
      </div>
      <div className="row wrap">
        <button disabled={busy !== '' || !dirty} onClick={() => save(['user_models_json', 'user_default_model'])}>Salva elenco utenti</button>
        <small className="muted">{list.length} modelli abilitati{def ? ` · default: ${def}` : ' · nessun default scelto (il primo dell\'elenco)'}</small>
      </div>
      <div className="card stack" style={{ background: 'var(--bg)' }}>
        <b>🔒 Il mio modello (solo per te)</b>
        <small className="muted">Come amministratore scegli qualsiasi modello in ogni chat. Se vuoi evitare di cambiarlo per sbaglio, bloccane uno: il menu della chat mostrerà solo quello finché non lo sblocchi. Vale solo per il tuo account.</small>
        <div className="row wrap">
          <select value={lockDraft} onChange={(e) => setLockDraft(e.target.value)} style={{ maxWidth: 420 }}>
            <option value="">— nessun blocco: scelgo in ogni chat —</option>
            {groups.map((g) => <optgroup key={g.id} label={g.label}>{g.models.map((m) => <option key={m.id} value={`${g.id}/${m.id}`}>{m.label || m.id}</option>)}</optgroup>)}
          </select>
          <button className="ghost" disabled={lockDraft === meLock} onClick={() => onLock(lockDraft)}>{lockDraft ? '🔒 Blocca per me' : '🔓 Sblocca'}</button>
          {meLock && <small className="ok">bloccato su {meLock}</small>}
        </div>
      </div>
    </section>
  )
}
