import * as React from "react"
import {
  CheckIcon,
  DatabaseIcon,
  KeyboardIcon,
  LayersIcon,
  LibraryIcon,
  MessageSquareIcon,
  MessageSquareTextIcon,
  MonitorIcon,
  MoonIcon,
  PlusIcon,
  Settings2Icon,
  SquarePenIcon,
  SunIcon,
  XIcon,
} from "lucide-react"
import { useShallow } from "zustand/react/shallow"

import { ModalityIcon } from "@/components/app/icons"
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command"
import { plural } from "@/lib/format"
import {
  clearScope,
  cycleTheme,
  focusComposer,
  kbChats,
  kbDocs,
  navigate,
  newChat,
  openChat,
  openPanel,
  switchKb,
  toggleScopePanel,
  useApp,
} from "@/lib/store"

export function CommandPalette() {
  const { open, mode } = useApp((s) => s.palette)
  const kbs = useApp((s) => s.kbs)
  const kb = useApp((s) => s.kb)
  const docs = useApp((s) => kbDocs(s))
  const chats = useApp(useShallow(kbChats))
  const chatId = useApp((s) => s.chatId)
  const scope = useApp((s) => s.scope.length)
  const theme = useApp((s) => s.theme)
  const [search, setSearch] = React.useState("")

  const setOpen = (o: boolean) => {
    useApp.setState({ palette: { open: o, mode } })
    if (!o) setSearch("")
  }
  const run = (fn: () => void) => () => {
    setOpen(false)
    // Let the dialog return focus before the command moves it.
    setTimeout(fn, 0)
  }
  const ThemeIcon = theme === "dark" ? MoonIcon : theme === "light" ? SunIcon : MonitorIcon
  const browsing = !search.trim()

  return (
    <CommandDialog
      open={open}
      onOpenChange={setOpen}
      title={mode === "kb" ? "Switch knowledge base" : "Command palette"}
      description="Search for a command, document, conversation or knowledge base"
      className="sm:max-w-xl"
    >
      <Command loop>
      <CommandInput
        placeholder={mode === "kb" ? "Switch knowledge base…" : "Type a command, document or knowledge base…"}
        value={search}
        onValueChange={setSearch}
      />
      <CommandList className="max-h-[min(26rem,60vh)]">
        <CommandEmpty>No matches for “{search}”.</CommandEmpty>
        {mode === "kb" ? (
          <CommandGroup heading="Knowledge bases">
            {(kbs ?? []).map((k) => (
              <CommandItem key={k.name} value={`kb ${k.name}`} onSelect={run(() => void switchKb(k.name))}>
                {k.name === kb ? <CheckIcon /> : <DatabaseIcon />}
                <span className="truncate">{k.name}</span>
                <CommandShortcut>{plural(k.documents, "doc")}</CommandShortcut>
              </CommandItem>
            ))}
            <CommandItem value="create knowledge base" onSelect={run(() => useApp.setState({ kbDialogOpen: true }))}>
              <PlusIcon />
              Create knowledge base…
            </CommandItem>
          </CommandGroup>
        ) : (
          <>
            <CommandGroup heading="Actions">
              <CommandItem value="new chat" onSelect={run(newChat)}>
                <SquarePenIcon />
                New chat
                <CommandShortcut>N</CommandShortcut>
              </CommandItem>
              <CommandItem value="focus the question box ask" onSelect={run(focusComposer)}>
                <MessageSquareIcon />
                Focus the question box
                <CommandShortcut>/</CommandShortcut>
              </CommandItem>
              {kb && (
                <CommandItem value="choose sources scope" onSelect={run(toggleScopePanel)}>
                  <LayersIcon />
                  Choose sources…
                  <CommandShortcut>S</CommandShortcut>
                </CommandItem>
              )}
              {scope > 0 && (
                <CommandItem value="clear source scope use all sources" onSelect={run(clearScope)}>
                  <XIcon />
                  Clear source scope ({plural(scope, "source")})
                </CommandItem>
              )}
              <CommandItem value="toggle theme dark light" onSelect={run(cycleTheme)}>
                <ThemeIcon />
                Toggle theme (now {theme})
              </CommandItem>
              <CommandItem value="keyboard shortcuts help" onSelect={run(() => useApp.setState({ shortcutsOpen: true }))}>
                <KeyboardIcon />
                Keyboard shortcuts
                <CommandShortcut>?</CommandShortcut>
              </CommandItem>
              <CommandItem value="create knowledge base" onSelect={run(() => useApp.setState({ kbDialogOpen: true }))}>
                <PlusIcon />
                Create knowledge base…
              </CommandItem>
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup heading="Go to">
              <CommandItem value="go to chat" onSelect={run(() => navigate("chat"))}>
                <MessageSquareIcon />
                Chat
                <CommandShortcut>G C</CommandShortcut>
              </CommandItem>
              <CommandItem value="go to library documents upload" onSelect={run(() => navigate("library"))}>
                <LibraryIcon />
                Library
                <CommandShortcut>G L</CommandShortcut>
              </CommandItem>
              <CommandItem value="go to settings model" onSelect={run(() => navigate("settings"))}>
                <Settings2Icon />
                Settings
                <CommandShortcut>G S</CommandShortcut>
              </CommandItem>
            </CommandGroup>
            {(kbs ?? []).some((k) => k.name !== kb) && (
              <CommandGroup heading="Knowledge bases">
                {(kbs ?? [])
                  .filter((k) => k.name !== kb)
                  .map((k) => (
                    <CommandItem key={k.name} value={`switch to ${k.name}`} onSelect={run(() => void switchKb(k.name))}>
                      <DatabaseIcon />
                      Switch to {k.name}
                      <CommandShortcut>{plural(k.documents, "doc")}</CommandShortcut>
                    </CommandItem>
                  ))}
              </CommandGroup>
            )}
            {docs && docs.length > 0 && (
              <CommandGroup heading="Documents">
                {(browsing ? docs.slice(0, 5) : docs).map((d) => (
                  <CommandItem
                    key={d.doc_id}
                    value={`doc ${d.name} ${d.path} ${d.doc_id}`}
                    onSelect={run(() => openPanel({ mode: "doc", docId: d.doc_id }))}
                  >
                    <ModalityIcon modality={d.modality} />
                    <span className="truncate">{d.name}</span>
                    <span className="ml-auto truncate pl-2 text-xs text-muted-foreground">{d.path !== d.name ? d.path : d.modality}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
            {chats.some((c) => c.id !== chatId) && (
              <CommandGroup heading="Conversations">
                {(browsing ? chats.slice(0, 4) : chats)
                  .filter((c) => c.id !== chatId)
                  .map((c) => (
                    <CommandItem key={c.id} value={`chat ${c.title} ${c.id}`} onSelect={run(() => openChat(c.id))}>
                      <MessageSquareTextIcon />
                      <span className="truncate">{c.title}</span>
                    </CommandItem>
                  ))}
              </CommandGroup>
            )}
          </>
        )}
      </CommandList>
      </Command>
    </CommandDialog>
  )
}
