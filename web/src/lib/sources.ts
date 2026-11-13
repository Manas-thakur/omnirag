import type { AssistantMessage, Source } from "@/lib/types"

export function baseName(path: string | undefined | null): string {
  const p = String(path ?? "")
  return p.split(/[\\/]/).filter(Boolean).pop() ?? p
}

/** Short display name for a source: its file name. */
export function shortName(s: Pick<Source, "metadata" | "source" | "title" | "index">): string {
  return baseName(s.metadata?.path || s.source) || s.title || `Source ${s.index}`
}

/** Short, human location inside the source: section, lines, rows, timestamp. */
export function shortLoc(s: Pick<Source, "metadata" | "modality" | "location">): string {
  const m = s.metadata ?? {}
  if (s.modality === "code" && m.line_start)
    return `${m.symbol ? `${m.symbol} · ` : ""}L${m.line_start}–${m.line_end ?? m.line_start}`
  if (s.modality === "code" && m.symbol) return String(m.symbol)
  if (s.modality === "text" && m.section) return m.section === m.title ? "Introduction" : String(m.section)
  if (s.modality === "text" && m.page) return `Page ${m.page}`
  if (s.modality === "table" && m.row_start) return `Rows ${m.row_start}–${m.row_end ?? m.row_start}`
  if (s.modality === "table") return "Columns & summary"
  if (s.modality === "audio" && m.timestamp) return String(m.timestamp).replace("-", "–")
  if (s.modality === "image") return "Image"
  return s.location ?? ""
}

/** Chunk text without the heading breadcrumb that chunking prepends, collapsed to one line. */
export function excerptOf(s: Pick<Source, "content" | "metadata">, max = 260): string {
  let text = String(s.content ?? "")
  const crumb = s.metadata?.heading
  if (crumb && text.startsWith(crumb)) text = text.slice(crumb.length)
  text = text
    .replace(/```[\w+#.-]*\n?/g, "")
    .replace(/\s+/g, " ")
    .trim()
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text
}

/** Sources ordered cited-first (in citation order), then the rest. */
export function orderedSources(msg: Pick<AssistantMessage, "sources" | "cited" | "pending">): {
  cited: Source[]
  rest: Source[]
} {
  const sources = msg.sources ?? []
  if (msg.pending) return { cited: [], rest: sources }
  if (!msg.cited?.length) return { cited: [], rest: sources }
  const cited = msg.cited
    .map((n) => sources.find((s) => s.index === n))
    .filter((s): s is Source => Boolean(s))
  return { cited, rest: sources.filter((s) => !msg.cited!.includes(s.index)) }
}

/**
 * Label for a citation pill. Usually the file name; when every cited source
 * comes from one file, a row of identical file names says nothing, so pills
 * are labelled by section / lines / rows instead.
 */
export function citationLabeler(msg: Pick<AssistantMessage, "sources" | "cited" | "text">) {
  const nums = msg.cited?.length
    ? msg.cited
    : [...(msg.text ?? "").matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1]))
  const files = new Set(
    nums
      .map((n) => msg.sources?.find((s) => s.index === n))
      .filter((s): s is Source => Boolean(s))
      .map(shortName),
  )
  const singleFile = files.size === 1
  return (s: Source) => {
    const loc = shortLoc(s)
    // "Image" says nothing about which image, so images keep their file name.
    return singleFile && loc && s.modality !== "image" ? loc : shortName(s)
  }
}

/** The answer text followed by a list of the sources it cites. */
export function copyText(msg: Pick<AssistantMessage, "text" | "sources" | "cited">): string {
  const cited = new Set(msg.cited ?? [])
  const refs = (msg.sources ?? [])
    .filter((s) => cited.has(s.index))
    .map((s) => {
      const loc = shortLoc(s)
      return `[${s.index}] ${s.metadata?.path || s.source}${loc ? ` — ${loc}` : ""}`
    })
  return refs.length ? `${msg.text}\n\nSources:\n${refs.join("\n")}` : msg.text
}

const STOP = new Set(
  "what when where which while with would about does have from that this there their them they into your how why who the and for are was were will been being can could should tell show".split(
    " ",
  ),
)

/** Stems of the question's content words, used to highlight matches in excerpts. */
export function questionWords(question: string): string[] {
  const words = question.toLowerCase().match(/[a-z0-9]{4,}/g) ?? []
  return [...new Set(words)].filter((w) => !STOP.has(w)).map((w) => w.slice(0, Math.max(4, w.length - 2)))
}

/** Split text into plain and highlighted runs for the given word stems. */
export function highlightRuns(text: string, words: string[]): { text: string; hit: boolean }[] {
  if (!words.length || !text) return [{ text, hit: false }]
  const escaped = words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
  const re = new RegExp(`\\b(?:${escaped.join("|")})\\w*`, "gi")
  const runs: { text: string; hit: boolean }[] = []
  let last = 0
  for (const m of text.matchAll(re)) {
    const at = m.index ?? 0
    if (at > last) runs.push({ text: text.slice(last, at), hit: false })
    runs.push({ text: m[0], hit: true })
    last = at + m[0].length
  }
  if (last < text.length) runs.push({ text: text.slice(last), hit: false })
  return runs
}
