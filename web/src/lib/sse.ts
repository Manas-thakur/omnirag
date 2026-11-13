/**
 * Incremental parser for `text/event-stream` bodies.
 *
 * The server (`POST /api/query/stream`) sends blocks like
 *
 *     event: delta
 *     data: {"text": "..."}
 *
 * separated by a blank line. Network chunks can split a block, a line or a
 * CRLF pair anywhere, so the parser buffers until a block is complete.
 * Comment lines (`:`) and unknown fields are ignored; multi-line `data:`
 * fields are joined with "\n" as the spec requires.
 */
export interface SseEvent {
  event: string
  data: string
}

export class SseParser {
  private buffer = ""

  /** Feed a decoded chunk; returns every event completed by it. */
  push(chunk: string): SseEvent[] {
    this.buffer += chunk
    // Normalise line endings, but keep a trailing "\r" until we know whether
    // it starts a CRLF pair that continues in the next chunk.
    const keepCr = this.buffer.endsWith("\r")
    const body = keepCr ? this.buffer.slice(0, -1) : this.buffer
    let text = body.replace(/\r\n?/g, "\n")
    const events: SseEvent[] = []
    let cut: number
    while ((cut = text.indexOf("\n\n")) >= 0) {
      const event = parseBlock(text.slice(0, cut))
      text = text.slice(cut + 2)
      if (event) events.push(event)
    }
    this.buffer = keepCr ? `${text}\r` : text
    return events
  }

  /** Flush a final block that was not followed by a blank line. */
  end(): SseEvent[] {
    const rest = this.buffer.replace(/\r\n?/g, "\n")
    this.buffer = ""
    const event = rest.trim() ? parseBlock(rest) : null
    return event ? [event] : []
  }
}

export function parseBlock(block: string): SseEvent | null {
  let event = "message"
  const data: string[] = []
  let sawData = false
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue
    const colon = line.indexOf(":")
    const field = colon < 0 ? line : line.slice(0, colon)
    let value = colon < 0 ? "" : line.slice(colon + 1)
    if (value.startsWith(" ")) value = value.slice(1)
    if (field === "event") event = value || "message"
    else if (field === "data") {
      data.push(value)
      sawData = true
    }
  }
  return sawData ? { event, data: data.join("\n") } : null
}

/** Parse a whole SSE body at once. */
export function parseSse(text: string): SseEvent[] {
  const parser = new SseParser()
  return [...parser.push(text), ...parser.end()]
}
