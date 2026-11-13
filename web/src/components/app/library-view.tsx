import * as React from "react"
import {
  CircleAlertIcon,
  CircleCheckIcon,
  DatabaseIcon,
  FileUpIcon,
  LayersIcon,
  Loader2Icon,
  MessageSquareIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
  UploadCloudIcon,
} from "lucide-react"
import { useShallow } from "zustand/react/shallow"

import { ModalityIcon } from "@/components/app/icons"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { InputGroup, InputGroupAddon, InputGroupInput } from "@/components/ui/input-group"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { exactTime, formatBytes, plural, relativeTime } from "@/lib/format"
import {
  askSelected,
  clearFinishedUploads,
  clearScope,
  deleteDoc,
  kbDocs,
  loadDocs,
  openPanel,
  reingestDoc,
  setScope,
  toggleScope,
  uploadFiles,
  useApp,
} from "@/lib/store"
import type { DocumentInfo } from "@/lib/types"
import { cn } from "@/lib/utils"

export function LibraryView() {
  const kb = useApp((s) => s.kb)
  const booted = useApp((s) => s.booted)
  if (booted && !kb) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <DatabaseIcon />
            </EmptyMedia>
            <EmptyTitle>No knowledge base selected</EmptyTitle>
            <EmptyDescription>Create one to start adding files.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button onClick={() => useApp.setState({ kbDialogOpen: true })}>
              <PlusIcon />
              New knowledge base
            </Button>
          </EmptyContent>
        </Empty>
      </div>
    )
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8">
        <Dropzone />
        <Uploads />
        <Documents />
      </div>
    </div>
  )
}

function Dropzone() {
  const kb = useApp((s) => s.kb)
  const status = useApp((s) => s.status)
  const [dragging, setDragging] = React.useState(false)
  const depth = React.useRef(0)
  const inputRef = React.useRef<HTMLInputElement>(null)
  return (
    <div
      onDragEnter={(e) => {
        e.preventDefault()
        depth.current += 1
        setDragging(true)
      }}
      onDragOver={(e) => e.preventDefault()}
      onDragLeave={() => {
        depth.current -= 1
        if (depth.current <= 0) setDragging(false)
      }}
      onDrop={(e) => {
        e.preventDefault()
        depth.current = 0
        setDragging(false)
        void uploadFiles(e.dataTransfer.files)
      }}
      className={cn(
        "relative flex flex-col items-center gap-4 rounded-2xl border border-dashed bg-muted/30 px-6 py-8 text-center transition-colors sm:flex-row sm:text-left",
        dragging && "border-brand bg-brand-soft/60",
      )}
    >
      <div className={cn("flex size-12 shrink-0 items-center justify-center rounded-xl border bg-background shadow-xs", dragging && "border-brand text-brand")}>
        <UploadCloudIcon className="size-5" />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="font-medium">
          Drop files to add them to <span className="text-brand">{kb}</span>
        </p>
        <p className="text-sm text-muted-foreground">
          Documents, code, tables, images and transcripts{status ? ` · up to ${status.max_upload_mb} MB per file` : ""}
        </p>
      </div>
      <Button variant="outline" onClick={() => inputRef.current?.click()}>
        <FileUpIcon />
        Choose files
      </Button>
      <input
        ref={inputRef}
        type="file"
        multiple
        className="sr-only"
        tabIndex={-1}
        aria-label="Choose files to upload"
        accept={status?.upload_extensions?.join(",")}
        onChange={(e) => {
          if (e.target.files) void uploadFiles(e.target.files)
          e.target.value = ""
        }}
      />
    </div>
  )
}

function Uploads() {
  const uploads = useApp((s) => s.uploads)
  if (!uploads.length) return null
  const busy = uploads.some((u) => u.state === "uploading" || u.state === "indexing" || u.state === "waiting")
  return (
    <section aria-label="Uploads" className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium">Uploads</h2>
        {!busy && (
          <Button variant="ghost" size="xs" onClick={clearFinishedUploads}>
            Clear
          </Button>
        )}
      </div>
      <ul className="flex flex-col divide-y rounded-xl border bg-card" aria-live="polite">
        {uploads.map((u) => (
          <li key={u.id} className="flex flex-col gap-1.5 px-3 py-2.5">
            <div className="flex items-center gap-2 text-sm">
              {u.state === "done" ? (
                <CircleCheckIcon className="size-4 text-success" aria-hidden="true" />
              ) : u.state === "error" ? (
                <CircleAlertIcon className="size-4 text-destructive" aria-hidden="true" />
              ) : (
                <Loader2Icon className="size-4 animate-spin text-muted-foreground" aria-hidden="true" />
              )}
              <span className="min-w-0 flex-1 truncate" title={u.name}>
                {u.name}
              </span>
              <span className={cn("shrink-0 text-xs", u.state === "error" ? "text-destructive" : "text-muted-foreground")}>
                {u.message}
              </span>
            </div>
            {(u.state === "uploading" || u.state === "indexing") && (
              <Progress value={u.state === "indexing" ? 100 : Math.round(u.progress * 100)} className={cn("h-1", u.state === "indexing" && "animate-pulse")} aria-label={`Uploading ${u.name}`} />
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

function Documents() {
  const kb = useApp((s) => s.kb)
  const docs = useApp((s) => kbDocs(s))
  const error = useApp((s) => s.docsError)
  const scope = useApp(useShallow((s) => s.scope))
  const [q, setQ] = React.useState("")
  const query = q.trim().toLowerCase()
  const list = docs
    ? query
      ? docs.filter((d) => `${d.name} ${d.path} ${d.title} ${d.modality}`.toLowerCase().includes(query))
      : docs
    : null
  const allOn = Boolean(list?.length) && list!.every((d) => scope.includes(d.doc_id))
  const someOn = Boolean(list?.some((d) => scope.includes(d.doc_id)))

  return (
    <section aria-labelledby="docs-heading" className="flex flex-col gap-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 id="docs-heading" className="flex items-center gap-2 text-base font-semibold">
          Documents
          {docs && (
            <Badge variant="secondary" className="tabular-nums">
              {query ? `${list?.length} of ${docs.length}` : docs.length}
            </Badge>
          )}
        </h2>
        <InputGroup className="sm:w-72">
          <InputGroupAddon>
            <SearchIcon />
          </InputGroupAddon>
          <InputGroupInput
            type="search"
            placeholder="Filter by name, path or type"
            aria-label="Search documents"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </InputGroup>
      </div>

      {scope.length > 0 && docs && (
        <div role="region" aria-label="Selected sources" className="flex flex-col gap-2 rounded-xl border border-brand/25 bg-brand-soft/60 px-3 py-2.5 text-sm sm:flex-row sm:items-center">
          <span className="flex flex-1 items-center gap-2">
            <LayersIcon className="size-4 text-brand" />
            <span>
              <strong className="font-medium">{plural(scope.length, "source")} selected</strong>
              <span className="text-muted-foreground"> · chat answers use only these</span>
            </span>
          </span>
          <span className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={clearScope}>
              Clear
            </Button>
            <Button size="sm" onClick={askSelected}>
              <MessageSquareIcon />
              Ask the selected sources
            </Button>
          </span>
        </div>
      )}

      {error && !docs ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>Could not load documents</EmptyTitle>
            <EmptyDescription>{error}</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button variant="outline" onClick={() => void loadDocs()}>
              <RefreshCwIcon />
              Try again
            </Button>
          </EmptyContent>
        </Empty>
      ) : !list ? (
        <div className="flex flex-col gap-2" aria-busy="true" aria-label="Loading documents">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-12 rounded-lg" />
          ))}
        </div>
      ) : !docs?.length ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>No documents yet</EmptyTitle>
            <EmptyDescription>
              Drop files above, or ingest a folder with{" "}
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">omnirag ingest PATH --kb {kb}</code>.
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : !list.length ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>No matches</EmptyTitle>
            <EmptyDescription>Nothing matches “{q}”.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="overflow-hidden rounded-xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-10 pl-3">
                  <Checkbox
                    aria-label={`Select all ${query ? "matching " : ""}documents`}
                    checked={allOn ? true : someOn ? "indeterminate" : false}
                    onCheckedChange={(v) => {
                      const next = new Set(scope)
                      for (const d of list) {
                        if (v === true) next.add(d.doc_id)
                        else next.delete(d.doc_id)
                      }
                      setScope(next)
                    }}
                  />
                </TableHead>
                <TableHead>Name</TableHead>
                <TableHead className="hidden md:table-cell">Type</TableHead>
                <TableHead className="hidden text-right md:table-cell">Chunks</TableHead>
                <TableHead className="hidden text-right md:table-cell">Size</TableHead>
                <TableHead className="hidden md:table-cell">Ingested</TableHead>
                <TableHead className="w-20 text-right">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((d) => (
                <DocRow key={d.doc_id} d={d} selected={scope.includes(d.doc_id)} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  )
}

function DocRow({ d, selected }: { d: DocumentInfo; selected: boolean }) {
  const [busy, setBusy] = React.useState(false)
  return (
    <TableRow data-state={selected ? "selected" : undefined}>
      <TableCell className="pl-3">
        <Checkbox aria-label={`Select ${d.name}`} checked={selected} onCheckedChange={(v) => toggleScope(d.doc_id, v === true)} />
      </TableCell>
      <TableCell className="max-w-0 min-w-40 whitespace-normal">
        <button
          type="button"
          onClick={() => openPanel({ mode: "doc", docId: d.doc_id })}
          title={d.source}
          className="flex w-full min-w-0 flex-col items-start rounded-md text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <span className="flex max-w-full min-w-0 items-center gap-1.5 font-medium hover:underline">
            <ModalityIcon modality={d.modality} className="md:hidden" />
            <span className="truncate">{d.name}</span>
            {d.missing && (
              <Badge variant="destructive" className="h-4 px-1.5 text-[0.65rem]">
                missing
              </Badge>
            )}
          </span>
          {(d.path !== d.name || (d.title && d.title !== d.name)) && (
            <span className="max-w-full truncate text-xs text-muted-foreground">{d.path !== d.name ? d.path : d.title}</span>
          )}
          <span className="text-xs text-muted-foreground md:hidden">
            {d.modality} · {plural(d.chunks, "chunk")} · {formatBytes(d.size_bytes)}
          </span>
        </button>
      </TableCell>
      <TableCell className="hidden md:table-cell">
        <span className="inline-flex items-center gap-1.5 text-muted-foreground">
          <ModalityIcon modality={d.modality} />
          {d.modality}
        </span>
      </TableCell>
      <TableCell className="hidden text-right tabular-nums md:table-cell">{d.chunks}</TableCell>
      <TableCell className="hidden text-right text-muted-foreground tabular-nums md:table-cell">{formatBytes(d.size_bytes)}</TableCell>
      <TableCell className="hidden text-muted-foreground md:table-cell">
        <span title={exactTime(d.updated_at)}>{relativeTime(d.updated_at)}</span>
      </TableCell>
      <TableCell className="pr-2 text-right">
        <div className="flex justify-end gap-0.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Re-ingest ${d.name}`}
                disabled={d.missing || busy}
                onClick={async () => {
                  setBusy(true)
                  await reingestDoc(d.doc_id)
                  setBusy(false)
                }}
              >
                <RefreshCwIcon className={cn(busy && "animate-spin")} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{d.missing ? "Source file missing" : "Re-ingest"}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                className="hover:text-destructive"
                aria-label={`Delete ${d.name}`}
                onClick={() => void deleteDoc(d.doc_id)}
              >
                <Trash2Icon />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Delete</TooltipContent>
          </Tooltip>
        </div>
      </TableCell>
    </TableRow>
  )
}
