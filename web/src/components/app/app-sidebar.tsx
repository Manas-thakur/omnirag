import {
  DatabaseIcon,
  KeyboardIcon,
  LibraryIcon,
  MessageSquareIcon,
  MonitorIcon,
  MoonIcon,
  PlusIcon,
  SearchIcon,
  Settings2Icon,
  SquarePenIcon,
  SunIcon,
  Trash2Icon,
} from "lucide-react"

import { useShallow } from "zustand/react/shallow"

import { Logo } from "@/components/app/icons"
import { StatusDot } from "@/components/app/status"
import { Button } from "@/components/ui/button"
import { Kbd } from "@/components/ui/kbd"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  useSidebar,
} from "@/components/ui/sidebar"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { MOD_KEY, plural } from "@/lib/format"
import {
  cycleTheme,
  deleteChat,
  deleteKb,
  kbChats,
  navigate,
  newChat,
  openChat,
  switchKb,
  useApp,
  type View,
} from "@/lib/store"

const NAV: { view: View; label: string; icon: typeof MessageSquareIcon }[] = [
  { view: "chat", label: "Chat", icon: MessageSquareIcon },
  { view: "library", label: "Library", icon: LibraryIcon },
  { view: "settings", label: "Settings", icon: Settings2Icon },
]

export function AppSidebar() {
  const { setOpenMobile, isMobile } = useSidebar()
  const view = useApp((s) => s.view)
  const version = useApp((s) => s.version)
  const kbs = useApp((s) => s.kbs)
  const kb = useApp((s) => s.kb)
  const chatId = useApp((s) => s.chatId)
  const chats = useApp(useShallow(kbChats))
  const theme = useApp((s) => s.theme)
  const close = () => isMobile && setOpenMobile(false)
  const ThemeIcon = theme === "dark" ? MoonIcon : theme === "light" ? SunIcon : MonitorIcon

  return (
    <Sidebar collapsible="offcanvas" aria-label="Workspace">
      <SidebarHeader className="gap-3 px-3 pt-3">
        <div className="flex items-center gap-2 px-1">
          <Logo className="size-6" />
          <span className="text-[0.95rem] font-semibold tracking-tight">OmniRAG</span>
          {version && <span className="text-xs text-muted-foreground tabular-nums">v{version}</span>}
        </div>
        <Button
          variant="outline"
          className="h-9 w-full justify-start gap-2 bg-background px-2.5 font-normal text-muted-foreground shadow-xs dark:bg-input/30"
          onClick={() => {
            close()
            useApp.setState({ palette: { open: true, mode: "all" } })
          }}
          aria-haspopup="dialog"
        >
          <SearchIcon className="size-4" />
          <span className="flex-1 text-left">Search or jump to…</span>
          <Kbd className="max-md:hidden">{MOD_KEY} K</Kbd>
        </Button>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  onClick={() => {
                    close()
                    newChat()
                  }}
                >
                  <SquarePenIcon />
                  <span>New chat</span>
                </SidebarMenuButton>
                <SidebarMenuBadge className="max-md:hidden">
                  <Kbd className="bg-transparent">N</Kbd>
                </SidebarMenuBadge>
              </SidebarMenuItem>
              {NAV.map(({ view: v, label, icon: Icon }) => (
                <SidebarMenuItem key={v}>
                  <SidebarMenuButton asChild isActive={view === v}>
                    <a href={`#/${v}`} aria-current={view === v ? "page" : undefined} onClick={close}>
                      <Icon />
                      <span>{label}</span>
                    </a>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>Knowledge bases</SidebarGroupLabel>
          <SidebarGroupAction
            title="New knowledge base"
            aria-label="New knowledge base"
            onClick={() => {
              close()
              useApp.setState({ kbDialogOpen: true })
            }}
          >
            <PlusIcon />
          </SidebarGroupAction>
          <SidebarGroupContent>
            <SidebarMenu aria-live="polite">
              {kbs === null &&
                Array.from({ length: 2 }, (_, i) => (
                  <SidebarMenuItem key={i}>
                    <SidebarMenuSkeleton showIcon />
                  </SidebarMenuItem>
                ))}
              {kbs?.length === 0 && <p className="px-2 py-1.5 text-xs text-muted-foreground">No knowledge bases yet</p>}
              {kbs?.map((k) => (
                <SidebarMenuItem key={k.name}>
                  <SidebarMenuButton
                    isActive={k.name === kb}
                    aria-current={k.name === kb ? "true" : undefined}
                    title={k.description || k.name}
                    onClick={() => {
                      close()
                      void switchKb(k.name)
                    }}
                  >
                    <DatabaseIcon />
                    <span>{k.name}</span>
                  </SidebarMenuButton>
                  <SidebarMenuBadge aria-label={plural(k.documents, "document")} className="max-md:hidden group-focus-within/menu-item:opacity-0 group-hover/menu-item:opacity-0">
                    {k.documents}
                  </SidebarMenuBadge>
                  <SidebarMenuAction
                    showOnHover
                    aria-label={`Delete knowledge base ${k.name}`}
                    title="Delete"
                    className="hover:text-destructive"
                    onClick={() => void deleteKb(k.name)}
                  >
                    <Trash2Icon />
                  </SidebarMenuAction>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup className="min-h-0">
          <SidebarGroupLabel>Recent</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {kb && chats.length === 0 && (
                <p className="px-2 py-1.5 text-xs text-muted-foreground">No conversations yet</p>
              )}
              {chats.map((c) => (
                <SidebarMenuItem key={c.id}>
                  <SidebarMenuButton
                    isActive={c.id === chatId && view === "chat"}
                    aria-current={c.id === chatId ? "true" : undefined}
                    onClick={() => {
                      close()
                      openChat(c.id)
                    }}
                    title={c.title}
                  >
                    <span>{c.title}</span>
                  </SidebarMenuButton>
                  <SidebarMenuAction
                    showOnHover
                    aria-label={`Delete conversation ${c.title}`}
                    title="Delete"
                    className="hover:text-destructive"
                    onClick={() => deleteChat(c.id)}
                  >
                    <Trash2Icon />
                  </SidebarMenuAction>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="flex-row items-center gap-1 border-t border-sidebar-border p-2">
        <StatusPill
          onClick={() => {
            close()
            navigate("settings")
          }}
        />
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Keyboard shortcuts"
              onClick={() => useApp.setState({ shortcutsOpen: true })}
            >
              <KeyboardIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            Keyboard shortcuts <Kbd>?</Kbd>
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={`Theme: ${theme}. Change theme`} onClick={cycleTheme}>
              <ThemeIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Theme: {theme}</TooltipContent>
        </Tooltip>
      </SidebarFooter>
    </Sidebar>
  )
}

function StatusPill({ onClick }: { onClick: () => void }) {
  const status = useApp((s) => s.status)
  const error = useApp((s) => s.statusError)
  let state: "ok" | "down" | "offline" | "unknown" = "unknown"
  let label = "Checking…"
  if (error && !status) {
    state = "down"
    label = "Server unreachable"
  } else if (status) {
    const llm = status.llm
    if (llm.backend === "none") {
      state = "offline"
      label = "Extractive · offline"
    } else if (llm.reachable) {
      state = "ok"
      label = `${llm.backend === "openai" ? "OpenAI-compatible" : "Ollama"} · ${llm.model}`
    } else {
      state = "down"
      label = `${llm.backend === "openai" ? "Endpoint" : "Ollama"} unreachable`
    }
  }
  return (
    <Button
      variant="ghost"
      size="sm"
      className="min-w-0 flex-1 justify-start gap-2 px-2 font-normal text-muted-foreground"
      onClick={onClick}
      title={status ? `${label}${status.llm.detail ? ` — ${status.llm.detail}` : ""}` : label}
    >
      <StatusDot state={state} />
      <span className="truncate">{label}</span>
    </Button>
  )
}
