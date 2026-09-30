import { useEffect, useState } from 'react'
import { get, put } from '../lib/api'

interface Prov {
  provider: string; configured: boolean; estimated_usd: number; budget_usd: number; remaining_usd: number | null
  percent: number | null; real: { ok: boolean; usd?: number; error?: string; via?: string } | null
  stats: { messages?: number; input_tokens?: number; output_tokens?: number; images?: number; videos?: number; searches?: number; cache_read_tokens?: number; cache_write_tokens?: number; cache_saved?: number }
}
interface Report {
  local?: { configured: boolean; model: string; messages: number; input_tokens: number; output_tokens: number; cloud_messages: number; avoided_usd: number; reference: string }
  since: string; providers: Prov[]; users: { name: string; cost: number; messages: number; images: number; videos: number; tokens: number }[]
  pricing: Record<string, any>; settings: Record<string, { value: string; source: string; configured: boolean; secret: boolean }>
}
const LABEL: Record<string, string> = { anthropic: 'Claude (Anthropic)', openai: 'ChatGPT (OpenAI)', gemini: 'Gemini (Google)' }
const usd = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `$${v.toFixed(2)}`)

export default function AdminCosts() {
  const [rep, setRep] = useState<Report | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [showPricing, setShowPricing] = useState(false)
  const load = () => get<Report>('/admin/costs').then(setRep).catch((e) => setErr(e.message))
  useEffect(() => {
    load()
  }, [])

  async function save(keys: string[]) {
    const values: Record<string, string> = {}
    for (const k of keys) if (k in draft) values[k] = draft[k]
    if (!Object.keys(values).length) return
    setBusy(true)
    setErr('')
    try {
      await put('/admin/providers', { values })
      setDraft((d) => { const n = { ...d }; keys.forEach((k) => delete n[k]); return n })
      setMsg('Salvato')
      await load()
    } catch (e: any) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (!rep) return <p className="muted">{err || '…'}</p>
  const s = rep.settings
  return (
    <div className="stack">
      <p className="muted">Mese corrente dal {new Date(rep.since).toLocaleDateString()}. I provider non espongono il credito residuo alle normali chiavi API: la <b>stima</b> viene dai log di FamilAI × listino prezzi; la <b>spesa reale</b> compare se inserisci una chiave Admin (Anthropic/OpenAI). Il <b>rimanente</b> è budget − spesa (reale se disponibile, altrimenti stimata).</p>
      {msg && <div className="ok">{msg}</div>}
      {err && <div className="error">{err}</div>}

      <div className="grid3">
        {rep.local?.configured && (
          <section className="card stack">
            <h3 style={{ margin: 0 }}>🏠 Modello locale (Ollama)</h3>
            <small className="muted">{rep.local.model} · gratis, i dati restano in casa</small>
            <div><small className="muted">Token elaborati in locale</small><div style={{ fontSize: 22, fontWeight: 600 }}>{(rep.local.input_tokens + rep.local.output_tokens).toLocaleString()}</div>
              <small className="muted">{rep.local.input_tokens.toLocaleString()} in ingresso · {rep.local.output_tokens.toLocaleString()} generati</small></div>
            <div><small className="muted">Messaggi</small><div><b>{rep.local.messages}</b> in locale · {rep.local.cloud_messages} nel cloud
              {rep.local.messages + rep.local.cloud_messages > 0 && <> ({Math.round(100 * rep.local.messages / (rep.local.messages + rep.local.cloud_messages))}% locale)</>}</div></div>
            <div><small className="muted">Costo evitato (stima, come se fosse {rep.local.reference})</small><div style={{ fontSize: 22, fontWeight: 600, color: 'var(--ok)' }}>{usd(rep.local.avoided_usd)}</div></div>
          </section>
        )}
        {rep.providers.map((p) => (
          <section key={p.provider} className="card stack" style={{ opacity: p.configured ? 1 : 0.55 }}>
            <h3 style={{ margin: 0 }}>{LABEL[p.provider]}</h3>
            {!p.configured && <small className="muted">chiave non configurata</small>}
            <div><small className="muted">Stima FamilAI</small><div style={{ fontSize: 22, fontWeight: 600 }}>{usd(p.estimated_usd)}</div></div>
            <div><small className="muted">Spesa reale (chiave Admin)</small>
              <div>{p.real ? (p.real.ok ? <><b>{usd(p.real.usd)}</b> <small className="muted">({p.real.via === 'api_key' ? 'con la chiave normale' : 'chiave Admin'})</small></> : <span className="error" style={{ padding: '2px 6px' }}>{p.real.error}</span>) : <span className="muted">{p.provider === 'gemini' ? 'non disponibile via API' : 'inserisci la chiave Admin sotto'}</span>}</div>
            </div>
            <div>
              <small className="muted">Budget mensile → rimanente</small>
              <div><b>{p.budget_usd > 0 ? usd(p.budget_usd) : 'nessun budget'}</b>{p.remaining_usd !== null && <> → <b style={{ color: p.remaining_usd < 0 ? 'var(--danger)' : 'var(--ok)' }}>{usd(p.remaining_usd)}</b></>}</div>
              {p.percent !== null && (
                <div style={{ height: 8, background: 'var(--bg)', borderRadius: 4, overflow: 'hidden', marginTop: 4 }}>
                  <div style={{ width: `${p.percent}%`, height: '100%', background: p.percent >= 90 ? 'var(--danger)' : p.percent >= 70 ? '#f59e0b' : 'var(--ok)' }} />
                </div>
              )}
            </div>
            <div>
              <small className="muted">Token usati questo mese</small>
              <div style={{ fontSize: 22, fontWeight: 600 }}>{((p.stats.input_tokens ?? 0) + (p.stats.output_tokens ?? 0)).toLocaleString()}</div>
              <small className="muted">
                {(p.stats.input_tokens ?? 0).toLocaleString()} in ingresso · {(p.stats.output_tokens ?? 0).toLocaleString()} generati
                {(p.stats.cache_read_tokens ?? 0) > 0 && <> · {(p.stats.cache_read_tokens ?? 0).toLocaleString()} da cache ({Math.round(100 * (p.stats.cache_read_tokens ?? 0) / Math.max(1, p.stats.input_tokens ?? 1))}% dell'ingresso, risparmiati ≈ {usd(p.stats.cache_saved ?? 0)})</>}
              </small>
            </div>
            <small className="muted">{p.stats.messages ?? 0} messaggi · {p.stats.images ?? 0} immagini · {p.stats.videos ?? 0} video · {p.stats.searches ?? 0} ricerche</small>
            <label>Budget mensile (USD)
              <input type="number" min={0} step={1} placeholder={s[`budget_${p.provider}`]?.value || '0'} value={draft[`budget_${p.provider}`] ?? ''} onChange={(e) => setDraft({ ...draft, [`budget_${p.provider}`]: e.target.value })} />
            </label>
            {p.provider !== 'gemini' && (
              <label>Chiave Admin <small className="muted">({s[`${p.provider}_admin_key`]?.configured ? s[`${p.provider}_admin_key`].value : 'non impostata'})</small>
                <input type="password" autoComplete="off" placeholder={p.provider === 'anthropic' ? 'sk-ant-admin…' : 'sk-admin…'} value={draft[`${p.provider}_admin_key`] ?? ''} onChange={(e) => setDraft({ ...draft, [`${p.provider}_admin_key`]: e.target.value })} />
              </label>
            )}
            <button disabled={busy || !(`budget_${p.provider}` in draft || `${p.provider}_admin_key` in draft)} onClick={() => save([`budget_${p.provider}`, `${p.provider}_admin_key`])}>Salva</button>
          </section>
        ))}
      </div>

      <h3>Per membro (stima, mese corrente)</h3>
      <table className="table">
        <thead><tr><th>Membro</th><th>Stima</th><th>Messaggi</th><th>Token</th><th>Immagini</th><th>Video</th></tr></thead>
        <tbody>
          {rep.users.map((u) => <tr key={u.name}><td>{u.name}</td><td>{usd(u.cost)}</td><td>{u.messages}</td><td>{u.tokens.toLocaleString()}</td><td>{u.images}</td><td>{u.videos}</td></tr>)}
          {rep.users.length === 0 && <tr><td colSpan={6} className="muted">Nessun utilizzo questo mese.</td></tr>}
        </tbody>
      </table>

      <details open={showPricing} onToggle={(e) => setShowPricing((e.target as any).open)}>
        <summary>Listino prezzi usato per la stima (USD per milione di token; immagini per pezzo; video per secondo)</summary>
        <p className="muted small">Puoi sovrascrivere singole voci con un JSON, es. <code>{'{"anthropic": {"claude-sonnet": {"in": 3, "out": 15}}, "openai": {"image": 0.04}}'}</code>. Le voci non indicate restano quelle di default. Controlla i prezzi sui siti dei provider: cambiano nel tempo.</p>
        <textarea rows={6} value={draft.pricing_json ?? s.pricing_json.value} onChange={(e) => setDraft({ ...draft, pricing_json: e.target.value })} placeholder="{}" />
        <div className="row"><button disabled={busy || !('pricing_json' in draft)} onClick={() => save(['pricing_json'])}>Salva listino</button></div>
        <pre>{JSON.stringify(rep.pricing, null, 1)}</pre>
      </details>
    </div>
  )
}
