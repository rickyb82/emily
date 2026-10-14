import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { APP_NAME } from '../lib/brand'

/**
 * 🎓 Guida: percorso di apprendimento in stile Trailhead/Lightning (Salesforce): moduli a schede, barra di avanzamento,
 * badge, e dentro ogni modulo una demo INTERATTIVA (chat simulata, Finder, cartella APP, condivisione, posta, 2FA).
 * Tutto finto e locale: nessuna demo tocca dati veri. L'avanzamento resta nel browser (localStorage).
 */

type ModuleId = 'start' | 'chat' | 'docs' | 'apps' | 'mail' | 'share' | 'security'
const ORDER: ModuleId[] = ['start', 'chat', 'docs', 'apps', 'mail', 'share', 'security']
const META: Record<ModuleId, { title: string; icon: string; minutes: number; color: string; blurb: string }> = {
  start: { title: 'Benvenuto', icon: '🚀', minutes: 2, color: '#0176d3', blurb: `Cos'è ${APP_NAME} e come è fatta la schermata.` },
  chat: { title: 'Parlare con l\'assistente', icon: '💬', minutes: 4, color: '#1b96ff', blurb: 'Chiedere, allegare, far creare documenti e vedere gli strumenti al lavoro.' },
  docs: { title: 'Documenti e cartelle', icon: '📁', minutes: 3, color: '#2e844a', blurb: 'Il Finder di Emily: cartelle, trascinamento, menu col tasto destro.' },
  apps: { title: 'Le applicazioni', icon: '🧰', minutes: 4, color: '#9050e9', blurb: 'Word, Excel, Presentazioni, Mappe, PDF: gli editor nel browser.' },
  mail: { title: 'La posta', icon: '✉️', minutes: 3, color: '#0b827c', blurb: 'Caselle personali, lettura e risposte con l\'assistente.' },
  share: { title: 'Progetti e condivisione', icon: '🤝', minutes: 3, color: '#dd7a01', blurb: 'Lavorare insieme: progetti, chat e file condivisi con i colleghi.' },
  security: { title: 'Sicurezza', icon: '🔐', minutes: 2, color: '#ba0517', blurb: 'Accesso, secondo fattore, sessioni.' },
}
const KEY = 'familai:guide'
const scrollTop = () => document.querySelector('.guide-main')?.scrollTo({ top: 0, behavior: 'smooth' })

function useProgress() {
  const [done, setDone] = useState<ModuleId[]>(() => { try { return JSON.parse(localStorage.getItem(KEY) || '[]') } catch { return [] } })
  const complete = (m: ModuleId) => setDone((d) => { const n = d.includes(m) ? d : [...d, m]; try { localStorage.setItem(KEY, JSON.stringify(n)) } catch {} return n })
  const reset = () => { setDone([]); try { localStorage.removeItem(KEY) } catch {} }
  return { done, complete, reset }
}

export default function Guide({ onClose }: { onClose?: () => void }) {
  const { me } = useAuth()
  const nav = useNavigate()
  const goto = (path: string) => { onClose?.(); nav(path) }
  useEffect(() => {
    if (!onClose) return
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  const { done, complete, reset } = useProgress()
  const [cur, setCur] = useState<ModuleId>('start')
  const org = !!me?.features?.org_mode
  const feats = me?.features || {}
  const pct = Math.round((done.length / ORDER.length) * 100)
  const idx = ORDER.indexOf(cur)
  const next = () => { complete(cur); if (idx < ORDER.length - 1) setCur(ORDER[idx + 1]); scrollTop() }

  return (
    <div className={`guide ${onClose ? 'in-modal' : 'page'}`}>
      {onClose && <button className="guide-close" onClick={onClose} title="Chiudi (Esc)">✕</button>}
      <header className="guide-hero" style={{ ['--accent' as any]: META[cur].color }}>
        <div>
          <small>GUIDA INTERATTIVA</small>
          <h1>Impara a usare {APP_NAME}</h1>
          <p>Sette moduli brevi con demo da provare. Niente di quello che fai qui tocca i tuoi dati veri.</p>
        </div>
        <div className="guide-progress">
          <div className="ring" style={{ ['--p' as any]: pct }}><span>{pct}%</span></div>
          <small>{done.length}/{ORDER.length} moduli · {ORDER.reduce((a, m) => a + META[m].minutes, 0)} min in tutto</small>
          {done.length === ORDER.length && <span className="badge-win">🏅 Esperto di {APP_NAME}</span>}
        </div>
      </header>

      <div className="guide-body">
        <aside className="guide-nav">
          {ORDER.map((m, i) => (
            <button key={m} className={`guide-step ${cur === m ? 'active' : ''} ${done.includes(m) ? 'done' : ''}`} onClick={() => { setCur(m); scrollTop() }} style={{ ['--accent' as any]: META[m].color }}>
              <span className="step-icon">{done.includes(m) ? '✓' : META[m].icon}</span>
              <span><b>{i + 1}. {META[m].title}</b><br /><small className="muted">{META[m].minutes} min</small></span>
            </button>
          ))}
          <button className="ghost small" onClick={reset} style={{ marginTop: 8 }}>Azzera avanzamento</button>
        </aside>

        <main className="guide-main">
          <div className="module-head" style={{ ['--accent' as any]: META[cur].color }}>
            <span className="module-icon">{META[cur].icon}</span>
            <div><h2>{META[cur].title}</h2><p className="muted">{META[cur].blurb}</p></div>
          </div>

          {cur === 'start' && <ModStart org={org} />}
          {cur === 'chat' && <ModChat />}
          {cur === 'docs' && <ModDocs />}
          {cur === 'apps' && <ModApps feats={feats} />}
          {cur === 'mail' && <ModMail enabled={!!feats.mailcraft_web} />}
          {cur === 'share' && <ModShare org={org} />}
          {cur === 'security' && <ModSecurity optional={!!feats.mfa_optional} passkeys={feats.passkeys !== false} />}

          <div className="module-foot">
            {idx > 0 && <button className="ghost" onClick={() => setCur(ORDER[idx - 1])}>← Indietro</button>}
            <span style={{ flex: 1 }} />
            {cur === 'docs' && <button className="ghost" onClick={() => goto('/documents')}>Apri Documenti</button>}
            {cur === 'mail' && feats.mailcraft_web && <button className="ghost" onClick={() => goto('/mail')}>Apri la Posta</button>}
            <button className="primary" onClick={next}>{idx < ORDER.length - 1 ? 'Fatto, avanti →' : '🏅 Completa la guida'}</button>
          </div>
        </main>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ componenti didattici */
function Card({ title, children, icon }: { title: string; children: React.ReactNode; icon?: string }) {
  return <section className="g-card"><h3>{icon && <span className="g-card-icon">{icon}</span>}{title}</h3>{children}</section>
}
function Tip({ children }: { children: React.ReactNode }) { return <div className="g-tip">💡 {children}</div> }
function Steps({ items }: { items: string[] }) { return <ol className="g-steps">{items.map((s, i) => <li key={i}><span className="g-num">{i + 1}</span><span>{s}</span></li>)}</ol> }

/* ---- Modulo 1: benvenuto, mappa della schermata con hotspot ---- */
function ModStart({ org }: { org: boolean }) {
  const [spot, setSpot] = useState<string>('')
  const spots: Record<string, string> = {
    nuova: 'Apre una conversazione vuota con l\'assistente. Ogni chat ha la sua memoria e i suoi file.',
    progetti: 'Raccolgono chat e documenti di uno stesso argomento o cliente: tutto quello che allegate è a disposizione dell\'assistente nel progetto.',
    produttivita: 'Documenti (il tuo Finder con le cartelle e la cartella APP) e la Posta.',
    chat: 'L\'elenco delle tue conversazioni; quelle condivise mostrano 🔗 e il nome di chi le ha create.',
    impostazioni: 'Profilo, password, secondo fattore, memoria dell\'assistente.',
    strumenti: 'Sotto la casella di scrittura puoi accendere o spegnere gli strumenti (ricerca web, immagini, codice, app…).',
  }
  return (
    <>
      <Card title="La schermata" icon="🗺️">
        <p>Tocca i punti arancioni per scoprire ogni zona.</p>
        <div className="mock-shell">
          <div className="mock-side">
            <div className="mock-brand"><img src="/sirius-logo.png" alt="" /> {APP_NAME}</div>
            <Hot id="nuova" set={setSpot} cur={spot} className="mock-btn">＋ Nuova chat</Hot>
            <Hot id="progetti" set={setSpot} cur={spot}>📁 Progetti</Hot>
            <Hot id="produttivita" set={setSpot} cur={spot}><div className="mock-group">🧰 PRODUTTIVITÀ<div>📝 Documenti</div><div>✉️ Posta</div></div></Hot>
            <Hot id="chat" set={setSpot} cur={spot}><div className="mock-list"><div>Preventivo SRv6 3 sedi</div><div>🔗 Schema rete Nuoro</div><div>Idee newsletter</div></div></Hot>
            <Hot id="impostazioni" set={setSpot} cur={spot}>⚙️ Impostazioni</Hot>
          </div>
          <div className="mock-main">
            <div className="mock-msgs">
              <div className="mock-msg me">Fammi il preventivo per il cliente Rossi in Word</div>
              <div className="mock-msg ai">Certo. Uso la carta intestata e preparo il documento… <span className="mock-tool">📝 Documento con WordCraft</span></div>
            </div>
            <div className="mock-input">Scrivi a {APP_NAME}…</div>
            <Hot id="strumenti" set={setSpot} cur={spot}><div className="mock-tools">☑ Ricerca web ☑ Documenti ☑ App ☑ Codice</div></Hot>
          </div>
        </div>
        <div className="g-callout">{spot ? spots[spot] : 'Scegli un punto arancione…'}</div>
      </Card>
      <Card title={`Cos'è ${APP_NAME}`} icon="✨">
        <p>{APP_NAME} è l'assistente {org ? 'dell\'organizzazione' : 'di casa'}: parla in italiano, legge i tuoi documenti, scrive file Word, Excel, PowerPoint e PDF, disegna mappe e schemi, gestisce la posta — tutto su un server {org ? 'aziendale' : 'di casa'}, non in cloud, con le app open source integrate.</p>
        <Tip>Puoi chiederle le cose come le chiederesti a un collega: «riassumi questo PDF», «fammi un foglio con i costi del mese», «rispondi a Luca che va bene giovedì».</Tip>
      </Card>
    </>
  )
}
function Hot({ id, cur, set, children, className = '' }: { id: string; cur: string; set: (s: string) => void; children: React.ReactNode; className?: string }) {
  return <div className={`hot ${cur === id ? 'on' : ''} ${className}`} onClick={() => set(id)}><span className="hot-dot" />{children}</div>
}

/* ---- Modulo 2: chat simulata ---- */
const DEMO_PROMPTS: { q: string; steps: string[]; a: string; file?: string }[] = [
  { q: 'Fammi un preventivo in Word per 3 sedi collegate in fibra, 1.200 € al mese', steps: ['📚 Leggo la carta intestata', '📝 Documento con WordCraft', '💾 salvato: Preventivo_3_sedi.docx'], a: 'Ecco il preventivo su carta intestata: 3 sedi, canone 1.200 €/mese, attivazione inclusa. Lo apri con ✏️ Modifica per ritoccarlo, oppure dimmi cosa cambiare.', file: '📄 Preventivo_3_sedi.docx' },
  { q: 'Disegnami lo schema di rete: router, switch, 2 PC, una stampante e un NAS', steps: ['🧠 IdeaCraft: build_map (diagramma)', '🔍 validate_network: nessun errore', '💾 salvato: schema_rete.svg + .ideacraft.json'], a: 'Schema pronto: router verso Internet, switch in VLAN 100 con i quattro dispositivi. L\'immagine è qui sotto; il file si modifica nell\'editor.', file: '🖼️ schema_rete.svg' },
  { q: 'Quante mail non lette ho?', steps: ['✉️ MailCraft: sync', '✉️ list_messages (non lette)'], a: 'Hai 4 mail non lette: due da Luca sul sopralluogo, una fattura Aruba e una newsletter. Vuoi che risponda a Luca?' },
  { q: 'Riassumi il PDF allegato in 5 punti', steps: ['📎 Allegato: contratto.pdf', '📚 Lettura documento'], a: '1. Durata 24 mesi · 2. Canone 890 €/mese · 3. SLA 4 ore · 4. Recesso con 60 giorni di preavviso · 5. Rinnovo tacito annuale.' },
]
function ModChat() {
  const [log, setLog] = useState<{ role: 'me' | 'ai'; text: string; steps?: string[]; file?: string; typing?: boolean }[]>([])
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { box.current?.scrollTo({ top: 9e6, behavior: 'smooth' }) }, [log])
  async function ask(p: typeof DEMO_PROMPTS[number]) {
    if (busy) return
    setBusy(true)
    setLog((l) => [...l, { role: 'me', text: p.q }])
    await sleep(500)
    setLog((l) => [...l, { role: 'ai', text: '', steps: [], typing: true }])
    for (const s of p.steps) { await sleep(700); setLog((l) => { const c = [...l]; const last = { ...c[c.length - 1] }; last.steps = [...(last.steps || []), s]; c[c.length - 1] = last; return c }) }
    await sleep(400)
    for (let i = 1; i <= p.a.length; i += 3) { await sleep(12); setLog((l) => { const c = [...l]; c[c.length - 1] = { ...c[c.length - 1], text: p.a.slice(0, i) }; return c }) }
    setLog((l) => { const c = [...l]; c[c.length - 1] = { ...c[c.length - 1], text: p.a, typing: false, file: p.file }; return c })
    setBusy(false)
  }
  return (
    <>
      <Card title="Prova: scegli una domanda" icon="🎮">
        <div className="demo-chat" ref={box}>
          {log.length === 0 && <p className="muted center">Qui vedrai la conversazione simulata.</p>}
          {log.map((m, i) => (
            <div key={i} className={`mock-msg ${m.role}`}>
              {m.steps?.map((s, j) => <div key={j} className="mock-tool">✓ {s}</div>)}
              {m.text}{m.typing && <span className="caret" />}
              {m.file && <div className="mock-file">{m.file} <span className="mock-edit">✏️ Modifica</span></div>}
            </div>
          ))}
        </div>
        <div className="demo-prompts">{DEMO_PROMPTS.map((p) => <button key={p.q} className="ghost" disabled={busy} onClick={() => ask(p)}>{p.q}</button>)}</div>
      </Card>
      <Card title="Cosa hai visto" icon="🔎">
        <Steps items={[
          'Le righe con ✓ sono gli strumenti che l\'assistente usa (leggere un documento, WordCraft, IdeaCraft, la posta): puoi aprirle per vedere i dettagli.',
          'I file creati compaiono nella chat con ✏️ Modifica: si aprono nell\'editor dentro il browser, senza scaricare nulla.',
          'Per allegare un file usa 📎 o trascinalo nella casella; l\'assistente lo legge e può convertirlo o modificarlo.',
          'Sotto la casella accendi o spegni gli strumenti; «Rigenera» rifà l\'ultima risposta, magari con un altro modello.',
        ]} />
        <Tip>Sii concreto: «fammi un preventivo per il cliente Rossi, 3 sedi, 1.200 €/mese, su carta intestata» funziona meglio di «fammi un preventivo».</Tip>
      </Card>
    </>
  )
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/* ---- Modulo 3: Finder simulato con drag & drop ---- */
function ModDocs() {
  const [folders, setFolders] = useState<{ id: string; name: string; files: string[] }[]>([{ id: 'cli', name: 'Clienti', files: [] }, { id: 'off', name: 'Offerte 2026', files: ['Preventivo_Nuoro.pdf'] }])
  const [loose, setLoose] = useState(['Preventivo_3_sedi.docx', 'schema_rete.svg', 'Costi_ottobre.xlsx'])
  const [open, setOpen] = useState<string>('')
  const [msg, setMsg] = useState('Trascina un file su una cartella, oppure crea una cartella nuova.')
  const [over, setOver] = useState('')
  const drop = (fid: string) => (e: React.DragEvent) => { e.preventDefault(); setOver(''); const f = e.dataTransfer.getData('text/plain'); if (!f) return; setLoose((l) => l.filter((x) => x !== f)); setFolders((fs) => fs.map((x) => x.id === fid ? { ...x, files: [...x.files, f] } : x)); setMsg(`«${f}» è ora in «${folders.find((x) => x.id === fid)?.name}». Nelle chat i link continuano a funzionare: i file si riconoscono dall'id, non dalla cartella.`) }
  const current = folders.find((f) => f.id === open)
  return (
    <>
      <Card title="Prova: il Finder" icon="🎮">
        <div className="demo-finder">
          <div className="crumbs"><button className="crumb" onClick={() => setOpen('')}>Documenti</button>{current && <><span className="muted">›</span><b className="crumb">{current.name}</b></>}</div>
          <div className="finder-grid demo">
            {!current && <button className="tile folder-tile app-folder" onClick={() => setMsg('La cartella APP contiene le applicazioni: la vedi nel modulo successivo.')}><span className="ios-folder">{['app-word', 'app-excel', 'app-deck', 'app-map', 'app-pdf', 'app-mail'].map((c) => <span key={c} className={`mini-app ${c}`} />)}</span><span className="tile-name">APP</span></button>}
            {!current && folders.map((f) => (
              <button key={f.id} className={`tile folder-tile ${over === f.id ? 'drop' : ''}`} onDragOver={(e) => { e.preventDefault(); setOver(f.id) }} onDragLeave={() => setOver('')} onDrop={drop(f.id)} onClick={() => { setOpen(f.id); setMsg('Dentro una cartella: il percorso in alto ti riporta indietro.') }}>
                <span className="folder-icon"><span className="folder-tab" /></span><span className="tile-name">{f.name}</span><small className="muted">{f.files.length ? `${f.files.length} file` : 'vuota'}</small>
              </button>
            ))}
            {(current ? current.files : loose).map((f) => (
              <button key={f} className="tile file-tile" draggable={!current} onDragStart={(e) => e.dataTransfer.setData('text/plain', f)} onContextMenu={(e) => { e.preventDefault(); setMsg('Tasto destro (o ⋯): Apri, Scarica, Rinomina, Sposta in…, Elimina.') }} onClick={() => setMsg(`Un clic seleziona, un secondo clic (o doppio clic) apre «${f}» nell'editor.`)}>
                <DemoIcon name={f} /><span className="tile-name">{f}</span>
              </button>
            ))}
          </div>
          <div className="row" style={{ gap: 8 }}>
            <button className="ghost" onClick={() => { const n = `Nuova cartella ${folders.length - 1}`; setFolders((f) => [...f, { id: n, name: n, files: [] }]); setMsg(`Creata «${n}»: col tasto destro la rinomini o la elimini (i file tornano su, non si perdono).`) }}>📁 Nuova cartella</button>
            <button className="ghost" onClick={() => setMsg('📎 Carica: scegli file dal computer; finiscono nella cartella in cui ti trovi, e se il nome esiste già diventa «nome 2».')}>📎 Carica</button>
          </div>
        </div>
        <div className="g-callout">{msg}</div>
      </Card>
      <Card title="Da ricordare" icon="📌">
        <Steps items={['I progetti compaiono come cartelle verdi automatiche: dentro ci sono i file di quel progetto.', 'La ricerca in alto cerca in tutte le cartelle.', 'Spostare o rinominare non rompe nulla: chat, progetti e indice usano l\'identità del file, non il nome.', 'I nomi doppi vengono numerati da soli (Finder-style): «documento 2.docx».']} />
      </Card>
    </>
  )
}
function DemoIcon({ name }: { name: string }) {
  const l = name.toLowerCase()
  const cls = l.endsWith('.docx') ? 'app-word' : l.endsWith('.xlsx') ? 'app-excel' : l.endsWith('.pptx') ? 'app-deck' : l.endsWith('.pdf') ? 'app-pdf' : ''
  const g = l.endsWith('.docx') ? 'W' : l.endsWith('.xlsx') ? 'X' : l.endsWith('.pptx') ? 'P' : l.endsWith('.pdf') ? 'PDF' : ''
  if (!cls) return <span className="file-icon generic">🖼️</span>
  return <span className={`file-icon doc ${cls}`}><span className="file-icon-corner" /><b>{g}</b></span>
}

/* ---- Modulo 4: cartella APP e gli editor ---- */
function ModApps({ feats }: { feats: Record<string, any> }) {
  const apps = [
    { k: 'word', cls: 'app-word', g: 'W', name: 'Documento', app: 'WordCraft', desc: 'Lettere, relazioni, preventivi, contratti. Stili, tabelle, immagini, revisioni; salva in .docx, PDF, ODT. Salvataggio automatico.', on: feats.wordcraft_web },
    { k: 'excel', cls: 'app-excel', g: 'X', name: 'Foglio', app: 'GridCraft', desc: 'Tabelle con formule Excel, formati condizionali, grafici, pivot; file .xlsx e CSV.', on: feats.gridcraft_web },
    { k: 'deck', cls: 'app-deck', g: 'P', name: 'Presentazione', app: 'DeckCraft', desc: 'Slide con temi, immagini e grafici; esporta .pptx e PDF.', on: feats.deckcraft_web },
    { k: 'map', cls: 'app-map', g: '◎', name: 'Mappa', app: 'IdeaCraft', desc: 'Mappe mentali e diagrammi (schemi di rete, flowchart, organigrammi) con controllo automatico di IP e VLAN; esporta SVG, PNG, draw.io.', on: feats.ideacraft_web },
    { k: 'pdf', cls: 'app-pdf', g: 'PDF', name: 'PDF', app: 'PdfCraft', desc: 'Nuovo PDF vuoto o modifica di uno esistente: pagine, moduli, firme, commenti, unione e divisione.', on: feats.pdfcraft_web },
    { k: 'mail', cls: 'app-mail', g: '✉', name: 'Posta', app: 'MailCraft', desc: 'Le tue caselle IMAP/SMTP, stile Gmail, con l\'assistente che legge e risponde per te.', on: feats.mailcraft_web },
    { k: 'remote', cls: 'app-remote', g: '🛟', name: 'Assistenza', app: 'RemoteCraft', desc: 'Assistenza remota: clienti, PC con ID RustDesk, interventi con cronometro e ore fatturabili, consensi GDPR e report; apre il client RustDesk sul PC del cliente.', on: feats.remotecraft_web },
    { k: 'cover', cls: 'app-cover', g: '📡', name: 'Copertura', app: 'CoverCraft', desc: 'Verifica di copertura a un indirizzo dal database dell\'operatore: fibra FTTH/FTTC e rame TIM, Open Fiber scala per scala, Fastweb, rete propria, ponti radio con distanza e direzione, celle mobili; storico delle verifiche.', on: feats.covercraft_web },
  ]
  const [sel, setSel] = useState(apps[0])
  const [openF, setOpenF] = useState(false)
  return (
    <>
      <Card title="Prova: apri la cartella APP" icon="🎮">
        {!openF ? (
          <div className="center"><button className="tile folder-tile app-folder big" onClick={() => setOpenF(true)}><span className="ios-folder">{apps.map((a) => <span key={a.k} className={`mini-app ${a.cls}`}>{a.g}</span>)}</span><span className="tile-name">APP</span></button><p className="muted small">Clicca la cartella</p></div>
        ) : (
          <div className="ios-panel inline">
            <div className="ios-apps">{apps.map((a) => <button key={a.k} className={`ios-app ${sel.k === a.k ? 'sel' : ''}`} onClick={() => setSel(a)}><span className={`app-icon ${a.cls}`}>{a.g}</span><span>{a.name}</span>{!a.on && <small className="muted">non attiva</small>}</button>)}</div>
            <div className="g-callout"><b>{sel.name} · {sel.app}</b><br />{sel.desc}{!sel.on && <><br /><small className="muted">Su questo server non è ancora attiva: chiedi all'amministratore.</small></>}</div>
          </div>
        )}
      </Card>
      <Card title="Come si lavora in un editor" icon="🖥️">
        <Steps items={['Dalla cartella APP crei un file nuovo nella cartella in cui ti trovi; da un file esistente usi ✏️ Modifica (in chat, in Documenti, nei progetti).', 'Il titolo in alto si clicca per rinominare; File › Salva (o Ctrl/Cmd+S) salva su Emily, non scarica. WordCraft salva anche da solo.', 'File › Esporta crea un nuovo file accanto (PDF, CSV…). Chiudi torna a Documenti.', 'In chat puoi dire «apri il preventivo e cambia il canone a 1.300 €»: l\'assistente modifica il file e lo salva; l\'anteprima che mostra è il documento vero.']} />
        <Tip>Serve un browser moderno (Chrome, Edge, Safari recenti): gli editor girano in WebAssembly e usano WebGPU o WebGL2.</Tip>
      </Card>
    </>
  )
}

/* ---- Modulo 5: posta ---- */
function ModMail({ enabled }: { enabled: boolean }) {
  const [step, setStep] = useState(0)
  const mails = [{ f: 'Luca Bianchi', s: 'Re: Sopralluogo giovedì', t: 'Confermo per le 10, porto le planimetrie…', u: true }, { f: 'Aruba', s: 'Fattura n. 2026-1187', t: 'In allegato la fattura del mese…', u: true, a: true }, { f: 'Anna Rossi', s: 'Riunione di lunedì', t: 'Spostiamo alle 15?', u: false }]
  return (
    <>
      <Card title="Prova: la casella" icon="🎮">
        <div className="demo-mail">
          <div className="dm-nav"><b>✎ Scrivi</b><div className="on">Inbox <span>2</span></div><div>Speciali</div><div>Inviati</div><div>Bozze</div><div>Archivio</div></div>
          <div className="dm-list">{mails.map((m, i) => <div key={i} className={`dm-row ${m.u ? 'unread' : ''} ${step === 1 && i === 0 ? 'sel' : ''}`} onClick={() => setStep(1)}><span>☆</span><b>{m.f}</b><span>{m.s} — <span className="muted">{m.t}</span></span>{m.a && <span>📎</span>}</div>)}</div>
          <div className="dm-read">{step === 0 ? <p className="muted center">Clicca una mail</p> : step === 1 ? <><b>Re: Sopralluogo giovedì</b><br /><small className="muted">Luca Bianchi · a: te</small><p>Confermo per le 10, porto le planimetrie. Ci vediamo in sede.</p><div className="row"><button className="ghost" onClick={() => setStep(2)}>↩ Rispondi</button><button className="ghost">↪ Inoltra</button><button className="ghost">📥 Archivia</button></div></> : <><b>Rispondi a Luca</b><div className="mock-input tall">Perfetto Luca, a giovedì alle 10. Riccardo</div><div className="row"><button className="primary" onClick={() => setStep(3)}>Invia</button></div></>}{step === 3 && <p className="g-tip">✓ Inviata (nella demo non parte nulla).</p>}</div>
        </div>
      </Card>
      <Card title="Configurare la tua casella" icon="⚙️">
        <Steps items={['Produttività › Posta, poi Impostazioni › Account dentro l\'app: indirizzo e password; i server dei provider più comuni (Gmail, Outlook, Aruba, PEC, Libero, TIM, Fastweb…) sono già noti.', 'Oppure in chat: «configura la mia casella info@…»: l\'assistente ti chiede la password e fa il test.', 'Puoi avere più caselle; ognuno vede solo le proprie, anche l\'assistente.', 'In chat: «leggi le non lette», «rispondi a Luca che va bene», «inoltra la fattura ad Anna con il PDF del preventivo». Prima di inviare ti mostra sempre il testo e aspetta un sì.']} />
        <Tip>Gmail e Outlook vogliono una «password per le app», non quella normale. {!enabled && 'Su questo server la posta non è ancora attiva.'}</Tip>
      </Card>
    </>
  )
}

/* ---- Modulo 6: condivisione con suggerimenti ---- */
function ModShare({ org }: { org: boolean }) {
  const people = [{ n: 'Anna Rossi', e: 'anna.rossi@azienda.it', a: '👩' }, { n: 'Luca Bianchi', e: 'luca.bianchi@azienda.it', a: '🧑' }, { n: 'Emiliano Verdi', e: 'emiliano@azienda.it', a: '👨' }, { n: 'Alessio Sacchetti', e: 'alessio@azienda.it', a: '🧔' }]
  const [q, setQ] = useState('')
  const [shared, setShared] = useState<typeof people>([])
  const hits = useMemo(() => q.trim() ? people.filter((p) => !shared.includes(p) && (p.n + ' ' + p.e).toLowerCase().includes(q.trim().toLowerCase())) : [], [q, shared])
  return (
    <>
      <Card title="Prova: condividi una chat" icon="🎮">
        <div className="modal demo">
          <h3>Condividi</h3>
          <div className="share-search">
            <div className="row" style={{ gap: 6 }}><input placeholder="Nome o email della persona…" value={q} onChange={(e) => setQ(e.target.value)} /><select><option>può vedere</option><option>può modificare</option></select></div>
            {hits.length > 0 && <ul className="suggest static">{hits.map((p) => <li key={p.e} onClick={() => { setShared((s) => [...s, p]); setQ('') }}><span className="kid-avatar small">{p.a}</span><span><b>{p.n}</b><br /><small className="muted">{p.e}</small></span></li>)}</ul>}
          </div>
          <div className="share-list">
            <div className="row between"><span>{org ? '🏢 Tutta l\'organizzazione' : '👪 Tutta la famiglia'}</span><select><option>—</option><option>può vedere</option></select></div>
            {shared.map((p) => <div key={p.e} className="row between"><span>{p.a} {p.n}</span><span className="row"><select><option>può vedere</option><option>può modificare</option></select><button className="icon" onClick={() => setShared((s) => s.filter((x) => x !== p))}>✕</button></span></div>)}
            {shared.length === 0 && <small className="muted">Per ora lo vedi solo tu. Prova a scrivere «an» o «luca».</small>}
          </div>
        </div>
      </Card>
      <Card title="Progetti" icon="📁">
        <Steps items={['Un progetto raccoglie chat e file su un tema (un cliente, una gara, un evento): l\'assistente usa tutti i documenti del progetto quando rispondi lì dentro.', 'Dalla chat, con 📁 scegli il progetto: anche i file già allegati si spostano con lei.', 'Condividere un progetto condivide tutto il suo contenuto; «può modificare» permette di aggiungere file e chat.', 'Le chat condivise con te compaiono nella barra laterale con 🔗.']} />
      </Card>
    </>
  )
}

/* ---- Modulo 7: sicurezza ---- */
function ModSecurity({ optional, passkeys }: { optional: boolean; passkeys: boolean }) {
  const [code, setCode] = useState('')
  const ok = code.replace(/\D/g, '').length === 6
  return (
    <>
      <Card title="Accesso" icon="🔑">
        <Steps items={[
          'Entri con email e password. ' + (optional ? 'Al primo accesso scegli se attivare un secondo fattore: puoi farlo anche dopo, da Impostazioni.' : 'Gli adulti devono attivare un secondo fattore al primo accesso.'),
          'App authenticator: inquadri un QR con Google Authenticator, Microsoft Authenticator, 1Password… e da allora, dopo la password, scrivi il codice a 6 cifre.' + (passkeys ? ' In alternativa una passkey (Face ID, Touch ID, chiave di sicurezza).' : ''),
          'Conserva i codici di recupero: servono se cambi telefono.',
          'In Impostazioni vedi le sessioni aperte sui vari dispositivi e puoi chiuderle; l\'amministratore può disattivare un account all\'istante.',
        ]} />
      </Card>
      <Card title="Prova: il codice a 6 cifre" icon="🎮">
        <div className="row" style={{ gap: 8 }}><input inputMode="numeric" placeholder="123456" value={code} onChange={(e) => setCode(e.target.value)} style={{ maxWidth: 160, letterSpacing: '.2em' }} /><button className="primary" disabled={!ok}>Verifica</button></div>
        <p className="muted small">{ok ? '✓ Così si entra. Il codice vero cambia ogni 30 secondi nell\'app.' : 'Scrivi sei cifre qualsiasi.'}</p>
      </Card>
    </>
  )
}
