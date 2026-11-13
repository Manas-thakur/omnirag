import { describe, expect, it } from "vitest"

import { citationLabeler, copyText, excerptOf, highlightRuns, orderedSources, questionWords, shortLoc, shortName } from "@/lib/sources"
import type { Source } from "@/lib/types"

const src = (index: number, path: string, extra: Partial<Source> = {}): Source => ({
  index,
  chunk_id: `doc${index}-0000`,
  doc_id: `doc${index}`,
  source: `/data/${path}`,
  title: path,
  modality: "text",
  score: 1,
  content: "Some content",
  metadata: { path },
  ...extra,
})

describe("source labels", () => {
  it("names a source by its file and locates it by section, lines, rows or timestamp", () => {
    expect(shortName(src(1, "docs/auth.md"))).toBe("auth.md")
    expect(shortLoc(src(1, "a.md", { metadata: { section: "Refreshing tokens", title: "Auth" } }))).toBe("Refreshing tokens")
    expect(shortLoc(src(1, "a.py", { modality: "code", metadata: { line_start: 9, line_end: 42, symbol: "TokenBucket" } }))).toBe(
      "TokenBucket · L9–42",
    )
    expect(shortLoc(src(1, "a.csv", { modality: "table", metadata: { row_start: 1, row_end: 20 } }))).toBe("Rows 1–20")
    expect(shortLoc(src(1, "m.vtt", { modality: "audio", metadata: { timestamp: "00:05-01:26" } }))).toBe("00:05–01:26")
  })

  it("strips the heading breadcrumb and code fences from excerpts", () => {
    const s = src(1, "a.md", { content: "Auth > Tokens\n\n```py\nx = 1\n```", metadata: { heading: "Auth > Tokens" } })
    expect(excerptOf(s)).toBe("x = 1")
    expect(excerptOf(src(1, "a.md", { content: "word ".repeat(100) }), 20)).toHaveLength(20)
  })
})

describe("orderedSources", () => {
  it("puts cited sources first, in citation order", () => {
    const sources = [src(1, "a.md"), src(2, "b.md"), src(3, "c.md")]
    const { cited, rest } = orderedSources({ sources, cited: [3, 1] })
    expect(cited.map((s) => s.index)).toEqual([3, 1])
    expect(rest.map((s) => s.index)).toEqual([2])
  })

  it("treats everything as uncited while streaming", () => {
    const sources = [src(1, "a.md")]
    expect(orderedSources({ sources, cited: [1], pending: true })).toEqual({ cited: [], rest: sources })
  })
})

describe("citationLabeler", () => {
  it("labels pills by section when every cited source is the same file", () => {
    const a = src(1, "auth.md", { metadata: { path: "auth.md", section: "Login" } })
    const b = src(2, "auth.md", { metadata: { path: "auth.md", section: "Refresh" } })
    const label = citationLabeler({ sources: [a, b], cited: [1, 2], text: "" })
    expect([label(a), label(b)]).toEqual(["Login", "Refresh"])
  })

  it("labels pills by file name when several files are cited", () => {
    const a = src(1, "auth.md", { metadata: { path: "auth.md", section: "Login" } })
    const b = src(2, "rate.md", { metadata: { path: "rate.md", section: "Limits" } })
    const label = citationLabeler({ sources: [a, b], cited: [1, 2], text: "" })
    expect([label(a), label(b)]).toEqual(["auth.md", "rate.md"])
  })
})

describe("copyText", () => {
  it("appends the cited sources to the answer", () => {
    const a = src(1, "docs/auth.md", { metadata: { path: "docs/auth.md", section: "Login" } })
    expect(copyText({ text: "Answer [1].", sources: [a, src(2, "b.md")], cited: [1] })).toBe(
      "Answer [1].\n\nSources:\n[1] docs/auth.md — Login",
    )
  })
})

describe("highlighting", () => {
  it("drops stop words and stems the rest", () => {
    expect(questionWords("How are refresh tokens rotated?")).toEqual(["refre", "toke", "rotat"])
  })

  it("splits text into highlighted runs", () => {
    expect(highlightRuns("Tokens rotate on refresh", ["toke", "refre"])).toEqual([
      { text: "Tokens", hit: true },
      { text: " rotate on ", hit: false },
      { text: "refresh", hit: true },
    ])
  })
})
