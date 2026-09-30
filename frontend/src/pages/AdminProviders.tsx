import { useEffect, useState } from 'react'
import { get, post, put } from '../lib/api'

interface KeyState { label: string; secret: boolean; configured: boolean; source: 'admin' | 'env' | 'none'; value: string }
interface Card {
  id: string; label: string; key: string; model_key: string | null; hint: string; testable: boolean
  key_state: KeyState; model_state: KeyState | null; active: boolean; models: { id: string; label: string }[]
}
interface Status { providers: Card[]; settings: Record<string, KeyState>; mock_active: boolean }

const SOURCE_IT = { admin: 'impostata dal pannello', env: 'dal file .env', none: 'non configurata' }

export default function AdminProviders() {
  const [st, setSt] = useState<Status | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [tests, setTests] = useState<Record<string, any>>({})
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const load = () => get<Status>('/admin/providers').then(setSt)
  useEffect(() => {
    load()
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
        <h3 style={{ margin: 0 }}>📧 Email (SMTP)</h3>
        <p className="muted small">Serve per l'invito ai nuovi membri, "password dimenticata" e il codice via email al posto della passkey. Con Gmail usa una <b>password per le app</b> (Account Google → Sicurezza → Verifica in due passaggi → Password per le app), non la password normale.</p>
        <div className="row wrap">
          <button className="ghost" onClick={() => setDraft({ ...draft, smtp_host: 'smtp.gmail.com', smtp_port: '587', smtp_security: 'starttls', smtp_from_name: 'FamilAI' })}>Preimposta Gmail</button>
          <button className="ghost" onClick={() => setDraft({ ...draft, smtp_host: 'smtp.office365.com', smtp_port: '587', smtp_security: 'starttls' })}>Outlook / Microsoft 365</button>
          <button className="ghost" onClick={() => setDraft({ ...draft, smtp_host: 'smtps.aruba.it', smtp_port: '465', smtp_security: 'ssl' })}>Aruba</button>
        </div>
        <div className="grid3">
          <label>Server SMTP <small className="muted">({s.smtp_host.value || 'non impostato'})</small><input value={draft.smtp_host ?? ''} placeholder={s.smtp_host.value || 'smtp.gmail.com'} onChange={(e) => setDraft({ ...draft, smtp_host: e.target.value })} /></label>
          <label>Porta<input value={draft.smtp_port ?? ''} placeholder={s.smtp_port.value || '587'} onChange={(e) => setDraft({ ...draft, smtp_port: e.target.value })} /></label>
          <label>Sicurezza <small className="muted">({s.smtp_security.value})</small>
            <select value={draft.smtp_security ?? s.smtp_security.value} onChange={(e) => setDraft({ ...draft, smtp_security: e.target.value })}>
              <option value="starttls">STARTTLS (587)</option><option value="ssl">SSL (465)</option><option value="none">nessuna</option>
            </select>
          </label>
          <label>Utente (email Google) <small className="muted">({s.smtp_user.value || '—'})</small><input value={draft.smtp_user ?? ''} placeholder={s.smtp_user.value || 'tuo.nome@gmail.com'} onChange={(e) => setDraft({ ...draft, smtp_user: e.target.value, smtp_from: draft.smtp_from ?? e.target.value })} /></label>
          <label>Password per le app <small className="muted">({s.smtp_password.configured ? 'impostata' : 'non impostata'})</small><input type="password" autoComplete="off" value={draft.smtp_password ?? ''} placeholder="xxxx xxxx xxxx xxxx" onChange={(e) => setDraft({ ...draft, smtp_password: e.target.value.replace(/\s+/g, '') })} /></label>
          <label>Mittente <small className="muted">({s.smtp_from.value || '—'})</small><input value={draft.smtp_from ?? ''} placeholder={s.smtp_from.value || 'tuo.nome@gmail.com'} onChange={(e) => setDraft({ ...draft, smtp_from: e.target.value })} /></label>
          <label>Nome mittente<input value={draft.smtp_from_name ?? ''} placeholder={s.smtp_from_name.value} onChange={(e) => setDraft({ ...draft, smtp_from_name: e.target.value })} /></label>
          <label>Codice email al posto della passkey <small className="muted">({s.email_mfa_fallback.value})</small>
            <select value={draft.email_mfa_fallback ?? s.email_mfa_fallback.value} onChange={(e) => setDraft({ ...draft, email_mfa_fallback: e.target.value })}>
              <option value="true">consentito</option><option value="false">solo passkey / codici di recupero</option>
            </select>
          </label>
        </div>
        <div className="row wrap">
          <button disabled={busy !== ''} onClick={() => save(['smtp_host', 'smtp_port', 'smtp_security', 'smtp_user', 'smtp_password', 'smtp_from', 'smtp_from_name', 'email_mfa_fallback'])}>Salva</button>
          <button className="ghost" disabled={busy !== '' || !s.smtp_host.configured} onClick={async () => { setBusy('mail'); setErr(''); try { const r = await post('/admin/email/test'); setMsg(`Email di prova inviata a ${r.to}`) } catch (e: any) { setErr(e.message) } finally { setBusy('') } }}>{busy === 'mail' ? 'Invio…' : '✉️ Invia email di prova a me'}</button>
        </div>
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
