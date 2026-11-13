// Shapes returned by the OmniRAG HTTP API (src/omnirag/server/app.py).

export type Modality = "text" | "code" | "table" | "image" | "audio"

export const MODALITIES: Modality[] = ["text", "code", "table", "image", "audio"]

export const MODALITY_LABEL: Record<Modality, string> = {
  text: "Text",
  code: "Code",
  table: "Tables",
  image: "Images",
  audio: "Audio",
}

export interface Health {
  status: string
  version: string
  default_kb: string
  llm: string
  auth_required: boolean
}

export interface KnowledgeBase {
  name: string
  description: string
  embedder: string
  documents: number
  chunks: number
  created_at: string
  is_default: boolean
}

export interface KBStats {
  name: string
  description: string
  embedder: string
  documents: number
  chunks: number
  by_modality: Record<string, number>
  documents_by_modality: Record<string, number>
  dimension: number | null
  storage_bytes: number
  avg_chunk_chars: number
  created_at: string
  last_updated: string | null
  path: string
}

export interface DocumentInfo {
  doc_id: string
  source: string
  path: string
  name: string
  title: string
  modality: Modality
  chunks: number
  size_bytes: number | null
  missing: boolean
  uploaded: boolean
  created_at: string
  updated_at: string
  warnings: string[]
}

export type SourceMetadata = Record<string, unknown> & {
  path?: string
  title?: string
  heading?: string
  section?: string
  symbol?: string
  kind?: string
  line_start?: number
  line_end?: number
  row_start?: number
  row_end?: number
  timestamp?: string
  page?: number
}

export interface Source {
  index: number
  chunk_id: string
  doc_id: string
  source: string
  title: string
  modality: Modality
  score: number
  content: string
  location?: string
  label?: string
  metadata: SourceMetadata
  retrieval?: { ranks?: Record<string, number> } & Record<string, unknown>
}

export interface Timings {
  retrieve_ms?: number
  generate_ms?: number
  first_token_ms?: number
  total_ms?: number
  [key: string]: number | undefined
}

export interface AnswerPayload {
  question: string
  answer: string
  backend: string
  cited: number[]
  sources: Source[]
  warnings: string[]
  timings: Timings
  query: Record<string, unknown>
}

export interface SourcesEvent {
  sources: Source[]
  query?: Record<string, unknown>
  retrieve_ms?: number
}

export interface RelatedQuestion {
  question: string
  doc_id: string
  chunk_id: string
  source: string
  modality: Modality
}

export interface ChunkPreview {
  chunk_id: string
  position: number
  content: string
  metadata: SourceMetadata
  doc_id: string
  source: string
  modality: Modality
  before: { chunk_id: string; position: number; content: string; metadata: SourceMetadata }[]
  after: { chunk_id: string; position: number; content: string; metadata: SourceMetadata }[]
}

export type LlmBackend = "none" | "ollama" | "openai"

export interface ServerStatus {
  version: string
  auth_required: boolean
  default_kb: string
  max_upload_mb: number
  upload_extensions: string[]
  kb: string | null
  embedder: { spec: string; dimension: number | null; offline: boolean } | null
  defaults: {
    llm: string
    ollama: { model: string; base_url: string }
    openai: { model: string; base_url: string }
  }
  llm: {
    backend: LlmBackend
    model: string
    base_url: string
    source: "kb" | "server"
    reachable: boolean | null
    detail: string
    latency_ms: number | null
    models: string[]
  }
}

export interface Preferences {
  llm: "" | LlmBackend
  model: string
  base_url: string
  top_k: number
}

export interface IngestReport {
  added: string[]
  updated: string[]
  unchanged: string[]
  failed: Record<string, string>
  warnings: Record<string, string[]>
  chunks: number
  seconds: number
  processed: number
}

export interface UploadResult {
  files: {
    name: string
    size_bytes: number
    status: "added" | "updated" | "unchanged" | "failed" | "skipped"
    error: string | null
    doc_id: string | null
    chunks: number
    warnings: string[]
  }[]
  report: IngestReport
}

export interface QueryRequest {
  query: string
  kb?: string
  top_k?: number | null
  llm?: string | null
  modalities?: Modality[] | null
  sources?: string[] | null
  doc_ids?: string[] | null
  mode?: "hybrid" | "dense" | "bm25"
  neighbors?: number
}

/** One assistant turn as kept in the browser (local chat history). */
export interface AssistantMessage {
  role: "assistant"
  text: string
  pending?: boolean
  phase?: "search" | "read" | "write" | "done"
  searched?: number | null
  sources?: Source[]
  cited?: number[]
  backend?: string
  timings?: Timings
  warnings?: string[]
  error?: string
  stopped?: boolean
  related?: RelatedQuestion[]
  scope?: { ids: string[]; names: string[] } | null
  tab?: "answer" | "sources" | "media"
}

export interface UserMessage {
  role: "user"
  text: string
}

export type ChatMessage = UserMessage | AssistantMessage

export interface Chat {
  id: string
  kb: string
  title: string
  created: number
  updated: number
  messages: ChatMessage[]
}
