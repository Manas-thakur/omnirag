import * as React from "react"

import { closePanel, focusComposer, navigate, newChat, stopStreaming, toggleScopePanel, useApp } from "@/lib/store"

/** Global keyboard shortcuts (see the shortcuts dialog for the list). */
export function useShortcuts() {
  React.useEffect(() => {
    let chord = 0 // time of a pending "g" chord
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const typing = Boolean(target?.closest?.("input, textarea, select, [contenteditable=true], [role=combobox]"))
      const dialogOpen = Boolean(document.querySelector('[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]'))
      const s = useApp.getState()

      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault()
        useApp.setState({ palette: { open: !s.palette.open, mode: "all" } })
        return
      }
      if (dialogOpen || e.defaultPrevented) return
      if (e.key === "Escape") {
        if (s.streaming && !typing) stopStreaming()
        else if (s.panel && window.matchMedia("(min-width: 1280px)").matches) closePanel()
        return
      }
      if (typing || e.ctrlKey || e.metaKey || e.altKey) return
      const key = e.key.toLowerCase()
      if (chord && Date.now() - chord < 1200) {
        chord = 0
        const to = ({ c: "chat", l: "library", s: "settings" } as const)[key as "c" | "l" | "s"]
        if (to) {
          e.preventDefault()
          navigate(to)
        }
        return
      }
      if (e.key === "?") {
        e.preventDefault()
        useApp.setState({ shortcutsOpen: true })
      } else if (e.key === "/") {
        e.preventDefault()
        focusComposer()
      } else if (key === "g") chord = Date.now()
      else if (key === "n") {
        e.preventDefault()
        newChat()
      } else if (key === "s" && s.kb) {
        e.preventDefault()
        toggleScopePanel()
      }
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [])
}
