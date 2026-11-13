import { KEYS, storage } from "@/lib/storage"
import { SseParser, type SseEvent } from "@/lib/sse"
import type {
  AnswerPayload,
  ChunkPreview,
  DocumentInfo,
  Health,
  IngestReport,
  KBStats,
  KnowledgeBase,
  Preferences,
  QueryRequest,
  RelatedQuestion,
  ServerStatus,
  SourcesEvent,
  UploadResult,
} from "@/lib/types"

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

/** FastAPI error bodies carry `detail` as a string or a list of validation errors. */
export function detailText(detail: unknown): string {
  if (!detail) return ""
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) =>
        d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : JSON.stringify(d),
      )
      .join("; ")
  }
  return JSON.stringify(detail)
}

export function authHeaders(): Record<string, string> {
  const key = storage.get(KEYS.apiKey, "")
  return key ? { "X-API-Key": key } : {}
}

/**
 * Called when the server answers 401. It should obtain a key (the app shows a
 * dialog) and resolve once one is stored; the request is then retried once.
 */
let unauthorizedHandler: (() => Promise<void>) | null = null
export function onUnauthorized(handler: (() => Promise<void>) | null) {
  unauthorizedHandler = handler
}

interface RequestOptions {
  method?: string
  body?: unknown
  signal?: AbortSignal
}

async function send(path: string, options: RequestOptions, retried = false): Promise<Response> {
  const headers: Record<string, string> = { ...authHeaders() }
  let payload: BodyInit | undefined
  if (options.body instanceof FormData) payload = options.body
  else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json"
    payload = JSON.stringify(options.body)
  }
  const res = await fetch(path, {
    method: options.method ?? "GET",
    headers,
    body: payload,
    signal: options.signal,
  })
  if (res.status === 401 && !retried && unauthorizedHandler) {
    await unauthorizedHandler()
    return send(path, options, true)
  }
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { detail?: unknown }
    throw new ApiError(detailText(data.detail) || `${res.status} ${res.statusText}`, res.status)
  }
  return res
}

async function json<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const res = await send(path, options)
  return (await res.json()) as T
}

const kbPath = (name: string) => `/api/kbs/${encodeURIComponent(name)}`

export const api = {
  health: () => json<Health>("/api/health"),
  status: (kb: string | null, probe = true) => {
    const params = new URLSearchParams()
    if (kb) params.set("kb", kb)
    if (!probe) params.set("probe", "false")
    const q = params.toString()
    return json<ServerStatus>(`/api/status${q ? `?${q}` : ""}`)
  },
  kbs: () => json<KnowledgeBase[]>("/api/kbs"),
  createKb: (name: string, description: string) =>
    json<KnowledgeBase>("/api/kbs", { method: "POST", body: { name, description } }),
  deleteKb: (name: string) => json<{ deleted: string }>(kbPath(name), { method: "DELETE" }),
  stats: (kb: string) => json<KBStats>(`${kbPath(kb)}/stats`),
  documents: (kb: string) => json<DocumentInfo[]>(`${kbPath(kb)}/documents`),
  deleteDocument: (kb: string, docId: string) =>
    json<{ deleted: string; removed_file: boolean }>(
      `${kbPath(kb)}/documents/${encodeURIComponent(docId)}`,
      { method: "DELETE" },
    ),
  reingest: (kb: string, docId: string) =>
    json<{ document: DocumentInfo; report: IngestReport }>(
      `${kbPath(kb)}/documents/${encodeURIComponent(docId)}/reingest`,
      { method: "POST" },
    ),
  settings: (kb: string) => json<Preferences>(`${kbPath(kb)}/settings`),
  saveSettings: (kb: string, prefs: Preferences) =>
    json<Preferences>(`${kbPath(kb)}/settings`, { method: "PUT", body: prefs }),
  related: (
    kb: string,
    body: { query?: string; chunk_ids?: string[]; doc_ids?: string[] | null; limit?: number },
  ) => json<{ questions: RelatedQuestion[] }>(`${kbPath(kb)}/related`, { method: "POST", body }),
  chunk: (kb: string, chunkId: string, window = 1) =>
    json<ChunkPreview>(`${kbPath(kb)}/chunks/${encodeURIComponent(chunkId)}?window=${window}`),
  /** The original file of a document as a blob (fetched with the API key). */
  raw: async (kb: string, docId: string) => {
    const res = await send(`${kbPath(kb)}/documents/${encodeURIComponent(docId)}/raw`, {})
    return res.blob()
  },
  query: (body: QueryRequest, signal?: AbortSignal) =>
    json<AnswerPayload>("/api/query", { method: "POST", body, signal }),
}

export interface StreamHandlers {
  onSources?: (payload: SourcesEvent) => void
  onDelta?: (text: string) => void
  onDone?: (answer: AnswerPayload) => void
  onError?: (detail: string) => void
}

/** Route parsed SSE events to typed handlers; malformed payloads are skipped. */
export function dispatchEvents(events: SseEvent[], handlers: StreamHandlers): void {
  for (const { event, data } of events) {
    let payload: unknown
    try {
      payload = JSON.parse(data)
    } catch {
      continue
    }
    if (event === "sources") handlers.onSources?.(payload as SourcesEvent)
    else if (event === "delta") handlers.onDelta?.(String((payload as { text?: unknown }).text ?? ""))
    else if (event === "done") handlers.onDone?.(payload as AnswerPayload)
    else if (event === "error")
      handlers.onError?.(detailText((payload as { detail?: unknown }).detail) || "The answer failed.")
  }
}

/** Read an SSE response body to the end, dispatching events as they complete. */
export async function readEventStream(
  body: ReadableStream<Uint8Array>,
  handlers: StreamHandlers,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  const parser = new SseParser()
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    dispatchEvents(parser.push(decoder.decode(value, { stream: true })), handlers)
  }
  dispatchEvents(parser.push(decoder.decode()), handlers)
  dispatchEvents(parser.end(), handlers)
}

/**
 * `POST /api/query/stream`. Resolves when the stream ends; rejects on network
 * and HTTP errors and when aborted (an `AbortError`).
 */
export async function streamAnswer(
  body: QueryRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await send("/api/query/stream", { method: "POST", body, signal })
  if (!res.body) throw new ApiError("The server sent an empty response.", res.status)
  await readEventStream(res.body, handlers)
}

/** Upload one file with progress (fetch has no upload progress events, XHR does). */
export function uploadFile(
  kb: string,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<UploadResult> {
  const attempt = (retried: boolean): Promise<UploadResult> =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      const form = new FormData()
      form.append("files", file, file.name)
      xhr.open("POST", `${kbPath(kb)}/upload`)
      for (const [k, v] of Object.entries(authHeaders())) xhr.setRequestHeader(k, v)
      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable) onProgress(e.loaded / e.total)
      })
      xhr.addEventListener("load", () => {
        let data: { detail?: unknown } & Partial<UploadResult> = {}
        try {
          data = JSON.parse(xhr.responseText || "{}")
        } catch {
          /* non-JSON error body */
        }
        if (xhr.status === 401 && !retried && unauthorizedHandler) {
          unauthorizedHandler().then(() => attempt(true).then(resolve, reject), reject)
          return
        }
        if (xhr.status >= 400) {
          reject(new ApiError(detailText(data.detail) || `Upload failed (${xhr.status})`, xhr.status))
          return
        }
        resolve(data as UploadResult)
      })
      xhr.addEventListener("error", () => reject(new ApiError("Network error", 0)))
      xhr.send(form)
    })
  return attempt(false)
}

/** Check a key without storing it (used by the API-key dialog). */
export async function verifyKey(key: string): Promise<"ok" | "rejected" | "unreachable"> {
  try {
    const res = await fetch("/api/kbs", { headers: { "X-API-Key": key } })
    return res.status === 401 ? "rejected" : "ok"
  } catch {
    return "unreachable"
  }
}
