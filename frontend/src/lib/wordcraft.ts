/** Collegamenti all'editor WordCraft nel browser (servito su /wordcraft/ quando il profilo e' attivo). */
export const WORDCRAFT_EXT = ['.docx', '.docm', '.dotx', '.doc', '.odt', '.rtf', '.txt', '.md', '.html', '.htm', '.tex']

export function editableInWordcraft(filename: string): boolean {
  const lower = (filename || '').toLowerCase()
  return WORDCRAFT_EXT.some((e) => lower.endsWith(e))
}

/** Id compatibile con quelli del server (32 hex): per i documenti nuovi lo sceglie il browser. */
export function newFileId(): string {
  const b = new Uint8Array(16)
  crypto.getRandomValues(b)
  return Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
}

/** Rotta interna dell'editor per un file esistente. */
export function editorPath(fileId: string): string {
  return `/editor?file=${encodeURIComponent(fileId)}`
}

/** Rotta interna dell'editor per un documento nuovo (collegato a una chat e/o a un progetto). */
export function newDocumentPath(opts: { conversationId?: string | null; projectId?: string | null; name?: string } = {}): string {
  const q = new URLSearchParams({ file: newFileId(), new: '1' })
  if (opts.conversationId) q.set('conversation_id', opts.conversationId)
  if (opts.projectId) q.set('project_id', opts.projectId)
  if (opts.name) q.set('name', opts.name)
  return `/editor?${q.toString()}`
}
