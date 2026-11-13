import { describe, expect, it } from "vitest"

import { citedNumbers, parseInline, parseMarkdown } from "@/lib/markdown"

describe("parseInline", () => {
  it("groups adjacent and comma-separated citations into one node", () => {
    expect(parseInline("Tokens rotate [1][2] and expire [3, 4].")).toEqual([
      { type: "text", value: "Tokens rotate " },
      { type: "cite", raw: "[1][2]", nums: [1, 2] },
      { type: "text", value: " and expire " },
      { type: "cite", raw: "[3, 4]", nums: [3, 4] },
      { type: "text", value: "." },
    ])
  })

  it("leaves citations as text when citations are off", () => {
    expect(parseInline("see [1]", false)).toEqual([{ type: "text", value: "see [1]" }])
  })

  it("keeps code spans literal, including double-backtick spans", () => {
    expect(parseInline("call `refresh([1])` with ``rate`` tokens")).toEqual([
      { type: "text", value: "call " },
      { type: "code", value: "refresh([1])" },
      { type: "text", value: " with " },
      { type: "code", value: "rate" },
      { type: "text", value: " tokens" },
    ])
  })

  it("parses emphasis with nested citations", () => {
    expect(parseInline("**Decision [2]** and *maybe*")).toEqual([
      { type: "strong", children: [{ type: "text", value: "Decision " }, { type: "cite", raw: "[2]", nums: [2] }] },
      { type: "text", value: " and " },
      { type: "em", children: [{ type: "text", value: "maybe" }] },
    ])
  })

  it("only links http(s) and mailto URLs", () => {
    expect(parseInline("[docs](https://example.com/a)")).toEqual([
      { type: "link", href: "https://example.com/a", children: [{ type: "text", value: "docs" }] },
    ])
    expect(parseInline("[x](javascript:alert(1))")).toEqual([{ type: "text", value: "[x](javascript:alert(1))" }])
  })

  it("never produces markup from raw HTML", () => {
    const nodes = parseInline('<img src=x onerror="alert(1)">')
    expect(nodes).toEqual([{ type: "text", value: '<img src=x onerror="alert(1)">' }])
  })
})

describe("parseMarkdown", () => {
  it("parses headings (shifted below the question heading), lists and paragraphs", () => {
    const blocks = parseMarkdown("# Title\n\n- one [1]\n- two\n\n3. three\n4. four\n\nPlain\ntext")
    expect(blocks.map((b) => b.type)).toEqual(["heading", "list", "list", "paragraph"])
    expect(blocks[0]).toMatchObject({ type: "heading", level: 3 })
    expect(blocks[2]).toMatchObject({ type: "list", ordered: true, start: 3 })
    expect(blocks[3]).toMatchObject({ type: "paragraph" })
    expect((blocks[3] as { lines: unknown[] }).lines).toHaveLength(2)
  })

  it("keeps an unterminated fence open while an answer streams", () => {
    const blocks = parseMarkdown("Code:\n```python\ndef f():\n    return [1]")
    expect(blocks[1]).toEqual({ type: "code", lang: "python", value: "def f():\n    return [1]", open: true })
    const closed = parseMarkdown("```\nx\n```")
    expect(closed[0]).toMatchObject({ type: "code", open: false, value: "x" })
  })

  it("parses tables and block quotes", () => {
    const blocks = parseMarkdown("| a | b |\n|---|---|\n| 1 | 2 [1] |\n\n> quoted")
    expect(blocks[0]).toMatchObject({ type: "table" })
    const table = blocks[0] as { head: unknown[]; rows: unknown[][] }
    expect(table.head).toHaveLength(2)
    expect(table.rows[0][1]).toEqual([{ type: "text", value: "2 " }, { type: "cite", raw: "[1]", nums: [1] }])
    expect(blocks[1]).toMatchObject({ type: "blockquote" })
  })
})

describe("citedNumbers", () => {
  it("lists every cited number once, in order of first use", () => {
    expect(citedNumbers("a [2] b [1][2] c [3, 1]")).toEqual([2, 1, 3])
  })
})
