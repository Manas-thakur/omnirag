/**
 * A small Markdown parser for answers, producing a tree that React renders.
 *
 * Safety: the output is data, never HTML. React escapes every text node, raw
 * HTML in the source stays literal text, and links are only produced for
 * http(s) and mailto URLs. Supported: paragraphs, headings, fenced code
 * (including a fence still open while an answer streams), inline code, bold,
 * italic, links, block quotes, ordered/unordered lists, simple tables,
 * horizontal rules and `[n]` citation groups (`[1][2]` and `[1, 2]` become one
 * group so the UI can show a single pill per group).
 */

export type Inline =
  | { type: "text"; value: string }
  | { type: "code"; value: string }
  | { type: "strong"; children: Inline[] }
  | { type: "em"; children: Inline[] }
  | { type: "link"; href: string; children: Inline[] }
  | { type: "cite"; nums: number[]; raw: string }

export type Block =
  | { type: "paragraph"; lines: Inline[][] }
  | { type: "heading"; level: 3 | 4 | 5 | 6; children: Inline[] }
  | { type: "code"; lang: string; value: string; open: boolean }
  | { type: "hr" }
  | { type: "blockquote"; children: Block[] }
  | { type: "table"; head: Inline[][]; rows: Inline[][][] }
  | { type: "list"; ordered: boolean; start: number; items: Inline[][][] }

export function safeUrl(raw: string): string | null {
  const url = raw.trim()
  return /^(https?:\/\/|mailto:)/i.test(url) ? url : null
}

interface Rule {
  re: RegExp
  build: (m: RegExpExecArray, cite: boolean) => Inline | null
}

const RULES: Rule[] = [
  // ``double`` (reStructuredText docstrings) and `single` backtick code spans.
  { re: /``(?!`)([^\n]+?)``|`([^`\n]+)`/g, build: (m) => ({ type: "code", value: (m[1] ?? m[2]).trim() }) },
  {
    re: /\[([^\]\n]+)\]\(([^)\s]+)\)/g,
    build: (m) => {
      const href = safeUrl(m[2])
      return href ? { type: "link", href, children: parseInline(m[1], false) } : null
    },
  },
  {
    re: /(?:\[\d{1,3}(?:\s*,\s*\d{1,3})*\])+/g,
    build: (m, cite) =>
      cite ? { type: "cite", raw: m[0], nums: [...m[0].matchAll(/\d{1,3}/g)].map((n) => Number(n[0])) } : null,
  },
  {
    re: /\*\*(?=\S)([^*]+?)\*\*|__(?=\S)([^_]+?)__/g,
    build: (m, cite) => ({ type: "strong", children: parseInline(m[1] ?? m[2], cite) }),
  },
  {
    re: /(?<![\w*])\*(?=\S)([^*\n]+?)\*(?![\w*])|(?<!\w)_(?=\S)([^_\n]+?)_(?!\w)/g,
    build: (m, cite) => ({ type: "em", children: parseInline(m[1] ?? m[2], cite) }),
  },
]

/** Parse one line of inline Markdown. `cite` turns `[n]` groups into citation nodes. */
export function parseInline(text: string, cite = true): Inline[] {
  const out: Inline[] = []
  let pos = 0
  let plain = ""
  const flush = () => {
    if (plain) out.push({ type: "text", value: plain })
    plain = ""
  }
  while (pos < text.length) {
    let best: { index: number; length: number; node: Inline } | null = null
    for (const rule of RULES) {
      rule.re.lastIndex = pos
      let m: RegExpExecArray | null
      // A match the rule rejects (an unsafe link) is skipped, not fatal.
      while ((m = rule.re.exec(text))) {
        if (best && m.index >= best.index) break
        const node = rule.build(m, cite)
        if (node) {
          best = { index: m.index, length: m[0].length, node }
          break
        }
        rule.re.lastIndex = m.index + 1
      }
    }
    if (!best) {
      plain += text.slice(pos)
      break
    }
    plain += text.slice(pos, best.index)
    flush()
    out.push(best.node)
    pos = best.index + best.length
  }
  flush()
  return out
}

const isTableSep = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line)
const splitRow = (line: string) =>
  line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim())
const LIST_ITEM = /^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$/

/** Parse Markdown into blocks. */
export function parseMarkdown(text: string, cite = true): Block[] {
  const lines = String(text ?? "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
  const out: Block[] = []
  let para: string[] = []
  let i = 0
  const flush = () => {
    if (para.length) out.push({ type: "paragraph", lines: para.map((l) => parseInline(l, cite)) })
    para = []
  }

  while (i < lines.length) {
    const line = lines[i]

    const fence = line.match(/^\s*(```|~~~)\s*([\w+#.-]*)\s*$/)
    if (fence) {
      flush()
      const body: string[] = []
      i += 1
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i++])
      const open = i >= lines.length
      i += 1
      out.push({ type: "code", lang: fence[2] || "", value: body.join("\n"), open })
      continue
    }

    if (!line.trim()) {
      flush()
      i += 1
      continue
    }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/)
    if (heading) {
      flush()
      // Answers sit under the question heading, so they never need h1/h2.
      const level = Math.min(6, heading[1].length + 2) as 3 | 4 | 5 | 6
      out.push({ type: "heading", level, children: parseInline(heading[2], cite) })
      i += 1
      continue
    }

    if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) {
      flush()
      out.push({ type: "hr" })
      i += 1
      continue
    }

    if (/^\s*>/.test(line)) {
      flush()
      const body: string[] = []
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""))
      out.push({ type: "blockquote", children: parseMarkdown(body.join("\n"), cite) })
      continue
    }

    if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      flush()
      const head = splitRow(line).map((c) => parseInline(c, cite))
      i += 2
      const rows: Inline[][][] = []
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        rows.push(splitRow(lines[i++]).map((c) => parseInline(c, cite)))
      }
      out.push({ type: "table", head, rows })
      continue
    }

    const item = line.match(LIST_ITEM)
    if (item) {
      flush()
      const ordered = /\d/.test(item[2])
      const start = ordered ? parseInt(item[2], 10) : 1
      const items: string[][] = []
      while (i < lines.length) {
        const m = lines[i].match(LIST_ITEM)
        if (m && /\d/.test(m[2]) === ordered) {
          items.push([m[3]])
          i += 1
        } else if (lines[i].trim() && /^\s{2,}\S/.test(lines[i]) && items.length) {
          items[items.length - 1].push(lines[i].trim()) // continuation line
          i += 1
        } else break
      }
      out.push({
        type: "list",
        ordered,
        start,
        items: items.map((ls) => ls.map((l) => parseInline(l, cite))),
      })
      continue
    }

    para.push(line.trim())
    i += 1
  }
  flush()
  return out
}

/** Every citation number used in a text, in order of first use. */
export function citedNumbers(text: string): number[] {
  const seen = new Set<number>()
  for (const group of text.matchAll(/(?:\[\d{1,3}(?:\s*,\s*\d{1,3})*\])+/g)) {
    for (const n of group[0].matchAll(/\d{1,3}/g)) seen.add(Number(n[0]))
  }
  return [...seen]
}
