import * as React from "react"
import { ArrowUpIcon, LayersIcon, SlidersHorizontalIcon, SquareIcon, XIcon } from "lucide-react"
import { useShallow } from "zustand/react/shallow"

import { ModalityIcon } from "@/components/app/icons"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from "@/components/ui/input-group"
import { Kbd } from "@/components/ui/kbd"
import { MOD_KEY, plural } from "@/lib/format"
import { ask, clearScope, openPanel, scopedDocs, stopStreaming, toggleFilter, useApp } from "@/lib/store"
import { MODALITIES, MODALITY_LABEL } from "@/lib/types"
import { cn } from "@/lib/utils"

/** Prompt Input: question box, content-type filter, scope chip and send / stop. */
export function Composer({ placeholder, large = false }: { placeholder: string; large?: boolean }) {
  const [text, setText] = React.useState("")
  const formRef = React.useRef<HTMLFormElement>(null)
  const kb = useApp((s) => s.kb)
  const streaming = useApp((s) => s.streaming)
  const empty = useApp((s) => s.stats?.documents === 0)
  const filters = useApp(useShallow((s) => s.filters))
  const disabled = !kb
  const canSend = !streaming && Boolean(text.trim()) && Boolean(kb) && !empty

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (streaming) return stopStreaming()
    if (!canSend) return
    const q = text
    setText("")
    void ask(q)
  }

  return (
    <form ref={formRef} onSubmit={submit} className="flex w-full flex-col gap-2" autoComplete="off">
      <ScopeChip />
      <InputGroup
        className={cn(
          "rounded-2xl bg-card shadow-sm transition-shadow focus-within:shadow-md dark:bg-card has-disabled:bg-card has-disabled:opacity-100 dark:has-disabled:bg-card has-[textarea:disabled]:opacity-60",
          large && "shadow-md",
        )}
      >
        <label htmlFor="question" className="sr-only">
          Question
        </label>
        <InputGroupTextarea
          id="question"
          value={text}
          disabled={disabled}
          maxLength={4000}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              formRef.current?.requestSubmit()
            }
          }}
          placeholder={placeholder}
          className={cn("max-h-52 min-h-12 px-4 pt-3.5 text-[0.95rem]", large && "min-h-20")}
        />
        <InputGroupAddon align="block-end" className="gap-1 px-2.5 pb-2.5">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <InputGroupButton
                variant={filters.length ? "secondary" : "ghost"}
                size="xs"
                className="gap-1.5 rounded-full px-2.5 text-muted-foreground"
                aria-label={filters.length ? `Content types: ${filters.map((f) => MODALITY_LABEL[f]).join(", ")}` : "Content types: all"}
              >
                {filters.length ? (
                  <span className="flex -space-x-0.5">
                    {filters.map((f) => (
                      <ModalityIcon key={f} modality={f} />
                    ))}
                  </span>
                ) : (
                  <SlidersHorizontalIcon />
                )}
                <span className="hidden sm:inline">
                  {filters.length ? filters.map((f) => MODALITY_LABEL[f]).join(", ") : "All types"}
                </span>
              </InputGroupButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-52">
              <DropdownMenuLabel>Limit to content types</DropdownMenuLabel>
              <DropdownMenuItem onSelect={() => toggleFilter(null)}>
                <span className="flex-1">All types</span>
                {!filters.length && <span className="text-xs text-muted-foreground">on</span>}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              {MODALITIES.map((m) => (
                <DropdownMenuCheckboxItem
                  key={m}
                  checked={filters.includes(m)}
                  onCheckedChange={() => toggleFilter(m)}
                  onSelect={(e) => e.preventDefault()}
                >
                  <ModalityIcon modality={m} />
                  {MODALITY_LABEL[m]}
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <span className="ml-auto hidden items-center gap-1 text-xs text-muted-foreground md:flex">
            <Kbd>Enter</Kbd> send · <Kbd>Shift Enter</Kbd> new line
          </span>
          <InputGroupButton
            type="submit"
            variant="default"
            size="icon-sm"
            className={cn("rounded-full md:ml-2", "ml-auto")}
            disabled={!streaming && !canSend}
            aria-label={streaming ? "Stop generating" : "Send"}
            title={streaming ? "Stop generating (Esc)" : "Send (Enter)"}
          >
            {streaming ? <SquareIcon className="fill-current" /> : <ArrowUpIcon />}
          </InputGroupButton>
        </InputGroupAddon>
      </InputGroup>
      {large && (
        <p className="hidden text-center text-xs text-muted-foreground sm:block">
          <Kbd>{MOD_KEY} K</Kbd> commands · inline filters like <code className="font-mono">source:*.py</code> or{" "}
          <code className="font-mono">modality:table</code>
        </p>
      )}
    </form>
  )
}

function ScopeChip() {
  const n = useApp((s) => s.scope.length)
  const names = useApp(useShallow((s) => scopedDocs(s).map((d) => d.name)))
  if (!n) return null
  const title = names.slice(0, 3).join(", ") + (names.length > 3 ? ", …" : "")
  return (
    <div className="flex">
      <div className="inline-flex items-center rounded-full border border-brand/25 bg-brand-soft text-xs">
        <Button
          variant="ghost"
          size="xs"
          className="h-6 rounded-full rounded-r-none pr-1.5 pl-2.5 hover:bg-transparent"
          title={title}
          onClick={() => openPanel({ mode: "scope" })}
        >
          <LayersIcon className="text-brand" />
          Scoped to {plural(n, "source")}
        </Button>
        <Button
          variant="ghost"
          size="icon-xs"
          className="mr-0.5 size-5 rounded-full hover:bg-background/60"
          aria-label="Clear source scope (use all sources)"
          onClick={clearScope}
        >
          <XIcon />
        </Button>
      </div>
    </div>
  )
}
