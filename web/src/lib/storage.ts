/** localStorage that never throws (private mode, blocked storage, full quota). */
export const storage = {
  get<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem(key)
      return raw === null ? fallback : (JSON.parse(raw) as T)
    } catch {
      return fallback
    }
  },
  set(key: string, value: unknown): boolean {
    try {
      localStorage.setItem(key, JSON.stringify(value))
      return true
    } catch {
      return false
    }
  },
  remove(key: string): void {
    try {
      localStorage.removeItem(key)
    } catch {
      /* storage unavailable */
    }
  },
}

/** Keys are shared with the 0.2 web app, so existing history and settings carry over. */
export const KEYS = {
  apiKey: "omnirag.apiKey",
  theme: "omnirag.theme",
  kb: "omnirag.kb",
  chats: "omnirag.chats.v1",
  scope: (kb: string) => `omnirag.scope.${kb}`,
}
