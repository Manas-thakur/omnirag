import * as React from "react"
import {
  CheckIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  CopyIcon,
  CornerDownRightIcon,
  GaugeIcon,
  LayersIcon,
  SearchIcon,
  BookOpenIcon,
  PenLineIcon,
  SquareIcon,
  SparklesIcon,
} from "lucide-react"
import { toast } from "sonner"

import { InlineCitation, SourceNumber } from "@/components/app/citation"
import { ModalityIcon } from "@/components/app/icons"
import { MarkdownView } from "@/components/app/markdown-view"
import { Thumb } from "@/components/app/thumb"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@/components/ui/trace"
import { formatMs, plural } from "@/lib/format"
import { citationLabeler, copyText, excerptOf, orderedSources, questionWords, shortLoc, shortName } from "@/lib/sources"
import { ask, navigate, openSource, setTab, useApp, type AnswerTab } from "@/lib/store"
import type { AssistantMessage, Source } from "@/lib/types"
import { cn } from "@/lib/utils"

/** The context budget of the answer generator (AnswerGenerator max_context_tokens). */
const CONTEXT_BUDGET = 3000

export function Turn({
  kb,
  chatId,
  index,
  question,
  msg,
}: {
  kb: string
  chatId: string
  index: number
  question: string
  msg: AssistantMessage
}) {
  const images = (msg.sources ?? []).filter((s) => s.modality === "image")
  const n = msg.sources?.length ?? 0
  const tab: AnswerTab = msg.tab === "media" && !images.length ? "answer" : (msg.tab ?? "answer")
  return (
    <article className="flex flex-col gap-4" aria-labelledby={`q-${chatId}-${index}`}>
      <h2 id={`q-${chatId}-${index}`} className="text-xl font-semibold tracking-tight text-balance sm:text-2xl">
        {question}
      </h2>
      <Tabs value={tab} onValueChange={(v) => setTab(index, v as AnswerTab)} className="gap-4">
        <TabsList variant="line" className="w-full justify-start border-b pb-0" aria-label="Answer views">
          <TabsTrigger value="answer" className="flex-none px-2 pb-2">
            <SparklesIcon />
            Answer
          </TabsTrigger>
          <TabsTrigger value="sources" className="flex-none px-2 pb-2">
            <LayersIcon />
            Sources
            {n > 0 && <span className="text-xs text-muted-foreground tabular-nums">{n}</span>}
          </TabsTrigger>
          {images.length > 0 && (
            <TabsTrigger value="media" className="flex-none px-2 pb-2">
              <ModalityIcon modality="image" className="text-current" />
              Media
              <span className="text-xs text-muted-foreground tabular-nums">{images.length}</span>
            </TabsTrigger>
          )}
        </TabsList>
        <RunStatus msg={msg} />
        <TabsContent value="answer" className="flex flex-col gap-5">
          <AnswerPanel kb={kb} chatId={chatId} index={index} question={question} msg={msg} />
        </TabsContent>
        <TabsContent value="sources">
          <SourcesPanel index={index} msg={msg} />
        </TabsContent>
        {images.length > 0 && (
          <TabsContent value="media">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {images.map((s) => (
                <button
                  key={s.index}
                  type="button"
                  onClick={() => openSource(index, s.index)}
                  className="group flex flex-col gap-2 rounded-xl border bg-card p-2 text-left transition-colors outline-none hover:bg-muted/50 focus-visible:ring-3 focus-visible:ring-ring/50"
                >
                  <Thumb kb={kb} docId={s.doc_id} alt={shortName(s)} className="aspect-[4/3] w-full rounded-lg bg-muted/60" />
                  <span className="flex min-w-0 items-center gap-1.5 px-0.5 text-xs">
                    <SourceNumber n={s.index} />
                    <span className="truncate">{shortName(s)}</span>
                  </span>
                </button>
              ))}
            </div>
          </TabsContent>
        )}
      </Tabs>
    </article>
  )
}

const STEPS = [
  { key: "search", icon: SearchIcon, label: (m: AssistantMessage) => `Searching ${m.searched ? plural(m.searched, "chunk") : "the knowledge base"}` },
  { key: "read", icon: BookOpenIcon, label: (m: AssistantMessage) => `Reading ${m.sources ? plural(m.sources.length, "source") : "sources"}` },
  { key: "write", icon: PenLineIcon, label: () => "Writing the answer" },
] as const

/** Chain of Thought: live steps while streaming, a one-line summary afterwards. */
function RunStatus({ msg }: { msg: AssistantMessage }) {
  if (msg.pending) {
    const at = STEPS.findIndex((s) => s.key === (msg.phase ?? "search"))
    return (
      <Trace aria-label="Progress" aria-live="polite" className="gap-1.5">
        {STEPS.map((step, i) => {
          if (i > at + 1) return null
          const Icon = i < at ? CircleCheckIcon : step.icon
          return (
            <TraceLine key={step.key} status={i === at ? "running" : i > at ? "pending" : undefined} aria-current={i === at ? "step" : undefined}>
              <TraceIcon>
                <Icon className={cn(i < at && "text-success")} />
              </TraceIcon>
              <TraceTitle>{step.label(msg)}</TraceTitle>
            </TraceLine>
          )
        })}
      </Trace>
    )
  }
  const t = msg.timings ?? {}
  const count = msg.cited?.length || msg.sources?.length || 0
  let head: string
  let Icon = CircleCheckIcon
  if (msg.error && !msg.text) {
    head = "Could not answer"
    Icon = CircleAlertIcon
  } else if (msg.stopped) {
    head = `Stopped${count ? ` · ${plural(count, "source")} retrieved` : ""}`
    Icon = SquareIcon
  } else head = `Answered from ${plural(count, "source")}`
  const rows = [
    { icon: SearchIcon, text: `Searched ${msg.searched ? plural(msg.searched, "chunk") : "the knowledge base"}`, ms: t.retrieve_ms },
    msg.sources && {
      icon: BookOpenIcon,
      text: `Read ${plural(msg.sources.length, "source")}${msg.cited?.length ? `, cited ${msg.cited.length}` : ""}`,
    },
    msg.text && {
      icon: PenLineIcon,
      text: `Wrote the answer${msg.backend ? ` with ${msg.backend === "extractive" ? "the offline extractive answerer" : msg.backend}` : ""}`,
      ms: t.generate_ms,
    },
    msg.scope?.names?.length && { icon: LayersIcon, text: `Scope: ${msg.scope.names.join(", ")}` },
  ].filter(Boolean) as { icon: typeof SearchIcon; text: string; ms?: number }[]
  return (
    <Trace>
      <TraceCollapsible>
        <TraceCollapsibleTrigger>
          <TraceLine status={msg.error && !msg.text ? "error" : undefined}>
            <TraceIcon>
              <Icon className={cn(!msg.error && !msg.stopped && "text-success")} />
            </TraceIcon>
            <TraceTitle>{head}</TraceTitle>
            {t.total_ms ? <TraceDescription>{formatMs(t.total_ms)}</TraceDescription> : null}
            {msg.scope?.ids?.length ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-brand-soft px-1.5 text-xs text-foreground">
                <LayersIcon className="size-3 text-brand" />
                scoped to {plural(msg.scope.ids.length, "source")}
              </span>
            ) : null}
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <Trace className="gap-1.5">
            {rows.map((r, i) => (
              <TraceLine key={i}>
                <TraceIcon>
                  <r.icon />
                </TraceIcon>
                <TraceTitle className="whitespace-normal">{r.text}</TraceTitle>
                {r.ms != null && <TraceDescription>{Math.round(r.ms)} ms</TraceDescription>}
              </TraceLine>
            ))}
          </Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  )
}

function AnswerPanel({
  kb,
  chatId,
  index,
  question,
  msg,
}: {
  kb: string
  chatId: string
  index: number
  question: string
  msg: AssistantMessage
}) {
  const panel = useApp((s) => s.panel)
  const activeN = panel?.mode === "preview" && panel.chatId === chatId && panel.index === index ? panel.n : null
  const streaming = Boolean(msg.pending && !msg.error)
  const words = React.useMemo(() => questionWords(question), [question])
  const sources = React.useMemo(() => msg.sources ?? [], [msg.sources])
  const label = React.useMemo(() => citationLabeler(msg), [msg])
  const cite = React.useCallback(
    (nums: number[], key: string) => (
      <InlineCitation
        key={key}
        nums={nums}
        sources={sources}
        label={label}
        words={words}
        active={activeN !== null && nums.includes(activeN)}
        onOpen={(n) => openSource(index, n)}
      />
    ),
    [sources, label, words, activeN, index],
  )
  const offline = msg.backend === "extractive" && Boolean(msg.text)
  return (
    <>
      <SourceStrip kb={kb} index={index} msg={msg} activeN={activeN} />
      {msg.text ? (
        <MarkdownView text={msg.text} cite={cite} streaming={streaming} />
      ) : streaming ? (
        <div className="flex flex-col gap-2.5" aria-hidden="true">
          <Skeleton className="h-4 w-[92%]" />
          <Skeleton className="h-4 w-[84%]" />
          <Skeleton className="h-4 w-[60%]" />
        </div>
      ) : null}
      {msg.error && (
        <Alert variant="destructive">
          <CircleAlertIcon />
          <AlertDescription>{msg.error}</AlertDescription>
        </Alert>
      )}
      {msg.stopped && <p className="text-sm text-muted-foreground">Stopped. The answer above is incomplete.</p>}
      {msg.warnings?.map((w) => (
        <p key={w} className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          {w}
        </p>
      ))}
      {!msg.pending && (msg.text || msg.error) && (
        <div className="flex flex-wrap items-center gap-1.5 text-sm">
          {msg.text && <CopyAnswerButton msg={msg} />}
          {msg.text && sources.length > 0 && <ContextMeter sources={sources} cited={msg.cited?.length ?? 0} />}
          {offline && (
            <Button
              variant="link"
              size="xs"
              className="h-auto px-1 text-xs font-normal text-muted-foreground"
              onClick={() => navigate("settings")}
              title="Answers are quoted from your sources. Connect Ollama or an OpenAI-compatible model for written answers."
            >
              Quoted from sources · connect a model for written answers
            </Button>
          )}
        </div>
      )}
      {msg.related && msg.related.length > 0 && (
        <section aria-label="Related questions" className="flex flex-col gap-1">
          <h3 className="flex items-center gap-1.5 text-sm font-medium">
            <CornerDownRightIcon className="size-4 text-muted-foreground" />
            Related
          </h3>
          <ul className="flex flex-col divide-y">
            {msg.related.map((r) => (
              <li key={r.question}>
                <Button
                  variant="ghost"
                  className="h-auto w-full justify-between gap-3 rounded-md px-2 py-2.5 text-left font-normal whitespace-normal text-foreground/90"
                  onClick={() => void ask(r.question)}
                >
                  <span>{r.question}</span>
                  <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
                    <ModalityIcon modality={r.modality} />
                    <span className="hidden max-w-[10rem] truncate sm:inline">{r.source}</span>
                  </span>
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}

function CopyAnswerButton({ msg }: { msg: AssistantMessage }) {
  const [copied, setCopied] = React.useState(false)
  React.useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 1600)
    return () => clearTimeout(t)
  }, [copied])
  return (
    <Button
      variant="ghost"
      size="xs"
      className="text-muted-foreground"
      onClick={() =>
        navigator.clipboard.writeText(copyText(msg)).then(
          () => setCopied(true),
          () => toast.error("Copy failed: clipboard access was blocked"),
        )
      }
    >
      {copied ? <CheckIcon /> : <CopyIcon />}
      {copied ? "Copied" : "Copy"}
    </Button>
  )
}

/** Context: how much source text went to the answerer, against its budget. */
function ContextMeter({ sources, cited }: { sources: Source[]; cited: number }) {
  // Same estimate as the server (about 4 characters per token, plus the "[n] (modality) path" header).
  const used = sources.reduce((t, s) => t + Math.max(1, Math.floor((s.content.length + s.source.length + 24) / 4)), 0)
  const percent = Math.min(100, Math.round((used / CONTEXT_BUDGET) * 100))
  return (
    <HoverCard openDelay={80} closeDelay={100}>
      <HoverCardTrigger asChild>
        <Button variant="ghost" size="xs" className="text-muted-foreground">
          <GaugeIcon />
          {percent}% context
        </Button>
      </HoverCardTrigger>
      <HoverCardContent className="flex w-72 flex-col gap-3" side="top" align="start">
        <div className="flex items-center justify-between gap-3 text-sm">
          <span className="font-medium">Context</span>
          <span className="text-muted-foreground tabular-nums">
            ≈{used.toLocaleString()} / {CONTEXT_BUDGET.toLocaleString()} tokens
          </span>
        </div>
        <Progress value={percent} aria-label="Context used" />
        <p className="text-xs leading-relaxed text-muted-foreground">
          {plural(sources.length, "source")} sent to the answerer, {cited} cited. Estimated at about four characters per
          token; neighbouring chunks may add more, up to the budget.
        </p>
      </HoverCardContent>
    </HoverCard>
  )
}

function SourceStrip({ kb, index, msg, activeN }: { kb: string; index: number; msg: AssistantMessage; activeN: number | null }) {
  if (!msg.sources?.length) return null
  const { cited, rest } = orderedSources(msg)
  const lead = msg.pending ? msg.sources : cited.length ? cited : rest
  const tail = msg.pending || !cited.length ? [] : rest
  const shown = lead.slice(0, 8)
  const more = lead.length - shown.length + tail.length
  return (
    <div role="list" aria-label="Sources" className="no-scrollbar -mx-1 flex scroll-fade-x gap-2 overflow-x-auto overscroll-x-contain px-1 py-0.5">
      {shown.map((s) => (
        <div role="listitem" key={s.index} className="shrink-0">
          <SourceCard kb={kb} s={s} cited={!msg.pending && cited.includes(s)} active={activeN === s.index} onClick={() => openSource(index, s.index)} />
        </div>
      ))}
      {more > 0 && (
        <div role="listitem" className="shrink-0">
          <button
            type="button"
            onClick={() => setTab(index, "sources")}
            className="flex h-full w-32 flex-col justify-center gap-0.5 rounded-xl border border-dashed px-3 py-2 text-left text-xs transition-colors outline-none hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <span className="font-medium">+{more} more</span>
            <span className="text-muted-foreground">{tail.length ? "retrieved, not cited" : "sources"}</span>
          </button>
        </div>
      )}
    </div>
  )
}

function SourceCard({ kb, s, cited, active, onClick }: { kb: string; s: Source; cited: boolean; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={s.metadata?.path || s.source}
      data-active={active || undefined}
      className={cn(
        "group flex h-full w-44 flex-col gap-1.5 rounded-xl border bg-card px-3 py-2.5 text-left shadow-xs transition-all outline-none hover:-translate-y-px hover:border-foreground/15 hover:shadow-sm focus-visible:ring-3 focus-visible:ring-ring/50 data-active:border-brand/50 data-active:ring-2 data-active:ring-brand/20",
        !cited && "border-dashed bg-transparent shadow-none",
      )}
    >
      {s.modality === "image" && <Thumb kb={kb} docId={s.doc_id} className="h-16 w-full rounded-md bg-muted/60" />}
      <span className="flex min-w-0 items-center gap-1.5">
        <ModalityIcon modality={s.modality} />
        <span className="truncate text-xs font-medium">{shortName(s)}</span>
      </span>
      <span className="flex min-w-0 items-center justify-between gap-2">
        <span className="truncate text-xs text-muted-foreground">{shortLoc(s) || s.modality}</span>
        <SourceNumber n={s.index} />
      </span>
    </button>
  )
}

function SourcesPanel({ index, msg }: { index: number; msg: AssistantMessage }) {
  if (!msg.sources?.length) return <p className="py-6 text-sm text-muted-foreground">No sources were retrieved for this question.</p>
  const { cited, rest } = orderedSources(msg)
  const row = (s: Source) => (
    <li key={s.index}>
      <button
        type="button"
        onClick={() => openSource(index, s.index)}
        className="flex w-full gap-3 rounded-lg px-2 py-2.5 text-left transition-colors outline-none hover:bg-muted/60 focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <SourceNumber n={s.index} className="mt-0.5" />
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="flex min-w-0 items-center gap-1.5 text-sm">
            <ModalityIcon modality={s.modality} />
            <span className="truncate font-medium">{shortName(s)}</span>
            <span className="truncate text-xs text-muted-foreground">{shortLoc(s)}</span>
          </span>
          <span className="truncate font-mono text-[0.7rem] text-muted-foreground">{s.metadata?.path || s.source}</span>
          <span className="line-clamp-2 text-sm text-muted-foreground">{excerptOf(s, 220)}</span>
        </span>
      </button>
    </li>
  )
  return (
    <div className="flex flex-col gap-4">
      {cited.length > 0 && (
        <section>
          <h3 className="mb-1 px-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Cited in the answer · {cited.length}
          </h3>
          <ul>{cited.map(row)}</ul>
        </section>
      )}
      {rest.length > 0 && (
        <section className={cn(cited.length > 0 && "opacity-90")}>
          <h3 className="mb-1 px-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
            {cited.length ? "Also retrieved" : "Retrieved"} · {rest.length}
          </h3>
          <ul>{rest.map(row)}</ul>
        </section>
      )}
    </div>
  )
}
