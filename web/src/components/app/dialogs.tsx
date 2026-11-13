import * as React from "react"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Kbd, KbdGroup } from "@/components/ui/kbd"
import { Spinner } from "@/components/ui/spinner"
import { verifyKey } from "@/lib/api"
import { MOD_KEY } from "@/lib/format"
import { apiKeyAccepted, createKb, resolveConfirm, useApp } from "@/lib/store"

const KB_NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/

export function CreateKbDialog() {
  const open = useApp((s) => s.kbDialogOpen)
  const [name, setName] = React.useState("")
  const [description, setDescription] = React.useState("")
  const [error, setError] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const setOpen = (o: boolean) => {
    useApp.setState({ kbDialogOpen: o })
    if (!o) {
      setName("")
      setDescription("")
      setError("")
    }
  }
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const n = name.trim()
    if (!KB_NAME.test(n)) {
      setError("Use 1–64 letters, digits, dots, dashes or underscores, starting with a letter or digit.")
      document.getElementById("kb-name")?.focus()
      return
    }
    setBusy(true)
    try {
      await createKb(n, description.trim())
      setOpen(false)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} noValidate className="flex flex-col gap-5">
          <DialogHeader>
            <DialogTitle>New knowledge base</DialogTitle>
            <DialogDescription>A separate index with its own documents, settings and chat history.</DialogDescription>
          </DialogHeader>
          <FieldGroup>
            <Field data-invalid={error ? true : undefined}>
              <FieldLabel htmlFor="kb-name">Name</FieldLabel>
              <Input
                id="kb-name"
                autoFocus
                autoComplete="off"
                spellCheck={false}
                maxLength={64}
                placeholder="team-docs"
                aria-invalid={error ? true : undefined}
                aria-describedby="kb-name-help"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <FieldDescription id="kb-name-help">Letters, digits, dot, dash and underscore.</FieldDescription>
              {error && <FieldError>{error}</FieldError>}
            </Field>
            <Field>
              <FieldLabel htmlFor="kb-desc">
                Description <span className="font-normal text-muted-foreground">(optional)</span>
              </FieldLabel>
              <Input id="kb-desc" autoComplete="off" maxLength={200} value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
          </FieldGroup>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="ghost">
                Cancel
              </Button>
            </DialogClose>
            <Button type="submit" disabled={busy}>
              {busy && <Spinner />}
              Create
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export function ConfirmDialog() {
  const confirm = useApp((s) => s.confirm)
  return (
    <AlertDialog open={Boolean(confirm)} onOpenChange={(o) => !o && resolveConfirm(false)}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{confirm?.title}</AlertDialogTitle>
          <AlertDialogDescription>{confirm?.body}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={() => resolveConfirm(false)}>Cancel</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={() => resolveConfirm(true)}>
            {confirm?.ok}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

export function ApiKeyDialog() {
  const { open, invalid } = useApp((s) => s.keyDialog)
  return (
    <Dialog open={open}>
      <DialogContent
        showCloseButton={false}
        className="sm:max-w-md"
        onEscapeKeyDown={(e) => e.preventDefault()}
        onPointerDownOutside={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
      >
        {/* Mounted only while open, so every prompt starts empty. */}
        <ApiKeyForm invalid={invalid} />
      </DialogContent>
    </Dialog>
  )
}

function ApiKeyForm({ invalid }: { invalid: boolean }) {
  const [key, setKey] = React.useState("")
  const [error, setError] = React.useState(invalid ? "That key was not accepted." : "")
  const [busy, setBusy] = React.useState(false)
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const k = key.trim()
    if (!k) return setError("Enter the API key.")
    setBusy(true)
    const result = await verifyKey(k)
    setBusy(false)
    if (result === "ok") apiKeyAccepted(k)
    else setError(result === "rejected" ? "That key was not accepted." : "Could not reach the server.")
  }
  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-5">
      <DialogHeader>
        <DialogTitle>API key required</DialogTitle>
        <DialogDescription>
          This OmniRAG server is protected. Enter the key set in <code className="font-mono">OMNIRAG_API_KEY</code>; it is
          kept in this browser only.
        </DialogDescription>
      </DialogHeader>
      <Field data-invalid={error ? true : undefined}>
        <FieldLabel htmlFor="api-key">API key</FieldLabel>
        <Input
          id="api-key"
          type="password"
          autoComplete="off"
          spellCheck={false}
          autoFocus
          aria-invalid={error ? true : undefined}
          value={key}
          onChange={(e) => setKey(e.target.value)}
        />
        {error && <FieldError role="alert">{error}</FieldError>}
      </Field>
      <DialogFooter>
        <Button type="submit" disabled={busy}>
          {busy && <Spinner />}
          Continue
        </Button>
      </DialogFooter>
    </form>
  )
}

const SHORTCUTS: [string[], string][] = [
  [[MOD_KEY, "K"], "Open the command palette"],
  [["/"], "Focus the question box"],
  [["N"], "New chat"],
  [["S"], "Choose sources (scope the chat)"],
  [["G", "then", "C"], "Go to Chat"],
  [["G", "then", "L"], "Go to Library"],
  [["G", "then", "S"], "Go to Settings"],
  [["Enter"], "Send the question"],
  [["Shift", "Enter"], "New line in the question"],
  [["←", "→"], "Switch answer tabs (when a tab is focused)"],
  [[MOD_KEY, "B"], "Show or hide the sidebar"],
  [["Esc"], "Stop generating, close panels and menus"],
  [["?"], "Show these shortcuts"],
]

export function ShortcutsDialog() {
  const open = useApp((s) => s.shortcutsOpen)
  return (
    <Dialog open={open} onOpenChange={(o) => useApp.setState({ shortcutsOpen: o })}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Single-key shortcuts work when you are not typing in a field.</DialogDescription>
        </DialogHeader>
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
          {SHORTCUTS.map(([keys, label]) => (
            <div key={label} className="contents">
              <dt>
                <KbdGroup>
                  {keys.map((k, i) =>
                    k === "then" ? (
                      <span key={i} className="text-xs text-muted-foreground">
                        then
                      </span>
                    ) : (
                      <Kbd key={i}>{k}</Kbd>
                    ),
                  )}
                </KbdGroup>
              </dt>
              <dd className="mb-1 text-muted-foreground sm:mb-0">{label}</dd>
            </div>
          ))}
        </dl>
        <DialogFooter>
          <DialogClose asChild>
            <Button>Done</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
