import * as React from "react"
import {
  CheckIcon,
  CopyIcon,
  ExternalLinkIcon,
  MessageSquareIcon,
  PlusIcon,
  SearchIcon,
  XIcon,
} from "lucide-react"
import { toast } from "sonner"
import { useShallow } from "zustand/react/shallow"

import { Highlighted, SourceNumber } from "@/components/app/citation"
import { ModalityIcon } from "@/components/app/icons"
import { HighlightedCode } from "@/components/app/markdown-view"
import { Thumb } from "@/components/app/thumb"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Drawer, DrawerContent, DrawerDescription, DrawerTitle } from "@/components/ui/drawer"
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group"
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { useMediaQuery } from "@/hooks/use-media-query"
import { api, ApiError } from "@/lib/api"
import { exactTime, formatBytes, plural, relativeTime } from "@/lib/format"
import { questionWords, shortLoc, shortName } from "@/lib/sources"
import {
  askAboutDoc,
  clearScope,
  closePanel,
  kbDocs,
  openRaw,
  setScope,
  toggleScope,
  useApp,
  type Panel,
} from "@/lib/store"
import type { AssistantMessage, ChunkPreview, DocumentInfo } from "@/lib/types"
import { cn } from "@/lib/utils"

const TITLES = { scope: "Sources", preview: "Source preview", doc: "Document" } as const

/** Right-hand panel: inline on wide screens, a sheet on tablets and a bottom drawer on phones. */
export function SidePanel() {
  const panel = useApp((s) => s.panel)
  const wide = useMediaQuery("(min-width: 1280px)")
  const phone = useMediaQuery("(max-width: 639px)")
  const content = panel ? <PanelContent panel={panel} /> : null

  if (wide) {
    if (!panel) return null
    return (
      <aside
        id="side-panel"
        aria-label={TITLES[panel.mode]}
        className="flex w-[26rem] shrink-0 flex-col border-l bg-background animate-in fade-in-0 slide-in-from-right-2 duration-200"
      >
        {content}
      </aside>
    )
  }
  if (phone) {
    return (
      <Drawer open={Boolean(panel)} onOpenChange={(o) => !o && closePanel()}>
        <DrawerContent id="side-panel" className="max-h-[88dvh]">
          <DrawerTitle className="sr-only">{panel ? TITLES[panel.mode] : "Panel"}</DrawerTitle>
          <DrawerDescription className="sr-only">Details panel</DrawerDescription>
          <div className="flex min-h-0 flex-1 flex-col">{content}</div>
        </DrawerContent>
      </Drawer>
    )
  }
  return (
    <Sheet open={Boolean(panel)} onOpenChange={(o) => !o && closePanel()}>
      <SheetContent id="side-panel" side="right" showCloseButton={false} className="w-full gap-0 p-0 sm:max-w-md">
        <SheetTitle className="sr-only">{panel ? TITLES[panel.mode] : "Panel"}</SheetTitle>
        <SheetDescription className="sr-only">Details panel</SheetDescription>
        {content}
      </SheetContent>
    </Sheet>
  )
}

function PanelContent({ panel }: { panel: Exclude<Panel, null> }) {
  if (panel.mode === "scope") return <ScopePanel />
  if (panel.mode === "preview") return <PreviewPanel chatId={panel.chatId} index={panel.index} n={panel.n} />
  return <DocPanel docId={panel.docId} />
}

function PanelHeader({ title, sub }: { title: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <header className="flex shrink-0 items-start gap-2 border-b px-4 py-3">
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <h2 className="flex min-w-0 items-center gap-2 text-sm font-semibold">{title}</h2>
        {sub && <div className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">{sub}</div>}
      </div>
      <Button variant="ghost" size="icon-sm" aria-label="Close panel" onClick={closePanel} className="-mr-1.5">
        <XIcon />
      </Button>
    </header>
  )
}

// ----------------------------------------------------------------- scope
function ScopePanel() {
  const docs = useApp((s) => kbDocs(s))
  const scope = useApp(useShallow((s) => s.scope))
  const [q, setQ] = React.useState("")
  const inputRef = React.useRef<HTMLInputElement>(null)
  React.useEffect(() => {
    inputRef.current?.focus()
  }, [])
  const query = q.trim().toLowerCase()
  const list = docs
    ? query
      ? docs.filter((d) => `${d.name} ${d.path} ${d.title} ${d.modality}`.toLowerCase().includes(query))
      : docs
    : null
  const allOn = Boolean(list?.length) && list!.every((d) => scope.includes(d.doc_id))
  const someOn = Boolean(list?.some((d) => scope.includes(d.doc_id)))
  const n = scope.length
  return (
    <>
      <PanelHeader
        title="Sources"
        sub={n ? `${n} of ${docs?.length ?? "…"} selected · answers use only these` : "Tick documents to limit answers to them"}
      />
      <div className="flex shrink-0 flex-col gap-2 border-b px-4 py-3">
        <InputGroup>
          <InputGroupAddon>
            <SearchIcon />
          </InputGroupAddon>
          <InputGroupInput
            ref={inputRef}
            type="search"
            placeholder="Filter sources"
            aria-label="Filter sources"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </InputGroup>
        <label className="flex items-center gap-2.5 px-1 text-sm">
          <Checkbox
            checked={allOn ? true : someOn ? "indeterminate" : false}
            disabled={!list?.length}
            onCheckedChange={(v) => {
              const ids = (list ?? []).map((d) => d.doc_id)
              const next = new Set(scope)
              for (const id of ids) {
                if (v === true) next.add(id)
                else next.delete(id)
              }
              setScope(next)
            }}
          />
          {query ? "Select matching" : "Select all"}
        </label>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {!list ? (
          <div className="flex flex-col gap-2 p-2">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        ) : list.length ? (
          <ul aria-label="Documents">
            {list.map((d) => (
              <li key={d.doc_id}>
                <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-sm transition-colors hover:bg-muted/60 has-[[data-state=checked]]:bg-brand-soft/60">
                  <Checkbox checked={scope.includes(d.doc_id)} onCheckedChange={(v) => toggleScope(d.doc_id, v === true)} />
                  <ModalityIcon modality={d.modality} />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate">{d.name}</span>
                    <small className="truncate text-xs text-muted-foreground">
                      {d.path !== d.name ? d.path : d.title || d.modality}
                    </small>
                  </span>
                  <span className="text-xs text-muted-foreground tabular-nums" title={plural(d.chunks, "chunk")}>
                    {d.chunks}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        ) : (
          <p className="p-4 text-center text-sm text-muted-foreground">No documents match.</p>
        )}
      </div>
      <footer className="flex shrink-0 items-center justify-between gap-2 border-t px-4 py-3">
        {n ? (
          <Button variant="ghost" size="sm" onClick={clearScope}>
            Use all sources
          </Button>
        ) : (
          <span className="text-xs text-muted-foreground">
            {docs ? `All ${plural(docs.length, "document")} are searched.` : ""}
          </span>
        )}
        <Button size="sm" onClick={closePanel}>
          Done
        </Button>
      </footer>
    </>
  )
}

// --------------------------------------------------------------- preview
function PreviewPanel({ chatId, index, n }: { chatId: string; index: number; n: number }) {
  const chat = useApp((s) => s.chats.find((c) => c.id === chatId))
  const msg = chat?.messages[index] as AssistantMessage | undefined
  const s = msg?.sources?.find((x) => x.index === n)
  const question = chat?.messages[index - 1]?.text ?? ""
  const [chunk, setChunk] = React.useState<{ id: string; data: ChunkPreview | null; note: string } | null>(null)
  const [copied, setCopied] = React.useState(false)
  const chunkId = s?.chunk_id
  const kb = chat?.kb

  React.useEffect(() => {
    if (!chunkId || !kb) return
    let live = true
    api.chunk(kb, chunkId, 1).then(
      (data) => live && setChunk({ id: chunkId, data, note: "" }),
      (err: unknown) =>
        live &&
        setChunk({
          id: chunkId,
          data: null,
          note:
            err instanceof ApiError && err.status === 404
              ? "This chunk is no longer in the knowledge base; showing the saved copy."
              : String(err instanceof Error ? err.message : err),
        }),
    )
    return () => {
      live = false
    }
  }, [chunkId, kb])

  if (!s || !chat || !msg) {
    return (
      <>
        <PanelHeader title="Source" />
        <p className="p-4 text-sm text-muted-foreground">This source is no longer available.</p>
      </>
    )
  }
  const loaded = chunk?.id === s.chunk_id ? chunk : null
  const meta = s.metadata ?? {}
  const content = loaded?.data?.content ?? s.content
  const words = questionWords(question)
  const lineStart = Number(meta.line_start)
  const isCode = s.modality === "code" && Number.isInteger(lineStart) && meta.line_start !== undefined
  // Code chunks are "description + fenced code"; number only the code lines.
  const fenced = isCode ? content.match(/^([\s\S]*?)```([\w+#.-]*)\n([\s\S]*?)\n?```\s*$/) : null
  const wasCited = msg.cited?.includes(n)
  const ranks = s.retrieval?.ranks
    ? Object.entries(s.retrieval.ranks)
        .map(([k, v]) => `${k} #${v}`)
        .join(" · ")
    : ""
  const metaRows = Object.entries(meta).filter(([k, v]) => v !== "" && v !== null && !["title", "path"].includes(k))
  const ctx = (list: { content: string }[] | undefined, label: string) =>
    list?.length ? (
      <section className="flex flex-col gap-1.5">
        <h3 className="text-xs font-medium text-muted-foreground">{label}</h3>
        <pre
          className={cn(
            "max-h-48 overflow-auto rounded-lg border border-dashed bg-muted/30 p-3 leading-relaxed whitespace-pre-wrap text-muted-foreground",
            s.modality === "code" ? "font-mono text-xs" : "font-sans text-[0.8rem]",
          )}
        >
          {list.map((c) => c.content).join("\n\n")}
        </pre>
      </section>
    ) : null

  return (
    <>
      <PanelHeader
        title={
          <>
            <SourceNumber n={n} />
            <span className="truncate">{shortName(s)}</span>
          </>
        }
        sub={
          <>
            <ModalityIcon modality={s.modality} />
            <span className="shrink-0">{shortLoc(s) || s.modality}</span>
            <span className="truncate font-mono">{meta.path || s.source}</span>
          </>
        }
      />
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        {loaded?.note && <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">{loaded.note}</p>}
        {s.modality === "image" && <Thumb kb={chat.kb} docId={s.doc_id} alt={shortName(s)} className="max-h-72 w-full rounded-lg border bg-muted/40" />}
        {!loaded ? <Skeleton className="h-12" /> : ctx(loaded.data?.before, "Before")}
        <section className="flex flex-col gap-1.5">
          <h3 className="flex items-center gap-1.5 text-xs font-medium">
            <span className={cn("size-1.5 rounded-full", wasCited ? "bg-brand" : "bg-muted-foreground")} />
            {wasCited ? "Cited passage" : "Retrieved passage"}
            {shortLoc(s) ? <span className="text-muted-foreground">· {shortLoc(s)}</span> : null}
          </h3>
          {isCode ? (
            <>
              {fenced?.[1].trim() && (
                <p className="text-sm leading-relaxed whitespace-pre-wrap text-muted-foreground">
                  <Highlighted text={fenced[1].trim()} words={words} />
                </p>
              )}
              <HighlightedCode
                code={fenced ? fenced[3] : content}
                lang={fenced?.[2] || String(meta.language ?? "")}
                title={baseNameOf(String(meta.path || s.source))}
                lineNumbers
                startLine={lineStart}
                size="sm"
              />
            </>
          ) : (
            <div className="rounded-lg border border-brand/30 bg-brand-soft/40 p-3 text-sm leading-relaxed whitespace-pre-wrap">
              <Highlighted text={content} words={words} />
            </div>
          )}
        </section>
        {loaded && ctx(loaded.data?.after, "After")}
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => void openRaw(chat.kb, s.doc_id)}>
            <ExternalLinkIcon />
            Open original
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              navigator.clipboard.writeText(content).then(
                () => setCopied(true),
                () => toast.error("Copy failed: clipboard access was blocked"),
              )
            }
          >
            {copied ? <CheckIcon /> : <CopyIcon />}
            {copied ? "Copied" : "Copy excerpt"}
          </Button>
        </div>
        <Collapsible className="rounded-lg border">
          <CollapsibleTrigger className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
            <span>Retrieval details{ranks ? ` · ${ranks}` : ""}</span>
            <PlusIcon className="size-3.5" />
          </CollapsibleTrigger>
          <CollapsibleContent>
            <table className="w-full border-t text-xs">
              <tbody>
                <tr className="border-b">
                  <th className="px-3 py-1.5 text-left font-medium text-muted-foreground">score</th>
                  <td className="px-3 py-1.5 font-mono">{Number(s.score).toFixed(3)}</td>
                </tr>
                {metaRows.map(([k, v]) => (
                  <tr key={k} className="border-b last:border-0">
                    <th className="px-3 py-1.5 text-left align-top font-medium text-muted-foreground">{k}</th>
                    <td className="px-3 py-1.5 font-mono break-all">{typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </>
  )
}

function baseNameOf(path: string) {
  return path.split(/[\\/]/).pop() ?? path
}

// ------------------------------------------------------------------- doc
function DocPanel({ docId }: { docId: string }) {
  const kb = useApp((s) => s.kb)
  const d = useApp((s) => s.docs?.find((x) => x.doc_id === docId)) as DocumentInfo | undefined
  const inScope = useApp((s) => s.scope.includes(docId))
  const [start, setStart] = React.useState<{ id: string; text: string } | null>(null)
  React.useEffect(() => {
    if (!kb) return
    let live = true
    // Chunk ids are "<doc_id>-<position>"; the first chunk gives a quick look inside.
    api.chunk(kb, `${docId}-0000`, 1).then(
      (c) => live && setStart({ id: docId, text: [c.content, ...c.after.map((x) => x.content)].join("\n\n").slice(0, 1600) }),
      () => live && setStart({ id: docId, text: "" }),
    )
    return () => {
      live = false
    }
  }, [kb, docId])
  if (!d || !kb) {
    return (
      <>
        <PanelHeader title="Document" />
        <p className="p-4 text-sm text-muted-foreground">This document is no longer in the knowledge base.</p>
      </>
    )
  }
  const preview = start?.id === docId ? start.text : null
  return (
    <>
      <PanelHeader
        title={<span className="truncate">{d.name}</span>}
        sub={
          <>
            <ModalityIcon modality={d.modality} />
            <span>{d.modality}</span>
            <span className="truncate font-mono">{d.path}</span>
          </>
        }
      />
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-sm">
          <dt className="text-muted-foreground">Chunks</dt>
          <dd className="tabular-nums">{d.chunks}</dd>
          <dt className="text-muted-foreground">Size</dt>
          <dd className="tabular-nums">{formatBytes(d.size_bytes)}</dd>
          <dt className="text-muted-foreground">Ingested</dt>
          <dd title={exactTime(d.updated_at)}>{relativeTime(d.updated_at)}</dd>
          {d.title && d.title !== d.name && (
            <>
              <dt className="text-muted-foreground">Title</dt>
              <dd>{d.title}</dd>
            </>
          )}
          {d.missing && (
            <>
              <dt className="text-muted-foreground">Status</dt>
              <dd className="text-destructive">Source file missing</dd>
            </>
          )}
        </dl>
        {d.modality === "image" && <Thumb kb={kb} docId={d.doc_id} alt={d.name} className="max-h-72 w-full rounded-lg border bg-muted/40" />}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => askAboutDoc(d.doc_id)}>
            <MessageSquareIcon />
            Ask about this document
          </Button>
          <Button variant="outline" size="sm" aria-pressed={inScope} onClick={() => toggleScope(d.doc_id)}>
            {inScope ? <CheckIcon /> : <PlusIcon />}
            {inScope ? "In scope" : "Add to scope"}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => void openRaw(kb, d.doc_id)}>
            <ExternalLinkIcon />
            Open original
          </Button>
        </div>
        <section className="flex flex-col gap-1.5">
          <h3 className="text-xs font-medium text-muted-foreground">Beginning of the document</h3>
          {preview === null ? (
            <Skeleton className="h-40" />
          ) : preview ? (
            <pre className="max-h-96 overflow-auto rounded-lg border bg-muted/30 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
              {preview}
            </pre>
          ) : (
            <p className="text-sm text-muted-foreground">No preview available.</p>
          )}
        </section>
      </div>
    </>
  )
}
