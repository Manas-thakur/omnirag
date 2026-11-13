import { describe, expect, it } from "vitest"

import { readEventStream } from "@/lib/api"
import { parseBlock, parseSse, SseParser } from "@/lib/sse"
import type { AnswerPayload, SourcesEvent } from "@/lib/types"

// The exact framing the server uses: omnirag.server.app._sse
const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`

describe("SseParser", () => {
  it("parses complete events", () => {
    const events = parseSse(sse("delta", { text: "Hello" }) + sse("delta", { text: " world" }))
    expect(events).toEqual([
      { event: "delta", data: '{"text":"Hello"}' },
      { event: "delta", data: '{"text":" world"}' },
    ])
  })

  it("buffers events split across chunks at any byte", () => {
    const body = sse("sources", { sources: [] }) + sse("delta", { text: "a\nb" }) + sse("done", { answer: "ok" })
    for (let cut = 1; cut < body.length; cut += 1) {
      const parser = new SseParser()
      const events = [...parser.push(body.slice(0, cut)), ...parser.push(body.slice(cut)), ...parser.end()]
      expect(events.map((e) => e.event)).toEqual(["sources", "delta", "done"])
      expect(JSON.parse(events[1].data)).toEqual({ text: "a\nb" })
    }
  })

  it("handles CRLF line endings, even when a CRLF pair is split", () => {
    const parser = new SseParser()
    const first = parser.push("event: delta\r\ndata: {\"text\":\"x\"}\r\n\r")
    const second = parser.push("\n")
    expect([...first, ...second]).toEqual([{ event: "delta", data: '{"text":"x"}' }])
  })

  it("joins multi-line data, ignores comments and defaults the event name", () => {
    expect(parseBlock(": keep-alive\ndata: one\ndata: two")).toEqual({ event: "message", data: "one\ntwo" })
    expect(parseBlock(": only a comment")).toBeNull()
  })

  it("flushes a final event without a trailing blank line", () => {
    const parser = new SseParser()
    expect(parser.push('event: done\ndata: {"answer":"x"}')).toEqual([])
    expect(parser.end()).toEqual([{ event: "done", data: '{"answer":"x"}' }])
  })
})

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c))
      controller.close()
    },
  })
}

describe("readEventStream", () => {
  it("dispatches sources, deltas and done in order", async () => {
    const source = {
      index: 1,
      chunk_id: "abc-0000",
      doc_id: "abc",
      source: "/docs/auth.md",
      title: "Auth",
      modality: "text",
      score: 0.9,
      content: "Tokens rotate.",
      metadata: {},
    }
    const body = sse("sources", { sources: [source], retrieve_ms: 3 }) + sse("delta", { text: "Tokens " }) + sse("delta", { text: "rotate [1]." }) + sse("done", { answer: "Tokens rotate [1].", cited: [1], sources: [source] })
    // Split mid-way through a multi-byte character and mid-event.
    const bytes = body.replace("rotate [1].", "rotate [1] ✓.")
    const calls: string[] = []
    let sources: SourcesEvent | null = null
    let done: AnswerPayload | null = null
    let text = ""
    await readEventStream(streamOf([bytes.slice(0, 37), bytes.slice(37, 120), bytes.slice(120)]), {
      onSources: (p) => {
        calls.push("sources")
        sources = p
      },
      onDelta: (t) => {
        calls.push("delta")
        text += t
      },
      onDone: (a) => {
        calls.push("done")
        done = a
      },
    })
    expect(calls).toEqual(["sources", "delta", "delta", "done"])
    expect(text).toBe("Tokens rotate [1] ✓.")
    expect(sources!.sources[0].doc_id).toBe("abc")
    expect(done!.cited).toEqual([1])
  })

  it("reports error events and skips malformed payloads", async () => {
    const errors: string[] = []
    const deltas: string[] = []
    await readEventStream(streamOf(["event: delta\ndata: {not json}\n\n", sse("error", { detail: "model went away" })]), {
      onDelta: (t) => deltas.push(t),
      onError: (d) => errors.push(d),
    })
    expect(deltas).toEqual([])
    expect(errors).toEqual(["model went away"])
  })
})
