import * as React from "react"

import {
  CodeBlock,
  CodeBlockActions,
  CodeBlockContent,
  CodeBlockCopyButton,
  CodeBlockHeader,
  CodeBlockLine,
  CodeBlockTitle,
} from "@/components/ui/code-block"
import { useHighlightedCode } from "@/hooks/use-highlighted-code"
import { parseMarkdown, type Block, type Inline } from "@/lib/markdown"

type CiteRenderer = (nums: number[], key: string) => React.ReactNode

function renderInline(nodes: Inline[], cite: CiteRenderer | undefined, prefix: string): React.ReactNode[] {
  return nodes.map((n, i) => {
    const key = `${prefix}.${i}`
    switch (n.type) {
      case "text":
        return n.value
      case "code":
        return <code key={key}>{n.value}</code>
      case "strong":
        return <strong key={key}>{renderInline(n.children, cite, key)}</strong>
      case "em":
        return <em key={key}>{renderInline(n.children, cite, key)}</em>
      case "link":
        return (
          <a key={key} href={n.href} target="_blank" rel="noopener noreferrer">
            {renderInline(n.children, cite, key)}
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        )
      case "cite":
        return cite ? <React.Fragment key={key}>{cite(n.nums, key)}</React.Fragment> : n.raw
    }
  })
}

function lines(ls: Inline[][], cite: CiteRenderer | undefined, prefix: string) {
  return ls.map((l, i) => (
    <React.Fragment key={i}>
      {i > 0 && <br />}
      {renderInline(l, cite, `${prefix}.${i}`)}
    </React.Fragment>
  ))
}

export function HighlightedCode({
  code,
  lang,
  title,
  lineNumbers = false,
  startLine = 1,
  size = "default",
}: {
  code: string
  lang: string
  title?: string
  lineNumbers?: boolean
  startLine?: number
  size?: "default" | "sm"
}) {
  const highlighted = useHighlightedCode(code, lang || "text")
  return (
    <CodeBlock size={size} className="bg-muted/40 dark:bg-input/20">
      {title || lang ? (
        <CodeBlockHeader>
          <CodeBlockTitle className="font-mono text-xs text-muted-foreground">{title || lang}</CodeBlockTitle>
          <CodeBlockActions>
            <CodeBlockCopyButton value={code} />
          </CodeBlockActions>
        </CodeBlockHeader>
      ) : (
        <CodeBlockActions>
          <CodeBlockCopyButton value={code} />
        </CodeBlockActions>
      )}
      <CodeBlockContent lineNumbers={lineNumbers} startLine={startLine} className="max-h-[28rem] text-[0.8rem]">
        {highlighted.map((line, i) => (
          <CodeBlockLine key={i}>{line}</CodeBlockLine>
        ))}
      </CodeBlockContent>
    </CodeBlock>
  )
}

function renderBlocks(blocks: Block[], cite: CiteRenderer | undefined, prefix = "b"): React.ReactNode[] {
  return blocks.map((b, i) => {
    const key = `${prefix}${i}`
    switch (b.type) {
      case "paragraph":
        return <p key={key}>{lines(b.lines, cite, key)}</p>
      case "heading": {
        const Tag = `h${b.level}` as "h3"
        return <Tag key={key}>{renderInline(b.children, cite, key)}</Tag>
      }
      case "code":
        return (
          <div key={key} className="not-prose">
            <HighlightedCode code={b.value} lang={b.lang} />
          </div>
        )
      case "hr":
        return <hr key={key} />
      case "blockquote":
        return <blockquote key={key}>{renderBlocks(b.children, cite, `${key}q`)}</blockquote>
      case "table":
        return (
          <div key={key} className="overflow-x-auto">
            <table>
              <thead>
                <tr>
                  {b.head.map((c, j) => (
                    <th key={j}>{renderInline(c, cite, `${key}h${j}`)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows.map((r, j) => (
                  <tr key={j}>
                    {r.map((c, k) => (
                      <td key={k}>{renderInline(c, cite, `${key}r${j}c${k}`)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      case "list": {
        const items = b.items.map((it, j) => <li key={j}>{lines(it, cite, `${key}i${j}`)}</li>)
        return b.ordered ? (
          <ol key={key} start={b.start !== 1 ? b.start : undefined}>
            {items}
          </ol>
        ) : (
          <ul key={key}>{items}</ul>
        )
      }
    }
  })
}

/** Render answer Markdown as React elements (never as HTML), with citation pills. */
export function MarkdownView({
  text,
  cite,
  streaming = false,
  className,
}: {
  text: string
  cite?: CiteRenderer
  streaming?: boolean
  className?: string
}) {
  const blocks = React.useMemo(() => parseMarkdown(text, Boolean(cite)), [text, cite])
  return (
    <div className={className ?? "prose-answer"} data-streaming={streaming || undefined}>
      {renderBlocks(blocks, cite)}
    </div>
  )
}
