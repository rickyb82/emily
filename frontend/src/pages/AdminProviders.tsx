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
