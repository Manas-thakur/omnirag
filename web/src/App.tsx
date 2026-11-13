import * as React from "react"

import { AppSidebar } from "@/components/app/app-sidebar"
import { ChatView } from "@/components/app/chat-view"
import { CommandPalette } from "@/components/app/command-palette"
import { ApiKeyDialog, ConfirmDialog, CreateKbDialog, ShortcutsDialog } from "@/components/app/dialogs"
import { LibraryView } from "@/components/app/library-view"
import { SettingsView } from "@/components/app/settings-view"
import { SidePanel } from "@/components/app/side-panel"
import { TopBar } from "@/components/app/top-bar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useShortcuts } from "@/hooks/use-shortcuts"
import { boot, syncViewFromHash, useApp, VIEWS } from "@/lib/store"

function useThemeClass() {
  const theme = useApp((s) => s.theme)
  React.useEffect(() => {
    const mql = window.matchMedia("(prefers-color-scheme: dark)")
    const apply = () => {
      const dark = theme === "dark" || (theme === "system" && mql.matches)
      document.documentElement.classList.toggle("dark", dark)
    }
    apply()
    mql.addEventListener("change", apply)
    return () => mql.removeEventListener("change", apply)
  }, [theme])
}

export default function App() {
  const view = useApp((s) => s.view)
  const kb = useApp((s) => s.kb)
  useThemeClass()
  useShortcuts()

  React.useEffect(() => {
    void boot()
    window.addEventListener("hashchange", syncViewFromHash)
    // Dropping a file outside the drop zone must not navigate away from the app.
    const prevent = (e: DragEvent) => e.preventDefault()
    window.addEventListener("dragover", prevent)
    window.addEventListener("drop", prevent)
    return () => {
      window.removeEventListener("hashchange", syncViewFromHash)
      window.removeEventListener("dragover", prevent)
      window.removeEventListener("drop", prevent)
    }
  }, [])

  React.useEffect(() => {
    document.title = `${VIEWS[view]}${kb ? ` · ${kb}` : ""} · OmniRAG`
  }, [view, kb])

  return (
    <TooltipProvider delayDuration={300}>
      <a
        href="#main"
        onClick={(e) => {
          e.preventDefault()
          document.getElementById("main")?.focus()
        }}
        className="sr-only z-50 rounded-md bg-background px-3 py-2 text-sm shadow focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <SidebarProvider className="h-svh overflow-hidden">
        <AppSidebar />
        <SidebarInset className="min-w-0 overflow-hidden">
          <div className="flex min-h-0 flex-1">
            <main id="main" tabIndex={-1} className="flex min-h-0 min-w-0 flex-1 flex-col outline-none">
              <TopBar />
              {view === "chat" && <ChatView />}
              {view === "library" && <LibraryView />}
              {view === "settings" && <SettingsView />}
            </main>
            <SidePanel />
          </div>
        </SidebarInset>
      </SidebarProvider>
      <CommandPalette />
      <CreateKbDialog />
      <ConfirmDialog />
      <ApiKeyDialog />
      <ShortcutsDialog />
      <Toaster position="bottom-right" closeButton />
      <div id="announcer" className="sr-only" aria-live="polite" />
    </TooltipProvider>
  )
}
