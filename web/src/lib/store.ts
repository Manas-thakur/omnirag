import { toast } from "sonner"
import { create } from "zustand"

import { api, ApiError, onUnauthorized, streamAnswer, uploadFile } from "@/lib/api"
import { plural } from "@/lib/format"
import { citedNumbers } from "@/lib/markdown"
import { orderedSources } from "@/lib/sources"
import { KEYS, storage } from "@/lib/storage"
import type {
  AssistantMessage,
  Chat,
  DocumentInfo,
  Health,
  KBStats,
  KnowledgeBase,
  Modality,
  RelatedQuestion,
  ServerStatus,
  Source,
} from "@/lib/types"

export type View = "chat" | "library" | "settings"
export const VIEWS: Record<View, string> = { chat: "Chat", library: "Library", settings: "Settings" }
export type Theme = "system" | "light" | "dark"
export type AnswerTab = "answer" | "sources" | "media"

export type Panel =
  | null
  | { mode: "scope" }
  | { mode: "preview"; chatId: string; index: number; n: number }
  | { mode: "doc"; docId: string }

export interface UploadItem {
  id: string
  name: string
  size: number
  state: "waiting" | "uploading" | "indexing" | "done" | "error"
  progress: number
  message: string
}

interface ConfirmRequest {
  title: string
  body: string
  ok: string
  resolve: (ok: boolean) => void
}

export interface AppState {
  defaultKb: string
  version: string
  health: Health | null
  booted: boolean
  kbs: KnowledgeBase[] | null
  kb: string | null
  stats: KBStats | null
  docs: DocumentInfo[] | null
  docsKb: string | null
  docsError: string | null
  status: ServerStatus | null
  statusError: string | null
  statusLoading: boolean
  view: View
  theme: Theme
  chats: Chat[]
  chatId: string | null
  filters: Modality[]
  scope: string[]
  streaming: boolean
  panel: Panel
  starters: { key: string; items: RelatedQuestion[] } | null
  palette: { open: boolean; mode: "all" | "kb" }
  shortcutsOpen: boolean
  kbDialogOpen: boolean
  keyDialog: { open: boolean; invalid: boolean }
  confirm: ConfirmRequest | null
  uploads: UploadItem[]
}

const MAX_CHATS = 40

function meta(name: string): string {
  const value = document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)?.content ?? ""
  // In `vite dev` the server does not fill the placeholders in.
  return value.startsWith("__") ? "" : value
}

function viewFromHash(): View {
  const v = location.hash.replace(/^#\/?/, "")
  return v in VIEWS ? (v as View) : "chat"
}

export const useApp = create<AppState>(() => ({
  defaultKb: meta("omnirag-default-kb") || "default",
  version: meta("omnirag-version"),
  health: null,
  booted: false,
  kbs: null,
  kb: null,
  stats: null,
  docs: null,
  docsKb: null,
  docsError: null,
  status: null,
  statusError: null,
  statusLoading: false,
  view: viewFromHash(),
  theme: storage.get<Theme>(KEYS.theme, "system"),
  chats: storage.get<Chat[]>(KEYS.chats, []),
  chatId: null,
  filters: [],
  scope: [],
  streaming: false,
  panel: null,
  starters: null,
  palette: { open: false, mode: "all" },
  shortcutsOpen: false,
  kbDialogOpen: false,
  keyDialog: { open: false, invalid: false },
  confirm: null,
  uploads: [],
}))

const get = useApp.getState
const set = useApp.setState

const errorText = (err: unknown) => (err instanceof Error ? err.message : String(err))

// ------------------------------------------------------------------ selectors
export const currentChat = (s: AppState = get()) => s.chats.find((c) => c.id === s.chatId) ?? null
export const kbChats = (s: AppState) =>
  s.chats.filter((c) => c.kb === s.kb).sort((a, b) => b.updated - a.updated)
export const kbDocs = (s: AppState) => (s.docs && s.docsKb === s.kb ? s.docs : null)
export const scopedDocs = (s: AppState) => (kbDocs(s) ?? []).filter((d) => s.scope.includes(d.doc_id))

// ------------------------------------------------------------------ dialogs
export function confirmAction(opts: { title: string; body: string; ok?: string }): Promise<boolean> {
  return new Promise((resolve) => {
    get().confirm?.resolve(false)
    set({ confirm: { title: opts.title, body: opts.body, ok: opts.ok ?? "Delete", resolve } })
  })
}

export function resolveConfirm(ok: boolean) {
  const c = get().confirm
  set({ confirm: null })
  c?.resolve(ok)
}

let keyWaiters: (() => void)[] = []
export function requestApiKey(invalid = false): Promise<void> {
  return new Promise((resolve) => {
    keyWaiters.push(resolve)
    set({ keyDialog: { open: true, invalid } })
  })
}

export function apiKeyAccepted(key: string) {
  storage.set(KEYS.apiKey, key)
  set({ keyDialog: { open: false, invalid: false } })
  const waiters = keyWaiters
  keyWaiters = []
  for (const w of waiters) w()
}

export function forgetApiKey() {
  storage.remove(KEYS.apiKey)
  void requestApiKey()
}

onUnauthorized(() => requestApiKey(Boolean(storage.get(KEYS.apiKey, ""))))

// ------------------------------------------------------------------- theme
export function setTheme(theme: Theme) {
  storage.set(KEYS.theme, theme)
  set({ theme })
}

export function cycleTheme() {
  const order: Theme[] = ["system", "light", "dark"]
  const next = order[(order.indexOf(get().theme) + 1) % order.length]
  setTheme(next)
  toast(`Theme: ${next}`)
}

// ------------------------------------------------------------------- routing
export function navigate(view: View) {
  if (location.hash !== `#/${view}`) location.hash = `#/${view}`
  else set({ view })
}

export function syncViewFromHash() {
  const view = viewFromHash()
  const { panel } = get()
  set({
    view,
    // Answer previews and the source picker belong to the chat.
    panel: view !== "chat" && panel && panel.mode !== "doc" ? null : panel,
  })
  if (view === "library") void loadDocs()
}

export function focusComposer() {
  if (get().view !== "chat") navigate("chat")
  setTimeout(() => document.getElementById("question")?.focus(), 0)
}

// ------------------------------------------------------------------- chats
function saveChats(chats = get().chats) {
  let list = [...chats].sort((a, b) => b.updated - a.updated).slice(0, MAX_CHATS)
  while (!storage.set(KEYS.chats, list) && list.length > 1) list = list.slice(0, -1)
  return list
}

function setChats(chats: Chat[], persist = true) {
  set({ chats: persist ? saveChats(chats) : chats })
}

function patchMessage(chatId: string, index: number, patch: Partial<AssistantMessage>, persist = false) {
  const chats = get().chats.map((c) => {
    if (c.id !== chatId) return c
    const messages = c.messages.slice()
    messages[index] = { ...(messages[index] as AssistantMessage), ...patch }
    return { ...c, messages }
  })
  setChats(chats, persist)
}

export function newChat() {
  stopStreaming()
  const { panel } = get()
  set({ chatId: null, panel: panel?.mode === "preview" ? null : panel })
  focusComposer()
}

export function openChat(id: string) {
  stopStreaming()
  const { panel } = get()
  set({ chatId: id, panel: panel?.mode === "preview" ? null : panel })
  navigate("chat")
}

export function deleteChat(id: string) {
  const chat = get().chats.find((c) => c.id === id)
  if (!chat) return
  if (get().chatId === id) newChat()
  setChats(get().chats.filter((c) => c.id !== id))
  toast("Conversation deleted", {
    action: { label: "Undo", onClick: () => setChats([...get().chats, chat]) },
  })
}

export function setTab(index: number, tab: AnswerTab) {
  const chat = currentChat()
  if (chat) patchMessage(chat.id, index, { tab }, true)
}

// ------------------------------------------------------------------- scope
function loadScope(kb: string | null): string[] {
  return kb ? storage.get<string[]>(KEYS.scope(kb), []) : []
}

export function setScope(ids: Iterable<string>, quiet = false) {
  const { kb } = get()
  const scope = [...new Set(ids)]
  if (kb) storage.set(KEYS.scope(kb), scope)
  set({ scope })
  if (!quiet) announce(scope.length ? `Scoped to ${plural(scope.length, "source")}` : "Using all sources")
}

export function toggleScope(id: string, on?: boolean) {
  const scope = new Set(get().scope)
  const enable = on ?? !scope.has(id)
  if (enable) scope.add(id)
  else scope.delete(id)
  setScope(scope, true)
}

export function clearScope() {
  setScope([])
}

/** Drop ids of documents that no longer exist. */
function pruneScope() {
  const docs = kbDocs(get())
  if (!docs) return
  const ids = new Set(docs.map((d) => d.doc_id))
  const scope = get().scope
  if (scope.some((id) => !ids.has(id))) setScope(scope.filter((id) => ids.has(id)), true)
}

export function toggleFilter(m: Modality | null) {
  if (!m) return set({ filters: [] })
  const filters = get().filters
  set({ filters: filters.includes(m) ? filters.filter((x) => x !== m) : [...filters, m] })
}

// ------------------------------------------------------------- announcements
export function announce(text: string) {
  const el = document.getElementById("announcer")
  if (!el) return
  el.textContent = ""
  requestAnimationFrame(() => (el.textContent = text))
}

// ----------------------------------------------------------- knowledge bases
export async function boot() {
  try {
    set({ health: await api.health() })
  } catch {
    set({ health: null })
  }
  const health = get().health
  if (health) {
    set({ version: get().version || health.version, defaultKb: health.default_kb || get().defaultKb })
    if (health.auth_required && !storage.get(KEYS.apiKey, "")) await requestApiKey()
  }
  await loadKbs()
  set({ booted: true })
  await refreshKb()
}

export async function loadKbs() {
  let kbs: KnowledgeBase[] = []
  try {
    kbs = await api.kbs()
  } catch (err) {
    toast.error(`Could not load knowledge bases: ${errorText(err)}`)
  }
  const names = kbs.map((k) => k.name)
  const { kb, defaultKb } = get()
  if (!kb || !names.includes(kb)) {
    const remembered = storage.get<string | null>(KEYS.kb, null)
    const next =
      remembered && names.includes(remembered)
        ? remembered
        : names.includes(defaultKb)
          ? defaultKb
          : (names[0] ?? null)
    set({ kbs, kb: next, scope: loadScope(next) })
  } else set({ kbs })
}

export async function switchKb(name: string | null) {
  if (name === get().kb && get().stats) return
  stopStreaming()
  if (name) storage.set(KEYS.kb, name)
  set({
    kb: name,
    stats: null,
    docs: null,
    docsKb: null,
    starters: null,
    scope: loadScope(name),
    chatId: null,
    panel: null,
  })
  await refreshKb()
}

export async function refreshKb() {
  const name = get().kb
  if (!name) {
    set({ stats: null })
    void loadStatus()
    return
  }
  try {
    const stats = await api.stats(name)
    if (name === get().kb) set({ stats })
  } catch (err) {
    if (name === get().kb) set({ stats: null })
    toast.error(errorText(err))
  }
  void loadDocs()
  void loadStatus()
}

export async function createKb(name: string, description: string) {
  await api.createKb(name, description)
  await loadKbs()
  await switchKb(name)
  navigate("library")
  toast.success(`Created ${name}`, { description: "Add some files to get started." })
}

export async function deleteKb(name: string) {
  const kb = get().kbs?.find((k) => k.name === name)
  const ok = await confirmAction({
    title: `Delete “${name}”?`,
    body: `This permanently removes the index${kb ? ` (${plural(kb.documents, "document")}, ${plural(kb.chunks, "chunk")})` : ""}, uploaded files and settings. Files ingested from server paths are not touched. This cannot be undone.`,
    ok: "Delete knowledge base",
  })
  if (!ok) return
  try {
    await api.deleteKb(name)
    setChats(get().chats.filter((c) => c.kb !== name))
    storage.remove(KEYS.scope(name))
    if (get().kb === name) set({ kb: null })
    await loadKbs()
    await switchKb(get().kb)
    toast.success(`Deleted ${name}`)
  } catch (err) {
    toast.error(errorText(err))
  }
}

// -------------------------------------------------------------------- status
export async function loadStatus() {
  const name = get().kb
  set({ statusLoading: true })
  try {
    const status = await api.status(name)
    if (name !== get().kb) return
    set({ status, statusError: null })
  } catch (err) {
    set({ statusError: errorText(err) })
  } finally {
    set({ statusLoading: false })
  }
}

// ----------------------------------------------------------------- documents
export async function loadDocs() {
  const name = get().kb
  if (!name) return
  if (get().docsKb !== name) set({ docs: null })
  try {
    const docs = await api.documents(name)
    if (name !== get().kb) return
    set({ docs, docsKb: name, docsError: null })
    pruneScope()
  } catch (err) {
    set({ docsError: errorText(err) })
  }
}

async function afterLibraryChange() {
  set({ starters: null })
  await loadKbs()
  const name = get().kb
  if (!name) return
  try {
    set({ stats: await api.stats(name) })
  } catch {
    /* keep the old stats */
  }
}

export async function deleteDoc(docId: string) {
  const { kb } = get()
  const d = get().docs?.find((x) => x.doc_id === docId)
  if (!d || !kb) return
  const ok = await confirmAction({
    title: `Delete ${d.name}?`,
    body: `Its ${plural(d.chunks, "chunk")} are removed from ${kb}. ${d.uploaded ? "The uploaded copy is deleted too." : "The source file on disk is not touched."}`,
    ok: "Delete document",
  })
  if (!ok) return
  try {
    await api.deleteDocument(kb, docId)
    const panel = get().panel
    set({
      docs: (get().docs ?? []).filter((x) => x.doc_id !== docId),
      panel: panel?.mode === "doc" && panel.docId === docId ? null : panel,
    })
    if (get().scope.includes(docId)) toggleScope(docId, false)
    toast.success(`Deleted ${d.name}`)
    void afterLibraryChange()
  } catch (err) {
    toast.error(errorText(err))
  }
}

export async function reingestDoc(docId: string) {
  const { kb } = get()
  const d = get().docs?.find((x) => x.doc_id === docId)
  if (!kb) return
  try {
    const r = await api.reingest(kb, docId)
    const failed = Object.values(r.report.failed)[0]
    if (failed) toast.error(`Re-ingest failed: ${failed}`)
    else toast.success(`Re-ingested ${d?.name ?? "document"}`, { description: plural(r.document.chunks, "chunk") })
    await loadDocs()
    void afterLibraryChange()
  } catch (err) {
    toast.error(errorText(err))
  }
}

function patchUpload(id: string, patch: Partial<UploadItem>) {
  set({ uploads: get().uploads.map((u) => (u.id === id ? { ...u, ...patch } : u)) })
}

export function clearFinishedUploads() {
  set({ uploads: get().uploads.filter((u) => u.state !== "done" && u.state !== "error") })
}

export async function uploadFiles(fileList: FileList | File[]) {
  const kb = get().kb
  const files = [...fileList]
  if (!kb || !files.length) return
  const status = get().status
  const allowed = new Set(status?.upload_extensions ?? [])
  const maxMb = status?.max_upload_mb ?? 50
  const jobs: [File, string][] = []
  const items: UploadItem[] = files.map((file) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`
    const ext = file.name.includes(".") ? `.${file.name.split(".").pop()!.toLowerCase()}` : ""
    const item: UploadItem = { id, name: file.name, size: file.size, state: "waiting", progress: 0, message: "Waiting" }
    if (allowed.size && !allowed.has(ext)) {
      Object.assign(item, { state: "error", message: `Unsupported type${ext ? ` (${ext})` : ""}` })
    } else if (file.size > maxMb * 1024 * 1024) {
      Object.assign(item, { state: "error", message: `Larger than ${maxMb} MB` })
    } else jobs.push([file, id])
    return item
  })
  set({ uploads: [...items.reverse(), ...get().uploads] })
  let changed = 0
  for (const [file, id] of jobs) {
    patchUpload(id, { state: "uploading", message: "Uploading…" })
    try {
      const result = await uploadFile(kb, file, (p) =>
        patchUpload(id, p >= 1 ? { progress: 1, state: "indexing", message: "Indexing…" } : { progress: p, message: `${Math.round(p * 100)}%` }),
      )
      const f = result.files?.[0]
      if (!f || f.status === "failed") {
        patchUpload(id, { state: "error", progress: 1, message: `Could not ingest: ${f?.error ?? "unknown error"}` })
      } else {
        changed += 1
        patchUpload(id, {
          state: "done",
          progress: 1,
          message:
            f.status === "unchanged"
              ? "Unchanged · already indexed"
              : `${f.status === "updated" ? "Updated" : "Added"} · ${plural(f.chunks, "chunk")}`,
        })
      }
    } catch (err) {
      patchUpload(id, { state: "error", message: errorText(err) })
    }
  }
  if (changed) {
    toast.success(`${plural(changed, "file")} indexed into ${kb}`)
    await loadDocs()
    void afterLibraryChange()
  }
}

// ------------------------------------------------------------------- panels
export function openPanel(panel: Exclude<Panel, null>) {
  set({ panel })
  if (panel.mode === "scope") void loadDocs()
}

export function closePanel() {
  set({ panel: null })
}

export function toggleScopePanel() {
  if (!get().kb) return
  if (get().panel?.mode === "scope") closePanel()
  else {
    if (get().view !== "chat") navigate("chat")
    openPanel({ mode: "scope" })
  }
}

export function openSource(index: number, n: number) {
  const chat = currentChat()
  if (!chat) return
  openPanel({ mode: "preview", chatId: chat.id, index, n })
}

export function askAboutDoc(docId: string) {
  setScope([docId])
  set({ panel: null, chatId: currentChat()?.messages.length ? null : get().chatId })
  focusComposer()
}

export function askSelected() {
  if (currentChat()?.messages.length) set({ chatId: null })
  focusComposer()
}

// ------------------------------------------------------------------ starters
export const startersKey = (s: AppState) => `${s.kb}|${[...s.scope].sort().join(",")}`

export async function loadStarters() {
  const s = get()
  const name = s.kb
  if (!name || s.starters?.key === startersKey(s)) return
  const key = startersKey(s)
  const scopeIds = [...s.scope]
  let items: RelatedQuestion[]
  try {
    items = (await api.related(name, { limit: 4, doc_ids: scopeIds.length ? scopeIds : null })).questions
  } catch {
    items = []
  }
  if (startersKey(get()) === key) set({ starters: { key, items } })
}

// ------------------------------------------------------------------- asking
let controller: AbortController | null = null

export function stopStreaming() {
  controller?.abort()
}

/** How many chunks the next question searches: the scope, or the whole knowledge base. */
function searchableChunks(): number | null {
  const s = get()
  if (s.scope.length) return scopedDocs(s).reduce((n, d) => n + (d.chunks || 0), 0) || null
  return s.stats?.chunks ?? null
}

function newId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Date.now())
}

export async function ask(question: string) {
  const s = get()
  question = question.trim()
  if (!s.kb || controller || !question) return
  let chat = currentChat()
  if (!chat) {
    chat = {
      id: newId(),
      kb: s.kb,
      title: question.length > 60 ? `${question.slice(0, 57)}…` : question,
      created: Date.now(),
      updated: Date.now(),
      messages: [],
    }
    set({ chatId: chat.id })
  }
  if (s.view !== "chat") navigate("chat")
  const scopeIds = [...s.scope]
  const scope = scopeIds.length ? { ids: scopeIds, names: scopedDocs(s).map((d) => d.name) } : null
  const msg: AssistantMessage = {
    role: "assistant",
    text: "",
    pending: true,
    phase: "search",
    searched: searchableChunks(),
    scope,
    tab: "answer",
  }
  const updated: Chat = {
    ...chat,
    updated: Date.now(),
    messages: [...chat.messages, { role: "user", text: question }, msg],
  }
  const chatId = updated.id
  const index = updated.messages.length - 1
  setChats([...get().chats.filter((c) => c.id !== chatId), updated])

  const ctrl = new AbortController()
  controller = ctrl
  set({ streaming: true })
  let text = ""
  let error: string | undefined
  let stopped = false
  // Deltas arrive fast; batch them into one store update per frame.
  let frame = 0
  const flushText = () => {
    frame = 0
    patchMessage(chatId, index, { text, phase: "write" })
  }
  try {
    await streamAnswer(
      {
        query: question,
        kb: updated.kb,
        modalities: s.filters.length ? s.filters : null,
        doc_ids: scopeIds.length ? scopeIds : null,
      },
      {
        onSources: (p) => patchMessage(chatId, index, { sources: p.sources.map(slimSource), phase: "read" }),
        onDelta: (piece) => {
          text += piece
          if (!frame) frame = requestAnimationFrame(flushText)
        },
        onDone: (a) => {
          if (frame) cancelAnimationFrame(frame)
          frame = 0
          text = a.answer
          patchMessage(chatId, index, {
            text: a.answer,
            cited: a.cited,
            backend: a.backend,
            timings: a.timings,
            warnings: a.warnings,
            sources: a.sources.map(slimSource),
            phase: "done",
          })
        },
        onError: (detail) => {
          error = detail
        },
      },
      ctrl.signal,
    )
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") stopped = true
    else error = err instanceof ApiError || err instanceof Error ? err.message : "The request failed."
  } finally {
    if (frame) cancelAnimationFrame(frame)
    controller = null
    const current = get().chats.find((c) => c.id === chatId)?.messages[index] as AssistantMessage | undefined
    const finalText = current?.phase === "done" ? current.text : text
    const patch: Partial<AssistantMessage> = { pending: false, phase: "done", text: finalText, error, stopped }
    if (!finalText && !error && !stopped) patch.error = "No answer was returned."
    if (!current?.cited && finalText) {
      // Interrupted answers: mark whatever was cited so far.
      const known = new Set((current?.sources ?? []).map((x) => x.index))
      patch.cited = citedNumbers(finalText).filter((n) => known.has(n))
    }
    patchMessage(chatId, index, patch, true)
    set({
      streaming: false,
      chats: saveChats(get().chats.map((c) => (c.id === chatId ? { ...c, updated: Date.now() } : c))),
    })
    if (finalText && !patch.error) {
      const cited = (get().chats.find((c) => c.id === chatId)?.messages[index] as AssistantMessage).cited ?? []
      announce(`Answer ready, ${plural(cited.length, "citation")}.`)
      void loadRelated(chatId, index)
    }
  }
}

function slimSource(s: Source): Source {
  return {
    index: s.index,
    chunk_id: s.chunk_id,
    doc_id: s.doc_id,
    source: s.source,
    title: s.title,
    modality: s.modality,
    score: s.score,
    content: s.content,
    location: s.location,
    label: s.label,
    metadata: s.metadata,
    retrieval: s.retrieval,
  }
}

async function loadRelated(chatId: string, index: number) {
  const chat = get().chats.find((c) => c.id === chatId)
  const msg = chat?.messages[index] as AssistantMessage | undefined
  if (!chat || !msg?.sources?.length) return
  const { cited, rest } = orderedSources(msg)
  const asked = new Set(chat.messages.filter((m) => m.role === "user").map((m) => m.text.toLowerCase()))
  try {
    const r = await api.related(chat.kb, {
      query: chat.messages[index - 1]?.text ?? "",
      chunk_ids: [...cited, ...rest].map((x) => x.chunk_id),
      doc_ids: msg.scope?.ids?.length ? msg.scope.ids : null,
      limit: 4,
    })
    patchMessage(chatId, index, { related: r.questions.filter((q) => !asked.has(q.question.toLowerCase())) }, true)
  } catch {
    /* related questions are optional */
  }
}

// ---------------------------------------------------------------- raw files
const rawCache = new Map<string, Promise<string>>()

/** Object URL for a document's original file (fetched once, with the API key). */
export function rawUrl(kb: string, docId: string): Promise<string> {
  const key = `${kb}/${docId}`
  let p = rawCache.get(key)
  if (!p) {
    p = api.raw(kb, docId).then((blob) => URL.createObjectURL(blob))
    p.catch(() => rawCache.delete(key))
    rawCache.set(key, p)
  }
  return p
}

export async function openRaw(kb: string, docId: string) {
  // Open the tab synchronously so popup blockers allow it, then point it at the file.
  const win = window.open("", "_blank")
  try {
    const url = await rawUrl(kb, docId)
    if (win) win.location.href = url
    else window.open(url, "_blank", "noopener")
  } catch (err) {
    win?.close()
    toast.error(`Could not open the file: ${errorText(err)}`)
  }
}
