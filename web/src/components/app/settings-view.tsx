import * as React from "react"
import { KeyRoundIcon, MonitorIcon, MoonIcon, RefreshCwIcon, SunIcon, Trash2Icon } from "lucide-react"
import { toast } from "sonner"

import { StatusDot } from "@/components/app/status"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Field, FieldDescription, FieldError, FieldGroup, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Skeleton } from "@/components/ui/skeleton"
import { Spinner } from "@/components/ui/spinner"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { api } from "@/lib/api"
import { KEYS, storage } from "@/lib/storage"
import { deleteKb, forgetApiKey, loadStatus, setTheme, useApp, type Theme } from "@/lib/store"
import type { Preferences, ServerStatus } from "@/lib/types"
import { cn } from "@/lib/utils"

const BACKENDS: { value: Preferences["llm"]; label: string; help: (s: ServerStatus | null) => string }[] = [
  {
    value: "",
    label: "Server default",
    help: (s) => `Uses the server's OMNIRAG_LLM setting${s ? ` (currently “${s.defaults.llm}”)` : ""}.`,
  },
  {
    value: "none",
    label: "None (offline)",
    help: () => "Answers are assembled from the most relevant source sentences. No model server needed.",
  },
  {
    value: "ollama",
    label: "Ollama",
    help: () => "A local Ollama server writes the answer. Leave the fields empty to use OLLAMA_HOST and OMNIRAG_OLLAMA_MODEL.",
  },
  {
    value: "openai",
    label: "OpenAI-compatible",
    help: () =>
      "Any /chat/completions endpoint (OpenAI, vLLM, LM Studio, llama.cpp server). The key comes from OPENAI_API_KEY on the server.",
  },
]

export function SettingsView() {
  const kb = useApp((s) => s.kb)
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8">
        {kb && <AnsweringCard key={kb} kb={kb} />}
        <StatusCard />
        <AppearanceCard />
        {kb && (
          <Card className="border-destructive/30">
            <CardHeader>
              <CardTitle>Delete knowledge base</CardTitle>
              <CardDescription>
                Removes the index, uploads and settings of <strong className="text-foreground">{kb}</strong>. Files ingested
                from server paths are not touched.
              </CardDescription>
            </CardHeader>
            <CardFooter>
              <Button variant="destructive" onClick={() => void deleteKb(kb)}>
                <Trash2Icon />
                Delete knowledge base
              </Button>
            </CardFooter>
          </Card>
        )}
      </div>
    </div>
  )
}

function AnsweringCard({ kb }: { kb: string }) {
  const status = useApp((s) => s.status)
  const [prefs, setPrefs] = React.useState<Preferences | null>(null)
  const [error, setError] = React.useState("")
  const [topKError, setTopKError] = React.useState("")
  const [saving, setSaving] = React.useState(false)
  React.useEffect(() => {
    let live = true
    api.settings(kb).then(
      (p) => live && setPrefs(p),
      (err: Error) => live && setError(err.message),
    )
    return () => {
      live = false
    }
  }, [kb])

  const backend = prefs?.llm ?? ""
  const needsModel = backend === "ollama" || backend === "openai"
  const defaults = needsModel && status ? status.defaults[backend] : null
  const models = status?.llm.backend === backend ? status.llm.models : []
  const help = BACKENDS.find((b) => b.value === backend)?.help(status) ?? ""

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!prefs) return
    const topK = Number(prefs.top_k)
    if (!Number.isInteger(topK) || topK < 1 || topK > 50) {
      setTopKError("Top-k must be a whole number from 1 to 50.")
      document.getElementById("top-k")?.focus()
      return
    }
    setTopKError("")
    setSaving(true)
    try {
      await api.saveSettings(kb, {
        llm: prefs.llm,
        model: needsModel ? prefs.model.trim() : "",
        base_url: needsModel ? prefs.base_url.trim() : "",
        top_k: topK,
      })
      toast.success("Settings saved", { description: "Checking the model endpoint…" })
      await loadStatus()
    } catch (err) {
      toast.error((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Answering</CardTitle>
        <CardDescription>
          Saved for <strong className="text-foreground">{kb}</strong>. API keys stay in the server environment.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : !prefs ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-20" />
            <Skeleton className="h-9" />
            <Skeleton className="h-9 w-40" />
          </div>
        ) : (
          <form id="settings-form" onSubmit={save} noValidate>
            <FieldGroup>
              <FieldSet>
                <FieldLegend variant="label">LLM backend</FieldLegend>
                <RadioGroup
                  value={backend || "default"}
                  onValueChange={(v) => setPrefs({ ...prefs, llm: (v === "default" ? "" : v) as Preferences["llm"] })}
                  className="grid gap-2 sm:grid-cols-2"
                >
                  {BACKENDS.map((b) => (
                    <label
                      key={b.label}
                      className={cn(
                        "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors hover:bg-muted/50",
                        (b.value || "default") === (backend || "default") && "border-brand/50 bg-brand-soft/50",
                      )}
                    >
                      <RadioGroupItem value={b.value || "default"} />
                      {b.label}
                    </label>
                  ))}
                </RadioGroup>
                <FieldDescription>{help}</FieldDescription>
              </FieldSet>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field data-disabled={!needsModel || undefined}>
                  <FieldLabel htmlFor="llm-model">Model</FieldLabel>
                  <Input
                    id="llm-model"
                    list="model-options"
                    spellCheck={false}
                    disabled={!needsModel}
                    placeholder={defaults ? defaults.model : "not used"}
                    value={needsModel ? prefs.model : ""}
                    onChange={(e) => setPrefs({ ...prefs, model: e.target.value })}
                  />
                  <datalist id="model-options">
                    {models.map((m) => (
                      <option key={m} value={m} />
                    ))}
                  </datalist>
                </Field>
                <Field data-disabled={!needsModel || undefined}>
                  <FieldLabel htmlFor="llm-url">Base URL</FieldLabel>
                  <Input
                    id="llm-url"
                    type="url"
                    spellCheck={false}
                    disabled={!needsModel}
                    placeholder={defaults ? defaults.base_url : "not used"}
                    value={needsModel ? prefs.base_url : ""}
                    onChange={(e) => setPrefs({ ...prefs, base_url: e.target.value })}
                  />
                </Field>
              </div>
              <Field className="max-w-48" data-invalid={topKError ? true : undefined}>
                <FieldLabel htmlFor="top-k">Sources per answer (top-k)</FieldLabel>
                <Input
                  id="top-k"
                  type="number"
                  min={1}
                  max={50}
                  step={1}
                  required
                  aria-invalid={topKError ? true : undefined}
                  value={prefs.top_k}
                  onChange={(e) => setPrefs({ ...prefs, top_k: e.target.value === "" ? ("" as unknown as number) : Number(e.target.value) })}
                />
                {topKError && <FieldError>{topKError}</FieldError>}
              </Field>
            </FieldGroup>
          </form>
        )}
      </CardContent>
      {prefs && (
        <CardFooter className="border-t">
          <Button type="submit" form="settings-form" disabled={saving}>
            {saving && <Spinner />}
            Save settings
          </Button>
        </CardFooter>
      )}
    </Card>
  )
}

function StatusCard() {
  const status = useApp((s) => s.status)
  const error = useApp((s) => s.statusError)
  const loading = useApp((s) => s.statusLoading)
  const llm = status?.llm
  const llmLabel = !llm || llm.backend === "none" ? "Extractive (offline)" : `${llm.backend === "openai" ? "OpenAI-compatible" : "Ollama"} · ${llm.model}`
  return (
    <Card>
      <CardHeader>
        <CardTitle>Status</CardTitle>
        <CardDescription>The embedder in use and whether the model endpoint answers.</CardDescription>
        <CardAction>
          <Button variant="outline" size="sm" disabled={loading} onClick={() => void loadStatus()}>
            <RefreshCwIcon className={cn(loading && "animate-spin")} />
            Check again
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {!status && !error ? (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-5 w-1/2" />
            <Skeleton className="h-5 w-3/5" />
          </div>
        ) : !status ? (
          <p className="flex items-center gap-2 text-sm">
            <StatusDot state="down" />
            {error}
          </p>
        ) : (
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-[10rem_1fr]">
            <dt className="text-muted-foreground">Answer backend</dt>
            <dd className="flex flex-wrap items-center gap-2">
              {llmLabel}
              <Badge variant="secondary">{llm?.source === "kb" ? "this knowledge base" : "server default"}</Badge>
            </dd>
            {llm && llm.backend !== "none" && (
              <>
                <dt className="text-muted-foreground">Endpoint</dt>
                <dd className="font-mono text-xs break-all">{llm.base_url}</dd>
              </>
            )}
            <dt className="text-muted-foreground">Reachability</dt>
            <dd className="flex items-start gap-2">
              {llm?.backend === "none" ? (
                <>
                  <StatusDot state="offline" className="mt-1.5" />
                  Not needed: answers are extractive
                </>
              ) : llm?.reachable ? (
                <>
                  <StatusDot state="ok" className="mt-1.5" />
                  Reachable{llm.latency_ms != null ? ` · ${Math.round(llm.latency_ms)} ms` : ""}
                  {llm.detail ? ` · ${llm.detail}` : ""}
                </>
              ) : (
                <>
                  <StatusDot state="down" className="mt-1.5" />
                  <span>
                    Not reachable
                    {llm?.detail && <span className="block font-mono text-xs break-all text-muted-foreground">{llm.detail}</span>}
                  </span>
                </>
              )}
            </dd>
            <dt className="text-muted-foreground">Embedder</dt>
            <dd className="flex flex-wrap items-center gap-2">
              {status.embedder ? (
                <>
                  <span className="font-mono text-xs">{status.embedder.spec}</span>
                  {status.embedder.dimension ? <Badge variant="secondary">{status.embedder.dimension} dims</Badge> : null}
                  {status.embedder.offline && <Badge variant="secondary">offline</Badge>}
                </>
              ) : (
                "—"
              )}
            </dd>
            <dt className="text-muted-foreground">Server</dt>
            <dd>
              OmniRAG {status.version} · {status.auth_required ? "API key required" : "no API key"} · uploads up to{" "}
              {status.max_upload_mb} MB
            </dd>
          </dl>
        )}
      </CardContent>
    </Card>
  )
}

function AppearanceCard() {
  const theme = useApp((s) => s.theme)
  const authRequired = useApp((s) => s.health?.auth_required ?? s.status?.auth_required ?? false)
  const key = storage.get<string>(KEYS.apiKey, "")
  return (
    <Card>
      <CardHeader>
        <CardTitle>Appearance</CardTitle>
        <CardDescription>System follows your operating system's light or dark setting.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <ToggleGroup
          type="single"
          variant="outline"
          value={theme}
          onValueChange={(v) => v && setTheme(v as Theme)}
          aria-label="Theme"
        >
          <ToggleGroupItem value="system" className="px-3">
            <MonitorIcon />
            System
          </ToggleGroupItem>
          <ToggleGroupItem value="light" className="px-3">
            <SunIcon />
            Light
          </ToggleGroupItem>
          <ToggleGroupItem value="dark" className="px-3">
            <MoonIcon />
            Dark
          </ToggleGroupItem>
        </ToggleGroup>
        {authRequired && (
          <div className="flex flex-col gap-3 rounded-lg border p-3 text-sm sm:flex-row sm:items-center">
            <KeyRoundIcon className="size-4 text-muted-foreground" />
            <p className="flex-1">
              This server requires an API key.{key ? ` Using a key ending in ${key.slice(-4)}.` : ""}
            </p>
            <Button variant="outline" size="sm" onClick={forgetApiKey}>
              Forget key
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
