import { useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { get, patch } from '../lib/api'

export interface ArtifactData {
  id: string
  title: string
  kind: 'html' | 'svg' | 'markdown' | 'code' | 'mermaid'
  language: string
  version: number
  content: string
  conversation_id: string
}

const CAN_PREVIEW = new Set(['html', 'svg', 'markdown', 'mermaid'])

/** HTML della pagina di anteprima: iframe sandbox senza same-origin, quindi senza cookie né accesso alle API. */
function previewDoc(a: ArtifactData): string {
  if (a.kind === 'html') return a.content
  if (a.kind === 'svg') return `<!doctype html><html><body style="margin:0;display:grid;place-items:center;min-height:100vh;background:#fff">${a.content}</body></html>`
  if (a.kind === 'mermaid')
    return `<!doctype html><html><body style="margin:16px;background:#fff"><pre class="mermaid">${a.content.replace(/</g, '&lt;')}</pre>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/11.4.1/mermaid.min.js"></script><script>mermaid.initialize({startOnLoad:true});</script></body></html>`
  return ''
}

export default function ArtifactPanel({ artifact, canEdit, onClose, onChange }: {
  artifact: ArtifactData; canEdit: boolean; onClose: () => void; onChange: (a: ArtifactData) => void
}) {
  const [tab, setTab] = useState<'preview' | 'code'>(CAN_PREVIEW.has(artifact.kind) ? 'preview' : 'code')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(artifact.content)
  const [versions, setVersions] = useState<number[]>([])
  const [shown, setShown] = useState<ArtifactData>(artifact)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    setShown(artifact)
    setDraft(artifact.content)
    setEditing(false)
    if (!CAN_PREVIEW.has(artifact.kind)) setTab('code')
    get(`/artifacts/${artifact.id}`).then((a) => setVersions([...(a.history || []).map((h: any) => h.version), a.version]))
  }, [artifact.id, artifact.version])

  const doc = useMemo(() => previewDoc(shown), [shown, reloadKey])

  async function save() {
    const a = await patch<ArtifactData>(`/artifacts/${artifact.id}`, { content: draft })
    onChange(a)
    setEditing(false)
  }
  async function showVersion(v: number) {
    setShown(await get(`/artifacts/${artifact.id}/versions/${v}`))
  }
  function download() {
    const ext = { html: 'html', svg: 'svg', markdown: 'md', mermaid: 'mmd' }[shown.kind as string] ??
      ({ python: 'py', javascript: 'js', typescript: 'ts', java: 'java', bash: 'sh' } as any)[shown.language] ?? 'txt'
    const blob = new Blob([shown.content], { type: 'text/plain' })
    const u = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = u
    a.download = `${shown.title.replace(/[^\w.-]+/g, '_')}.${ext}`
    a.click()
    URL.revokeObjectURL(u)
  }

  return (
    <aside className="artifact-panel">
      <header className="artifact-header">
        <div className="title" title={shown.title}>📦 {shown.title}</div>
        <div className="row">
          {versions.length > 1 && (
            <select value={shown.version} onChange={(e) => showVersion(Number(e.target.value))} title="Versione">
              {versions.map((v) => <option key={v} value={v}>v{v}</option>)}
            </select>
          )}
          {CAN_PREVIEW.has(shown.kind) && (
            <div className="tabs small">
              <button className={tab === 'preview' ? 'active' : ''} onClick={() => setTab('preview')}>Anteprima</button>
              <button className={tab === 'code' ? 'active' : ''} onClick={() => setTab('code')}>Codice</button>
            </div>
          )}
          {tab === 'preview' && <button className="icon" title="Ricarica" onClick={() => setReloadKey((k) => k + 1)}>↻</button>}
          <button className="icon" title="Copia" onClick={() => navigator.clipboard.writeText(shown.content)}>📋</button>
          <button className="icon" title="Scarica" onClick={download}>⬇️</button>
          {shown.kind === 'html' && <a className="icon" title="Apri in nuova scheda" href={`/api/artifacts/${shown.id}/raw`} target="_blank" rel="noreferrer">↗</a>}
          <button className="icon" onClick={onClose} title="Chiudi">✕</button>
        </div>
      </header>

      <div className="artifact-body">
        {tab === 'preview' && shown.kind === 'markdown' && (
          <div className="markdown pad"><ReactMarkdown remarkPlugins={[remarkGfm]}>{shown.content}</ReactMarkdown></div>
        )}
        {tab === 'preview' && shown.kind !== 'markdown' && (
          <iframe
            key={`${shown.id}-${shown.version}-${reloadKey}`}
            className="artifact-frame"
            sandbox="allow-scripts allow-modals allow-forms allow-popups allow-pointer-lock"
            referrerPolicy="no-referrer"
            srcDoc={doc}
            title={shown.title}
          />
        )}
        {tab === 'code' && (
          editing ? (
            <textarea className="code-editor" value={draft} onChange={(e) => setDraft(e.target.value)} spellCheck={false} />
          ) : (
            <pre className="code-view"><code>{shown.content}</code></pre>
          )
        )}
      </div>

      {tab === 'code' && canEdit && shown.version === artifact.version && (
        <footer className="artifact-footer row">
          {editing ? (
            <>
              <button onClick={save}>Salva come nuova versione</button>
              <button className="ghost" onClick={() => { setEditing(false); setDraft(artifact.content) }}>Annulla</button>
            </>
          ) : (
            <button className="ghost" onClick={() => setEditing(true)}>✏️ Modifica</button>
          )}
          <small className="muted">{shown.kind}{shown.language ? ` · ${shown.language}` : ''} · v{shown.version}</small>
        </footer>
      )}
    </aside>
  )
}
