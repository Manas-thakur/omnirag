import { ChevronsUpDownIcon, DatabaseIcon, LayersIcon, SquarePenIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Kbd } from "@/components/ui/kbd"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { plural } from "@/lib/format"
import { kbDocs, newChat, toggleScopePanel, useApp, VIEWS } from "@/lib/store"
import { cn } from "@/lib/utils"

export function TopBar() {
  const view = useApp((s) => s.view)
  const kb = useApp((s) => s.kb)
  const stats = useApp((s) => s.stats)
  const scopeCount = useApp((s) => s.scope.length)
  const total = useApp((s) => kbDocs(s)?.length ?? s.stats?.documents ?? null)
  const scopeOpen = useApp((s) => s.panel?.mode === "scope")

  return (
    <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2 border-b bg-background/80 px-3 backdrop-blur-md supports-[backdrop-filter]:bg-background/70 md:px-4">
      <SidebarTrigger className="-ml-1" aria-label="Toggle menu" />
      <Separator orientation="vertical" className="mr-1 data-vertical:h-4 data-vertical:self-center" />
      <div className="flex min-w-0 flex-1 items-center gap-1.5">
        {kb && (
          <>
            <Button
              variant="ghost"
              size="sm"
              className="min-w-0 gap-1.5 px-1.5 font-medium"
              onClick={() => useApp.setState({ palette: { open: true, mode: "kb" } })}
              title="Switch knowledge base"
            >
              <DatabaseIcon className="text-muted-foreground" />
              <span className="truncate">{kb}</span>
              <ChevronsUpDownIcon className="text-muted-foreground" />
            </Button>
            <span aria-hidden="true" className="text-muted-foreground/60">
              /
            </span>
          </>
        )}
        <h1 className="truncate text-sm font-medium">{VIEWS[view]}</h1>
        {kb && stats && (
          <span className="ml-2 hidden truncate text-xs text-muted-foreground lg:inline">
            {plural(stats.documents, "document")} · {plural(stats.chunks, "chunk")}
          </span>
        )}
      </div>
      {view === "chat" && kb && (
        <div className="flex items-center gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant={scopeCount ? "secondary" : "ghost"}
                size="sm"
                className={cn("gap-1.5", scopeCount && "bg-brand-soft text-foreground hover:bg-brand-soft/80")}
                aria-controls="side-panel"
                aria-expanded={scopeOpen}
                onClick={toggleScopePanel}
              >
                <LayersIcon className={cn(scopeCount && "text-brand")} />
                <span>Sources</span>
                <span className="rounded-sm bg-background/70 px-1 text-xs tabular-nums text-muted-foreground">
                  {scopeCount ? `${scopeCount}/${total ?? "–"}` : (total ?? "")}
                </span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              Choose the sources answers may use <Kbd>S</Kbd>
            </TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label="New chat" onClick={newChat}>
                <SquarePenIcon />
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              New chat <Kbd>N</Kbd>
            </TooltipContent>
          </Tooltip>
        </div>
      )}
    </header>
  )
}
