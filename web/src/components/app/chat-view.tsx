import * as React from "react"
import { ArrowUpRightIcon, DatabaseIcon, PlusIcon, UploadIcon } from "lucide-react"

import { Composer } from "@/components/app/composer"
import { Logo, ModalityIcon } from "@/components/app/icons"
import { Turn } from "@/components/app/turn"
import { Button } from "@/components/ui/button"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Message, MessageContent } from "@/components/ui/message"
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from "@/components/ui/message-scroller"
import { Skeleton } from "@/components/ui/skeleton"
import { plural } from "@/lib/format"
import { ask, currentChat, loadStarters, navigate, startersKey, useApp } from "@/lib/store"
import { MODALITIES, MODALITY_LABEL, type AssistantMessage } from "@/lib/types"

export function ChatView() {
  const chat = useApp((s) => currentChat(s))
  const booted = useApp((s) => s.booted)
  const kb = useApp((s) => s.kb)
  const stats = useApp((s) => s.stats)
  const scope = useApp((s) => s.scope.length)
  const streaming = useApp((s) => s.streaming)

  if (!booted) return <HomeSkeleton />
  if (!kb) {
    return (
      <Centered>
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <DatabaseIcon />
            </EmptyMedia>
            <EmptyTitle>Create a knowledge base</EmptyTitle>
            <EmptyDescription>
              A knowledge base holds the documents, code, tables, images and transcripts OmniRAG answers from. Everything
              stays on this server.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => useApp.setState({ kbDialogOpen: true })}>
              <PlusIcon />
              New knowledge base
            </Button>
          </EmptyContent>
        </Empty>
      </Centered>
    )
  }
  if (stats && stats.documents === 0) {
    return (
      <Centered>
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <UploadIcon />
            </EmptyMedia>
            <EmptyTitle>{kb} is empty</EmptyTitle>
            <EmptyDescription>
              Add files in the library, then ask about them here. Answers cite the exact section, line range, table rows
              or timestamp they came from.
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => navigate("library")}>
              <UploadIcon />
              Add files
            </Button>
          </EmptyContent>
        </Empty>
      </Centered>
    )
  }

  const messages = chat?.messages ?? []
  if (!chat || !messages.length) {
    const kinds = stats
      ? MODALITIES.filter((m) => stats.documents_by_modality?.[m]).map((m) => MODALITY_LABEL[m].toLowerCase())
      : []
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-7 px-4 py-10 sm:py-16">
          <div className="flex flex-col items-center gap-3 text-center">
            <Logo className="size-10 rounded-xl shadow-sm" />
            <h2 className="text-2xl font-semibold tracking-tight text-balance sm:text-3xl">
              Ask <span className="text-brand">{kb}</span> anything
            </h2>
            <p className="text-sm text-muted-foreground">
              {stats ? (
                <>
                  {plural(stats.documents, "document")} · {plural(stats.chunks, "chunk")}
                  {kinds.length ? ` · ${kinds.join(", ")}` : ""}
                </>
              ) : (
                <Skeleton className="mx-auto h-4 w-48" />
              )}
            </p>
          </div>
          <Composer large placeholder={scope ? `Ask the ${plural(scope, "selected source")}` : `Ask ${kb} anything`} />
          <Starters />
        </div>
      </div>
    )
  }

  const turns: { index: number; question: string; msg: AssistantMessage }[] = []
  messages.forEach((m, i) => {
    if (m.role === "assistant") turns.push({ index: i, question: messages[i - 1]?.text ?? "", msg: m })
  })

  return (
    <MessageScrollerProvider>
      <div className="relative flex min-h-0 flex-1 flex-col">
        <MessageScroller className="min-h-0 flex-1">
          <MessageScrollerViewport aria-label="Conversation">
            <MessageScrollerContent aria-busy={streaming} className="mx-auto w-full max-w-3xl gap-14 px-4 pt-8 pb-16 sm:px-6">
              {turns.map((t) => (
                <MessageScrollerItem key={`${chat.id}-${t.index}`} messageId={`${chat.id}-${t.index}`} scrollAnchor>
                  <Message className="text-base">
                    <MessageContent>
                      <Turn kb={chat.kb} chatId={chat.id} index={t.index} question={t.question} msg={t.msg} />
                    </MessageContent>
                  </Message>
                </MessageScrollerItem>
              ))}
            </MessageScrollerContent>
          </MessageScrollerViewport>
          <MessageScrollerButton aria-label="Jump to latest" />
        </MessageScroller>
        <div className="relative shrink-0 px-3 pb-3 sm:px-6 sm:pb-5">
          <div className="pointer-events-none absolute inset-x-0 -top-8 h-8 bg-gradient-to-t from-background to-transparent" />
          <div className="mx-auto w-full max-w-3xl">
            <Composer placeholder={scope ? `Ask a follow-up about the ${plural(scope, "selected source")}` : "Ask a follow-up"} />
          </div>
        </div>
      </div>
    </MessageScrollerProvider>
  )
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto p-6">{children}</div>
}

function HomeSkeleton() {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center gap-6 px-4" aria-busy="true" aria-label="Loading">
      <Skeleton className="mx-auto size-10 rounded-xl" />
      <Skeleton className="mx-auto h-8 w-72" />
      <Skeleton className="h-28 w-full rounded-2xl" />
    </div>
  )
}

/** Suggestion: starter questions phrased offline from the knowledge base's headings and symbols. */
function Starters() {
  const items = useApp((s) => (s.starters?.key === startersKey(s) ? s.starters.items : null))
  const key = useApp(startersKey)
  React.useEffect(() => {
    void loadStarters()
  }, [key])
  if (items && !items.length) return null
  return (
    <section aria-label="Suggested questions" className="flex flex-col gap-2">
      <h3 className="px-1 text-xs font-medium text-muted-foreground">Try asking</h3>
      <div className="grid gap-2 sm:grid-cols-2">
        {items
          ? items.map((s) => (
              <button
                key={s.question}
                type="button"
                onClick={() => void ask(s.question)}
                className="group flex flex-col gap-2 rounded-xl border bg-card px-3.5 py-3 text-left shadow-xs transition-all outline-none hover:-translate-y-px hover:border-foreground/15 hover:shadow-sm focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <span className="flex items-start justify-between gap-2 text-sm leading-snug font-medium">
                  {s.question}
                  <ArrowUpRightIcon className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                </span>
                <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                  <ModalityIcon modality={s.modality} />
                  <span className="truncate">{s.source}</span>
                </span>
              </button>
            ))
          : Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-[4.5rem] rounded-xl" />)}
      </div>
    </section>
  )
}
