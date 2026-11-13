import * as React from "react"
import { ArrowRightIcon } from "lucide-react"

import { ModalityIcon } from "@/components/app/icons"
import { Button } from "@/components/ui/button"
import { useMediaQuery } from "@/hooks/use-media-query"
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card"
import { excerptOf, highlightRuns, shortLoc, shortName } from "@/lib/sources"
import type { Source } from "@/lib/types"
import { cn } from "@/lib/utils"

export function SourceNumber({ n, className }: { n: number; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-4.5 min-w-4.5 shrink-0 items-center justify-center rounded-[5px] bg-muted px-1 font-mono text-[0.68rem] font-medium tabular-nums text-muted-foreground",
        className,
      )}
    >
      {n}
    </span>
  )
}

export function Highlighted({ text, words }: { text: string; words: string[] }) {
  return (
    <>
      {highlightRuns(text, words).map((r, i) =>
        r.hit ? (
          <mark key={i} className="rounded-[3px] bg-brand-soft text-foreground [box-decoration-break:clone]">
            {r.text}
          </mark>
        ) : (
          <React.Fragment key={i}>{r.text}</React.Fragment>
        ),
      )}
    </>
  )
}

/**
 * Inline Citation: a pill naming the cited source ("auth.md +1"). Hover or
 * keyboard focus shows the excerpts; click opens the full source panel.
 * The accessible name keeps the `[n]` numbers.
 */
export function InlineCitation({
  nums,
  sources,
  label,
  words,
  active,
  onOpen,
}: {
  nums: number[]
  sources: Source[]
  label: (s: Source) => string
  words: string[]
  active?: boolean
  onOpen: (n: number) => void
}) {
  const [open, setOpen] = React.useState(false)
  const finePointer = useMediaQuery("(hover: hover) and (pointer: fine)")
  const known = [...new Set(nums)].filter((n) => sources.some((s) => s.index === n))
  if (!known.length) {
    return (
      <span className="text-xs text-muted-foreground" title="No matching source">
        [{nums.join(", ")}]
      </span>
    )
  }
  const items = known.map((n) => sources.find((s) => s.index === n)!)
  const first = items[0]
  const names = [...new Set(items.map(shortName))]
  const pill = (
    <button
      type="button"
      data-active={active || undefined}
      aria-label={`Source${known.length > 1 ? "s" : ""} ${known.join(", ")}: ${names.join(", ")}`}
      onClick={() => onOpen(known[0])}
      onFocus={() => setOpen(true)}
      onBlur={(e) => {
        if (!e.relatedTarget || !(e.relatedTarget as HTMLElement).closest?.("[data-slot=hover-card-content]")) setOpen(false)
      }}
      className={cn(
        "mx-0.5 inline-flex max-w-[16rem] translate-y-[-1px] items-center gap-1 rounded-full border border-transparent bg-muted px-2 py-px align-middle text-[0.72rem] leading-5 font-medium text-muted-foreground transition-colors outline-none",
        "hover:border-brand/30 hover:bg-brand-soft hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 data-active:border-brand/40 data-active:bg-brand-soft data-active:text-foreground",
      )}
    >
      <ModalityIcon modality={first.modality} className="size-3" />
      <span className="truncate">{label(first)}</span>
      {known.length > 1 && <span className="text-muted-foreground/80 tabular-nums">+{known.length - 1}</span>}
    </button>
  )
  // Touch screens get no hover card: a tap opens the source panel directly.
  if (!finePointer) return pill
  return (
    <HoverCard open={open} onOpenChange={setOpen} openDelay={120} closeDelay={120}>
      <HoverCardTrigger asChild>{pill}</HoverCardTrigger>
      <HoverCardContent
        className="w-[min(22rem,calc(100vw-2rem))] p-0"
        side="bottom"
        align="start"
        collisionPadding={12}
      >
        <ul className="divide-y">
          {items.slice(0, 3).map((s) => (
            <li key={s.index} className="flex flex-col gap-1.5 p-3">
              <div className="flex min-w-0 items-center gap-1.5 text-xs">
                <SourceNumber n={s.index} />
                <ModalityIcon modality={s.modality} />
                <span className="truncate font-medium">{shortName(s)}</span>
                <span className="ml-auto shrink-0 truncate text-muted-foreground">{shortLoc(s)}</span>
              </div>
              <p className="line-clamp-4 text-[0.8rem] leading-relaxed text-muted-foreground">
                <Highlighted text={excerptOf(s, 240)} words={words} />
              </p>
              <Button
                variant="ghost"
                size="xs"
                className="-ml-1.5 w-fit text-brand hover:text-brand"
                tabIndex={-1}
                onClick={() => {
                  setOpen(false)
                  onOpen(s.index)
                }}
              >
                Open source
                <ArrowRightIcon />
              </Button>
            </li>
          ))}
        </ul>
        {items.length > 3 && (
          <p className="border-t px-3 py-2 text-xs text-muted-foreground">+{items.length - 3} more in the Sources tab</p>
        )}
      </HoverCardContent>
    </HoverCard>
  )
}
