import { cn } from "@/lib/utils"

export type DotState = "ok" | "down" | "offline" | "unknown"

export function StatusDot({ state, className }: { state: DotState; className?: string }) {
  return (
    <span
      aria-hidden="true"
      data-state={state}
      className={cn(
        "relative inline-flex size-2 shrink-0 rounded-full",
        state === "ok" && "bg-success",
        state === "down" && "bg-destructive",
        state === "offline" && "bg-muted-foreground/60",
        state === "unknown" && "animate-pulse bg-muted-foreground/40",
        className,
      )}
    >
      {state === "ok" && <span className="absolute inset-0 animate-ping rounded-full bg-success opacity-40 [animation-iteration-count:2]" />}
    </span>
  )
}
