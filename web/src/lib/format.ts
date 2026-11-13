export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n} ${n === 1 ? word : many}`
}

export function formatBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—"
  if (n < 1024) return `${n} B`
  const units = ["KB", "MB", "GB"]
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return ""
  return ms < 1000 ? `${Math.max(0.01, ms / 1000).toFixed(2)}s` : `${(ms / 1000).toFixed(1)}s`
}

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" })

export function relativeTime(iso: string | null | undefined): string {
  const t = Date.parse(iso ?? "")
  if (Number.isNaN(t)) return "—"
  let v = (t - Date.now()) / 1000
  const steps: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
    [4.35, "week"],
    [12, "month"],
    [Infinity, "year"],
  ]
  for (const [size, unit] of steps) {
    if (Math.abs(v) < size) return rtf.format(Math.round(v), unit)
    v /= size
  }
  return "—"
}

export function exactTime(iso: string | null | undefined): string {
  const t = Date.parse(iso ?? "")
  return Number.isNaN(t) ? "" : new Date(t).toLocaleString()
}

export const IS_MAC =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
export const MOD_KEY = IS_MAC ? "⌘" : "Ctrl"
