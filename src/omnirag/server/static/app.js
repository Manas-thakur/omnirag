// OmniRAG web app. Plain ES module, no build step.
import { escapeHtml as esc, renderMarkdown } from "./markdown.js";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const MODALITIES = ["text", "code", "table", "image", "audio"];
const MODALITY_LABEL = { text: "Text", code: "Code", table: "Tables", image: "Images", audio: "Audio" };
const VIEWS = { chat: "Chat", library: "Library", settings: "Settings" };
const CHATS_KEY = "omnirag.chats.v1";
const MAX_CHATS = 40;
const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const MOD = IS_MAC ? "⌘" : "Ctrl";
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const finePointer = () => window.matchMedia("(hover: hover) and (pointer: fine)").matches;

// ------------------------------------------------------------------ storage
const store = {
  get(key, fallback = null) {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch {
      return fallback;
    }
  },
  set(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch {
      return false;
    }
  },
  remove(key) {
    try {
      localStorage.removeItem(key);
    } catch {
      /* storage unavailable */
    }
  },
};

const state = {
  defaultKb: $('meta[name="omnirag-default-kb"]').content,
  version: $('meta[name="omnirag-version"]').content,
  health: null,
  kbs: null, // null = loading
  kb: null,
  stats: null,
  docs: null,
  docsKb: null,
  docsError: null,
  status: null,
  view: "chat",
  chats: store.get(CHATS_KEY, []),
  chatId: null,
  filters: new Set(), // modality filters
  scope: new Set(), // selected document ids (NotebookLM-style grounding)
  controller: null,
  drawer: null, // null | {mode: "scope"} | {mode: "preview", chatId, index, n} | {mode: "doc", docId}
  starters: null,
};

// ---------------------------------------------------------------------- api
class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function detailText(detail) {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  return JSON.stringify(detail);
}

function authHeaders() {
  const key = store.get("omnirag.apiKey", "");
  return key ? { "X-API-Key": key } : {};
}

async function api(path, { method = "GET", body, signal, raw = false } = {}, retried = false) {
  const headers = { ...authHeaders() };
  let payload = body;
  if (body !== undefined && !(body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(path, { method, headers, body: payload, signal });
  if (res.status === 401 && !retried) {
    await requestApiKey(true);
    return api(path, { method, body, signal, raw }, true);
  }
  if (raw && res.ok) return res;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(detailText(data.detail) || `${res.status} ${res.statusText}`, res.status);
  return data;
}

const kbPath = (name = state.kb) => `/api/kbs/${encodeURIComponent(name)}`;

// ------------------------------------------------------------------ helpers
function icon(name, cls = "") {
  return `<svg aria-hidden="true"${cls ? ` class="${cls}"` : ""}><use href="#i-${name}"/></svg>`;
}
const mIcon = (m) => icon(`m-${MODALITIES.includes(m) ? m : "text"}`, "m-icon");

function formatBytes(n) {
  if (n === null || n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

function formatMs(ms) {
  if (ms === null || ms === undefined) return "";
  return ms < 1000 ? `${Math.max(0.01, ms / 1000).toFixed(2)}s` : `${(ms / 1000).toFixed(1)}s`;
}

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
function relativeTime(iso) {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  let v = (t - Date.now()) / 1000;
  for (const [size, unit] of [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
    [4.35, "week"],
    [12, "month"],
    [Infinity, "year"],
  ]) {
    if (Math.abs(v) < size) return rtf.format(Math.round(v), unit);
    v /= size;
  }
  return "—";
}

function exactTime(iso) {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? "" : new Date(t).toLocaleString();
}

function plural(n, word, many = `${word}s`) {
  return `${n} ${n === 1 ? word : many}`;
}

function baseName(path) {
  return String(path || "").split(/[\\/]/).filter(Boolean).pop() || String(path || "");
}

/** Short display name for a source: its file name. */
const shortName = (s) => baseName(s.metadata?.path || s.source) || s.title || `Source ${s.index}`;

/** Short, human location inside the source (section, lines, rows, timestamp). */
function shortLoc(s) {
  const m = s.metadata || {};
  if (s.modality === "code" && m.line_start) return `${m.symbol ? `${m.symbol} · ` : ""}L${m.line_start}–${m.line_end}`;
  if (s.modality === "code" && m.symbol) return m.symbol;
  if (s.modality === "text" && m.section) return m.section === m.title ? "Introduction" : m.section;
  if (s.modality === "table" && m.row_start) return `Rows ${m.row_start}–${m.row_end}`;
  if (s.modality === "table") return "Columns & summary";
  if (s.modality === "audio" && m.timestamp) return String(m.timestamp).replace("-", "–");
  if (s.modality === "image") return "Image";
  return s.location || "";
}

/** Chunk text without the leading heading breadcrumb that chunking adds. */
function excerptOf(s, max = 260) {
  let text = String(s.content || "");
  const crumb = s.metadata?.heading;
  if (crumb && text.startsWith(crumb)) text = text.slice(crumb.length);
  text = text.replace(/```[\w+#.-]*\n?/g, "").replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text;
}

function announce(text) {
  const el = $("#announcer");
  el.textContent = "";
  requestAnimationFrame(() => (el.textContent = text));
}

let toastTimer = null;
function toast(message, { error = false, action = null } = {}) {
  const el = $("#toast");
  el.className = `toast${error ? " error" : ""}`;
  el.innerHTML = `<span>${esc(message)}</span>`;
  if (action) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-ghost";
    btn.textContent = action.label;
    btn.addEventListener("click", () => {
      el.hidden = true;
      action.run();
    });
    el.append(btn);
  }
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), error ? 6000 : 3200);
}

function openDialog(dialog) {
  if (!dialog.open) dialog.showModal();
}

function confirmAction({ title, body, ok = "Delete" }) {
  const dialog = $("#confirm-dialog");
  $("#confirm-title").textContent = title;
  $("#confirm-body").textContent = body;
  $("#confirm-ok").textContent = ok;
  dialog.returnValue = "";
  openDialog(dialog);
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
  });
}

// ------------------------------------------------------------------- auth
let keyPromise = null;
function requestApiKey(invalid = false) {
  if (keyPromise) return keyPromise;
  const dialog = $("#key-dialog");
  const input = $("#api-key");
  const error = $("#key-error");
  error.textContent = invalid && store.get("omnirag.apiKey") ? "That key was not accepted." : "";
  input.value = "";
  keyPromise = new Promise((resolve) => {
    const form = $("#key-form");
    const onSubmit = async (event) => {
      event.preventDefault();
      const key = input.value.trim();
      if (!key) {
        error.textContent = "Enter the API key.";
        input.focus();
        return;
      }
      const res = await fetch("/api/kbs", { headers: { "X-API-Key": key } }).catch(() => null);
      if (!res || res.status === 401) {
        error.textContent = res ? "That key was not accepted." : "Could not reach the server.";
        input.select();
        return;
      }
      store.set("omnirag.apiKey", key);
      form.removeEventListener("submit", onSubmit);
      dialog.close();
      keyPromise = null;
      renderKeyRow();
      resolve();
    };
    form.addEventListener("submit", onSubmit);
    dialog.addEventListener("cancel", (e) => e.preventDefault()); // a key is required
    openDialog(dialog);
    input.focus();
  });
  return keyPromise;
}

function renderKeyRow() {
  const row = $("#key-row");
  row.hidden = !state.health?.auth_required;
  const key = store.get("omnirag.apiKey", "");
  $("#key-hint").textContent = key ? `Using a key ending in ${key.slice(-4)}.` : "";
}

// ------------------------------------------------------------------ theme
const THEMES = ["system", "light", "dark"];
const currentTheme = () => store.get("omnirag.theme", "system");
function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  const btn = $("#theme-toggle");
  btn.innerHTML = icon(theme === "light" ? "sun" : theme === "dark" ? "moon" : "auto");
  btn.setAttribute("aria-label", `Theme: ${theme}. Change theme`);
  btn.title = `Theme: ${theme}`;
  const radio = $(`#theme-choice input[value="${theme}"]`);
  if (radio) radio.checked = true;
}
function setTheme(theme) {
  store.set("omnirag.theme", theme);
  applyTheme(theme);
}
function cycleTheme() {
  const next = THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length];
  setTheme(next);
  toast(`Theme: ${next}`);
}

// ------------------------------------------------------------------ chats
function saveChats() {
  state.chats.sort((a, b) => b.updated - a.updated);
  state.chats = state.chats.slice(0, MAX_CHATS);
  while (!store.set(CHATS_KEY, state.chats) && state.chats.length > 1) state.chats.pop();
}

function slimSource(s) {
  return {
    index: s.index,
    chunk_id: s.chunk_id,
    doc_id: s.doc_id,
    source: s.source,
    title: s.title,
    modality: s.modality,
    score: s.score,
    content: s.content,
    location: s.location,
    label: s.label,
    metadata: s.metadata,
    retrieval: s.retrieval,
  };
}

const currentChat = () => state.chats.find((c) => c.id === state.chatId) || null;
const kbChats = () => state.chats.filter((c) => c.kb === state.kb).sort((a, b) => b.updated - a.updated);

function newChat() {
  stopStreaming();
  state.chatId = null;
  if (state.drawer?.mode === "preview") closeDrawer();
  renderChatList();
  if (state.view !== "chat") location.hash = "#/chat";
  else renderThread();
  $("#question").focus();
}

function openChat(id) {
  stopStreaming();
  state.chatId = id;
  if (state.drawer?.mode === "preview") closeDrawer();
  renderChatList();
  if (state.view !== "chat") location.hash = "#/chat";
  renderThread(true);
}

function deleteChat(id) {
  const chat = state.chats.find((c) => c.id === id);
  if (!chat) return;
  state.chats = state.chats.filter((c) => c.id !== id);
  saveChats();
  if (state.chatId === id) newChat();
  renderChatList();
  toast("Conversation deleted", {
    action: {
      label: "Undo",
      run: () => {
        state.chats.push(chat);
        saveChats();
        renderChatList();
      },
    },
  });
}

function renderChatList() {
  const list = $("#chat-list");
  if (!state.kb) {
    list.innerHTML = "";
    return;
  }
  const chats = kbChats();
  if (!chats.length) {
    list.innerHTML = `<li class="side-empty">No conversations yet</li>`;
    return;
  }
  list.innerHTML = chats
    .map(
      (c) => `<li class="side-item" ${c.id === state.chatId ? 'aria-current="true"' : ""}>
        <button type="button" data-open-chat="${esc(c.id)}"><span class="label">${esc(c.title)}</span></button>
        <button class="icon-btn sm danger" type="button" data-delete-chat="${esc(c.id)}" aria-label="Delete conversation ${esc(c.title)}">${icon("trash")}</button>
      </li>`,
    )
    .join("");
}

// ------------------------------------------------------------------- scope
const scopeKey = (kb = state.kb) => `omnirag.scope.${kb}`;

function loadScope() {
  state.scope = new Set(state.kb ? store.get(scopeKey(), []) : []);
}

function saveScope() {
  if (state.kb) store.set(scopeKey(), [...state.scope]);
}

/** Drop ids of documents that no longer exist. */
function pruneScope() {
  if (!state.docs || state.docsKb !== state.kb) return;
  const ids = new Set(state.docs.map((d) => d.doc_id));
  let changed = false;
  for (const id of state.scope) {
    if (!ids.has(id)) {
      state.scope.delete(id);
      changed = true;
    }
  }
  if (changed) saveScope();
}

function scopedDocs() {
  return (state.docs || []).filter((d) => state.scope.has(d.doc_id));
}

function setScope(ids, { quiet = false } = {}) {
  state.scope = new Set(ids);
  saveScope();
  renderScopeUi();
  if (!quiet) announce(state.scope.size ? `Scoped to ${plural(state.scope.size, "source")}` : "Using all sources");
}

function toggleScope(id, on = !state.scope.has(id)) {
  if (on) state.scope.add(id);
  else state.scope.delete(id);
  saveScope();
  renderScopeUi();
}

function clearScope() {
  setScope([]);
}

function renderScopeUi() {
  // Re-rendering replaces the checkboxes; put keyboard focus back where it was.
  const a = document.activeElement;
  const sel = a?.dataset?.scopeDoc
    ? `[data-scope-doc="${CSS.escape(a.dataset.scopeDoc)}"]`
    : a?.dataset?.scopeToggle
      ? `[data-scope-toggle="${CSS.escape(a.dataset.scopeToggle)}"]`
      : a?.id
        ? `#${CSS.escape(a.id)}`
        : null;
  const root = a?.closest?.("#drawer") ? "#drawer" : a?.closest?.("#view-library") ? "#view-library" : null;
  renderComposerContext();
  renderTopbar();
  if (state.view === "library") renderDocs();
  if (state.drawer?.mode === "scope") renderScopePanel();
  if (state.drawer?.mode === "doc") renderDocPanel();
  if (state.view === "chat" && !currentChat()?.messages.length) renderEmptyThread();
  if (sel && root && !a.isConnected) $(`${root} ${sel}`)?.focus();
}

function renderComposerContext() {
  const box = $("#composer-context");
  const n = state.scope.size;
  if (!n) {
    box.innerHTML = "";
    return;
  }
  const docs = scopedDocs();
  const names = docs.slice(0, 3).map((d) => d.name).join(", ") + (docs.length > 3 ? ", …" : "");
  box.innerHTML = `<div class="scope-chip">
    <button type="button" class="scope-chip-main" data-action="open-scope" title="${esc(names)}">${icon("layers")}<span>Scoped to ${plural(n, "source")}</span></button>
    <button type="button" class="scope-chip-x" data-action="clear-scope" aria-label="Clear source scope (use all sources)">${icon("close")}</button>
  </div>`;
}

// ---------------------------------------------------------- knowledge bases
async function loadKbs() {
  try {
    state.kbs = await api("/api/kbs");
  } catch (err) {
    state.kbs = [];
    toast(`Could not load knowledge bases: ${err.message}`, { error: true });
  }
  const names = state.kbs.map((k) => k.name);
  if (!state.kb || !names.includes(state.kb)) {
    const remembered = store.get("omnirag.kb");
    state.kb = names.includes(remembered)
      ? remembered
      : names.includes(state.defaultKb)
        ? state.defaultKb
        : names[0] || null;
    loadScope();
  }
  renderKbList();
}

function renderKbList() {
  const list = $("#kb-list");
  if (state.kbs === null) {
    list.innerHTML = `<li class="side-empty">Loading…</li>`;
    return;
  }
  if (!state.kbs.length) {
    list.innerHTML = `<li class="side-empty">No knowledge bases yet</li>`;
    return;
  }
  list.innerHTML = state.kbs
    .map(
      (k) => `<li class="side-item" ${k.name === state.kb ? 'aria-current="true"' : ""}>
        <button type="button" data-kb="${esc(k.name)}" title="${esc(k.description || k.name)}">
          ${icon("db", "kb-glyph")}
          <span class="label">${esc(k.name)}</span>
          <span class="meta" aria-label="${plural(k.documents, "document")}">${k.documents}</span>
        </button>
        <button class="icon-btn sm danger" type="button" data-delete-kb="${esc(k.name)}" aria-label="Delete knowledge base ${esc(k.name)}">${icon("trash")}</button>
      </li>`,
    )
    .join("");
}

async function switchKb(name) {
  if (name === state.kb && state.stats) return;
  stopStreaming();
  state.kb = name;
  store.set("omnirag.kb", name);
  state.stats = null;
  state.docs = null;
  state.docsKb = null;
  state.starters = null;
  loadScope();
  state.chatId = null;
  closeDrawer();
  renderKbList();
  renderChatList();
  renderComposerContext();
  renderTopbar();
  renderView();
  await refreshKb();
}

async function refreshKb() {
  if (!state.kb) {
    state.stats = null;
    renderTopbar();
    renderView();
    loadStatus();
    return;
  }
  const name = state.kb;
  try {
    const stats = await api(`${kbPath(name)}/stats`);
    if (name !== state.kb) return;
    state.stats = stats;
  } catch (err) {
    state.stats = null;
    toast(err.message, { error: true });
  }
  renderTopbar();
  loadDocs();
  if (state.view === "chat" && !currentChat()?.messages.length) renderThread();
  if (state.view === "settings") loadSettings();
  loadStatus();
}

function openKbDialog() {
  const dialog = $("#kb-dialog");
  $("#kb-form").reset();
  $("#kb-error").textContent = "";
  $("#kb-name").removeAttribute("aria-invalid");
  openDialog(dialog);
  $("#kb-name").focus();
}

async function createKb(event) {
  event.preventDefault();
  const name = $("#kb-name").value.trim();
  const description = $("#kb-desc").value.trim();
  const error = $("#kb-error");
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/.test(name)) {
    error.textContent = "Use 1–64 letters, digits, dots, dashes or underscores, starting with a letter or digit.";
    $("#kb-name").setAttribute("aria-invalid", "true");
    $("#kb-name").focus();
    return;
  }
  const btn = $("#kb-create");
  btn.disabled = true;
  try {
    await api("/api/kbs", { method: "POST", body: { name, description } });
    $("#kb-dialog").close();
    await loadKbs();
    await switchKb(name);
    location.hash = "#/library";
    toast(`Created ${name}. Add some files to get started.`);
  } catch (err) {
    error.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}

async function deleteKb(name) {
  const kb = state.kbs.find((k) => k.name === name);
  const ok = await confirmAction({
    title: `Delete “${name}”?`,
    body: `This permanently removes the index${kb ? ` (${plural(kb.documents, "document")}, ${plural(kb.chunks, "chunk")})` : ""}, uploaded files and settings. Files ingested from server paths are not touched. This cannot be undone.`,
    ok: "Delete knowledge base",
  });
  if (!ok) return;
  try {
    await api(kbPath(name), { method: "DELETE" });
    state.chats = state.chats.filter((c) => c.kb !== name);
    saveChats();
    store.remove(scopeKey(name));
    if (state.kb === name) state.kb = null;
    await loadKbs();
    await switchKb(state.kb);
    toast(`Deleted ${name}`);
  } catch (err) {
    toast(err.message, { error: true });
  }
}

// ------------------------------------------------------------------ status
async function loadStatus() {
  const q = state.kb ? `?kb=${encodeURIComponent(state.kb)}` : "";
  const name = state.kb;
  try {
    const status = await api(`/api/status${q}`);
    if (name !== state.kb) return;
    state.status = status;
  } catch (err) {
    state.status = { error: err.message };
  }
  renderStatusPill();
  if (state.view === "settings") renderStatusGrid();
  if (state.view === "library") renderDropHint();
}

function llmLabel(llm) {
  if (!llm || llm.backend === "none") return "Extractive";
  return `${llm.backend === "openai" ? "OpenAI-compatible" : "Ollama"} · ${llm.model}`;
}

function renderStatusPill() {
  const dot = $("#status-dot");
  const text = $("#status-text");
  const s = state.status;
  if (!s || s.error) {
    dot.dataset.state = "down";
    text.textContent = s?.error ? "Server unreachable" : "Checking…";
    return;
  }
  const llm = s.llm;
  if (llm.backend === "none") {
    dot.dataset.state = "offline";
    text.textContent = "Extractive · offline";
  } else if (llm.reachable) {
    dot.dataset.state = "ok";
    text.textContent = llmLabel(llm);
  } else {
    dot.dataset.state = "down";
    text.textContent = `${llm.backend === "openai" ? "Endpoint" : "Ollama"} unreachable`;
  }
  $("#status-pill").title = `${llmLabel(llm)}${llm.detail ? ` — ${llm.detail}` : ""}`;
}

// ----------------------------------------------------------------- routing
function viewFromHash() {
  const v = location.hash.replace(/^#\/?/, "");
  return VIEWS[v] ? v : "chat";
}

function showView(view) {
  state.view = view;
  $("#app").dataset.view = view;
  for (const v of Object.keys(VIEWS)) $(`#view-${v}`).hidden = v !== view;
  for (const a of $$(".nav-link[data-nav]")) {
    if (a.dataset.nav === view) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  if (view !== "chat" && state.drawer && state.drawer.mode !== "doc") closeDrawer();
  hideCiteCard();
  closeSidebar();
  renderTopbar();
  renderView();
}

function renderView() {
  if (state.view === "chat") renderThread();
  else if (state.view === "library") {
    renderLibrary();
    loadDocs();
  } else if (state.view === "settings") loadSettings();
}

function renderTopbar() {
  $("#view-title").textContent = VIEWS[state.view];
  document.title = `${VIEWS[state.view]}${state.kb ? ` · ${state.kb}` : ""} · OmniRAG`;
  const kbBtn = $("#topbar-kb");
  kbBtn.hidden = !state.kb;
  $(".crumb-sep").hidden = !state.kb;
  kbBtn.innerHTML = state.kb ? `${icon("db")}<span>${esc(state.kb)}</span>` : "";
  const s = state.stats;
  $("#topbar-meta").textContent = state.kb && s ? `${plural(s.documents, "document")} · ${plural(s.chunks, "chunk")}` : "";
  const actions = $("#topbar-actions");
  if (state.view === "chat" && state.kb) {
    const n = state.scope.size;
    const total = state.docs && state.docsKb === state.kb ? state.docs.length : state.stats?.documents;
    const open = state.drawer?.mode === "scope";
    actions.innerHTML = `
      <button class="btn btn-ghost btn-sm${n ? " is-scoped" : ""}" type="button" id="toggle-scope" aria-controls="drawer" aria-expanded="${open}" title="Choose the sources answers may use (S)">
        ${icon("layers")}<span>Sources</span><span class="count-badge">${n ? `${n}/${total ?? "–"}` : total ?? ""}</span></button>
      <button class="icon-btn" type="button" id="new-chat-top" aria-label="New chat" title="New chat (N)">${icon("compose")}</button>`;
  } else actions.innerHTML = "";
  for (const el of $$(".kb-name-ref")) el.textContent = state.kb || "";
  updateSendEnabled();
}

// --------------------------------------------------------------- chat view
function renderFilters() {
  const box = $("#filters");
  const all = state.filters.size === 0;
  box.innerHTML =
    `<button type="button" class="filter-chip" data-filter="" aria-pressed="${all}">All</button>` +
    MODALITIES.map(
      (m) => `<button type="button" class="filter-chip" data-filter="${m}" aria-pressed="${state.filters.has(m)}">${mIcon(m)}${MODALITY_LABEL[m]}</button>`,
    ).join("");
}

function toggleFilter(m) {
  if (!m) state.filters.clear();
  else if (state.filters.has(m)) state.filters.delete(m);
  else state.filters.add(m);
  renderFilters();
}

/** Fallback starter questions computed in the browser (used if the endpoint fails). */
function localStarters(docs) {
  const picks = [];
  const seen = new Set();
  for (const d of docs) {
    if (seen.has(d.modality) || picks.length >= 4) continue;
    seen.add(d.modality);
    const name = d.title || d.name;
    const question = {
      text: `Summarise ${name}`,
      code: `What does ${d.name} do?`,
      table: `What does ${d.name} contain?`,
      image: `What does ${d.name} show?`,
      audio: `Summarise the ${name} transcript`,
    }[d.modality];
    if (question) picks.push({ question, source: d.name, modality: d.modality });
  }
  return picks;
}

function autosize() {
  const q = $("#question");
  q.style.height = "auto";
  q.style.height = `${Math.min(q.scrollHeight, 200)}px`;
  q.style.overflowY = q.scrollHeight > 200 ? "auto" : "hidden";
  updateSendEnabled();
}

function setEmptyMode(empty) {
  const view = $("#view-chat");
  if (view.classList.contains("is-empty") === empty) return;
  const composer = $("#composer");
  const before = composer.getBoundingClientRect();
  view.classList.toggle("is-empty", empty);
  autosize();
  if (empty || reducedMotion() || !before.height) return;
  // FLIP: glide the composer from the centre of the page down to its dock.
  const after = composer.getBoundingClientRect();
  const dy = before.top - after.top;
  if (Math.abs(dy) < 4) return;
  composer.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }], {
    duration: 200,
    easing: "cubic-bezier(0.16, 1, 0.3, 1)",
  });
}

function renderEmptyThread() {
  const thread = $("#thread");
  setEmptyMode(true);
  const starters = $("#starters");
  const q = $("#question");
  if (state.kbs === null) {
    thread.innerHTML = `<div class="hero"><span class="thinking">Loading…</span></div>`;
    starters.innerHTML = "";
    return;
  }
  if (!state.kb) {
    thread.innerHTML = `<div class="hero">
      <h2>Create a knowledge base</h2>
      <p class="hero-sub">A knowledge base holds the documents, code, tables, images and transcripts OmniRAG answers from. Everything stays on this server.</p>
      <div class="hero-actions"><button class="btn btn-primary" type="button" data-action="new-kb">${icon("plus")}New knowledge base</button></div>
    </div>`;
    starters.innerHTML = "";
    q.placeholder = "Create a knowledge base first";
    return;
  }
  const s = state.stats;
  if (s && s.documents === 0) {
    thread.innerHTML = `<div class="hero">
      <h2>${esc(state.kb)} is empty</h2>
      <p class="hero-sub">Add files in the library, then ask about them here. Answers cite the exact section, line range, table rows or timestamp they came from.</p>
      <div class="hero-actions"><a class="btn btn-primary" href="#/library">${icon("upload")}Add files</a></div>
    </div>`;
    starters.innerHTML = "";
    q.placeholder = "Add files to start asking";
    return;
  }
  const kinds = s ? MODALITIES.filter((m) => s.documents_by_modality?.[m]).map((m) => MODALITY_LABEL[m].toLowerCase()) : [];
  thread.innerHTML = `<div class="hero">
    <h2>Ask <span class="hero-kb">${esc(state.kb)}</span> anything</h2>
    <p class="hero-sub">${s ? `${plural(s.documents, "document")} · ${plural(s.chunks, "chunk")}${kinds.length ? ` · ${esc(kinds.join(", "))}` : ""}` : "&nbsp;"}</p>
  </div>`;
  q.placeholder = state.scope.size ? `Ask the ${plural(state.scope.size, "selected source")}` : `Ask ${state.kb} anything`;
  renderStarters();
  loadStarters();
}

const startersKey = () => `${state.kb}|${[...state.scope].sort().join(",")}`;

function renderStarters() {
  const box = $("#starters");
  const list = state.starters?.key === startersKey() ? state.starters.items : null;
  if (!list) {
    box.innerHTML = `<div class="starter skeleton-card"></div>`.repeat(4);
    return;
  }
  box.innerHTML = list.length
    ? `<h3 class="starters-head">Try asking</h3>` +
      list
        .map(
          (s) => `<button class="starter" type="button" data-ask="${esc(s.question)}">
            <span class="starter-q">${esc(s.question)}</span>
            <span class="starter-src">${mIcon(s.modality)}${esc(s.source)}</span></button>`,
        )
        .join("")
    : "";
}

let startersToken = 0;
async function loadStarters() {
  if (!state.kb || state.starters?.key === startersKey()) return;
  const name = state.kb;
  const key = startersKey();
  const scopeIds = [...state.scope];
  const token = ++startersToken;
  let items;
  try {
    const r = await api(`${kbPath(name)}/related`, {
      method: "POST",
      body: { limit: 4, doc_ids: scopeIds.length ? scopeIds : null },
    });
    items = r.questions;
  } catch {
    const docs = state.docs && state.docsKb === name ? state.docs : [];
    items = localStarters(scopeIds.length ? docs.filter((d) => state.scope.has(d.doc_id)) : docs);
  }
  if (token !== startersToken || name !== state.kb) return;
  state.starters = { key, items };
  if (state.view === "chat" && !currentChat()?.messages.length) renderStarters();
}

// ---- answer rendering
function citeGroup(index, msg) {
  // When every cited source comes from one file, a row of identical file-name
  // pills says nothing; label each pill by its section/lines/rows instead.
  const citedNums = msg.cited?.length ? msg.cited : [...(msg.text || "").matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1]));
  const citedFiles = new Set(
    citedNums.map((n) => msg.sources?.find((s) => s.index === n)).filter(Boolean).map(shortName),
  );
  const singleFile = citedFiles.size === 1;
  const label = (s) => (singleFile && shortLoc(s) ? shortLoc(s) : shortName(s));
  return (nums) => {
    const known = [...new Set(nums)].filter((n) => msg.sources?.some((s) => s.index === n));
    if (!known.length) return `<span class="cite missing" title="No matching source">[${esc(nums.join(", "))}]</span>`;
    const first = msg.sources.find((s) => s.index === known[0]);
    const names = [...new Set(known.map((n) => shortName(msg.sources.find((s) => s.index === n))))];
    const more = known.length - 1;
    return `<button type="button" class="cite" data-cites="${known.join(",")}" data-msg="${index}" aria-label="Source${known.length > 1 ? "s" : ""} ${known.join(", ")}: ${esc(names.join(", "))}" title="${esc(`${shortName(first)} · ${shortLoc(first)}`)}">
      <span class="cite-name">${esc(label(first))}</span>${more ? `<span class="cite-more">+${more}</span>` : ""}</button>`;
  };
}

/** Sources ordered cited-first (in order of citation), then the rest. */
function orderedSources(msg) {
  const sources = msg.sources || [];
  if (msg.pending || !msg.cited?.length) return { cited: msg.pending ? sources : [], rest: msg.pending ? [] : sources };
  const cited = msg.cited.map((n) => sources.find((s) => s.index === n)).filter(Boolean);
  return { cited, rest: sources.filter((s) => !msg.cited.includes(s.index)) };
}

function sourceCard(s, index, cited) {
  const thumb = s.modality === "image" ? `<span class="card-thumb" data-thumb="${esc(s.doc_id)}" data-kb="${esc(currentChat()?.kb || "")}"></span>` : "";
  return `<button type="button" class="source-card${cited ? " cited" : ""}" data-cite="${s.index}" data-msg="${index}" title="${esc(s.metadata?.path || s.source)}">
    ${thumb}<span class="card-top">${mIcon(s.modality)}<span class="card-name">${esc(shortName(s))}</span></span>
    <span class="card-loc">${esc(shortLoc(s))}</span>
    <span class="card-n" aria-label="source ${s.index}">${s.index}</span></button>`;
}

function renderStrip(msg, index) {
  if (!msg.sources?.length) return "";
  const { cited, rest } = orderedSources(msg);
  const lead = msg.pending ? msg.sources : cited.length ? cited : rest;
  const tail = msg.pending || !cited.length ? [] : rest;
  const shown = lead.slice(0, 8);
  const more = lead.length - shown.length + tail.length;
  return `<div class="source-strip" role="list" aria-label="Sources">
    ${shown.map((s) => `<div role="listitem">${sourceCard(s, index, !msg.pending && cited.includes(s))}</div>`).join("")}
    ${more > 0 ? `<div role="listitem"><button type="button" class="source-card more-card" data-tab="sources" data-msg="${index}"><span class="card-name">+${more} more</span><span class="card-loc">${tail.length ? "retrieved, not cited" : "sources"}</span></button></div>` : ""}
  </div>`;
}

const STEPS = [
  ["search", (m) => `Searching ${m.searched ? plural(m.searched, "chunk") : "the knowledge base"}`],
  ["read", (m) => `Reading ${m.sources ? plural(m.sources.length, "source") : "sources"}`],
  ["write", () => "Writing"],
  ["done", () => "Done"],
];

function renderSteps(msg) {
  const at = STEPS.findIndex(([k]) => k === (msg.phase || "search"));
  return `<ol class="steps" aria-label="Progress">${STEPS.map(([key, label], i) => {
    const st = i < at ? "done" : i === at ? "active" : "todo";
    return `<li class="step" data-state="${st}"${st === "active" ? ' aria-current="step"' : ""}><span class="step-dot" aria-hidden="true">${st === "done" ? icon("check") : ""}</span>${esc(label(msg))}</li>`;
  }).join("")}</ol>`;
}

function renderRunSummary(msg) {
  const t = msg.timings || {};
  const n = msg.cited?.length || msg.sources?.length || 0;
  let head;
  if (msg.error && !msg.text) head = "Could not answer";
  else if (msg.stopped) head = `Stopped${n ? ` · ${plural(n, "source")} retrieved` : ""}`;
  else head = `Answered from ${plural(n, "source")}${t.total_ms ? ` in ${formatMs(t.total_ms)}` : ""}`;
  const scope = msg.scope?.ids?.length ? `<span class="run-scope">${icon("layers")}scoped to ${plural(msg.scope.ids.length, "source")}</span>` : "";
  const rows = [
    `Searched ${msg.searched ? plural(msg.searched, "chunk") : "the knowledge base"}${t.retrieve_ms != null ? ` · ${Math.round(t.retrieve_ms)} ms` : ""}`,
    msg.sources ? `Read ${plural(msg.sources.length, "source")}${msg.cited?.length ? `, cited ${msg.cited.length}` : ""}` : "",
    msg.text ? `Wrote the answer${msg.backend ? ` with ${msg.backend}` : ""}${t.generate_ms != null ? ` · ${Math.round(t.generate_ms)} ms` : ""}` : "",
    msg.scope?.names?.length ? `Scope: ${msg.scope.names.join(", ")}` : "",
  ].filter(Boolean);
  return `<details class="run-summary"><summary>${icon("check", "run-icon")}<span>${esc(head)}</span>${scope}${icon("chevron", "run-chevron")}</summary>
    <ul class="run-steps">${rows.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></details>`;
}

function renderAnswerPanel(msg, index) {
  const parts = [];
  const streaming = msg.pending && !msg.error;
  parts.push(renderStrip(msg, index));
  if (msg.text) {
    parts.push(
      `<div class="answer-body${streaming ? " streaming" : ""}">${renderMarkdown(msg.text, { cite: citeGroup(index, msg) })}</div>`,
    );
  } else if (streaming) {
    parts.push(`<div class="answer-skeleton" aria-hidden="true"><span></span><span></span><span></span></div>`);
  }
  if (msg.error) parts.push(`<div class="notice error">${esc(msg.error)}</div>`);
  if (msg.stopped) parts.push(`<div class="notice">Stopped. The answer above is incomplete.</div>`);
  for (const w of msg.warnings || []) parts.push(`<div class="notice">${esc(w)}</div>`);
  if (!msg.pending && (msg.text || msg.error)) {
    const offline = msg.backend === "extractive" && msg.text;
    parts.push(`<div class="answer-foot">
      ${msg.text ? `<button class="btn btn-ghost btn-xs" type="button" data-copy="${index}">${icon("copy")}<span>Copy</span></button>` : ""}
      ${offline ? `<a class="foot-hint" href="#/settings" title="Answers are quoted from your sources. Connect Ollama or an OpenAI-compatible model for written answers.">Quoted from sources · connect a model for written answers</a>` : ""}
    </div>`);
  }
  if (msg.related?.length) {
    parts.push(`<section class="related" aria-label="Related questions"><h3>${icon("layers")}Related</h3><ul>${msg.related
      .map(
        (r) => `<li><button type="button" data-ask="${esc(r.question)}"><span>${esc(r.question)}</span>${icon("plus")}</button></li>`,
      )
      .join("")}</ul></section>`);
  }
  return parts.join("");
}

function renderSourcesPanel(msg, index) {
  if (!msg.sources?.length) return `<p class="panel-empty">No sources were retrieved for this question.</p>`;
  const { cited, rest } = orderedSources(msg);
  const row = (s) => `<li><button type="button" class="source-row" data-cite="${s.index}" data-msg="${index}">
      <span class="row-n">${s.index}</span>
      <span class="row-main"><span class="row-top">${mIcon(s.modality)}<span class="row-name">${esc(shortName(s))}</span><span class="row-loc">${esc(shortLoc(s))}</span></span>
      <span class="row-path">${esc(s.metadata?.path || s.source)}</span>
      <span class="row-snippet">${esc(excerptOf(s, 220))}</span></span></button></li>`;
  return `${cited.length ? `<h3 class="panel-head">Cited in the answer <span class="count">${cited.length}</span></h3><ul class="source-rows">${cited.map(row).join("")}</ul>` : ""}
    ${rest.length ? `<h3 class="panel-head">${cited.length ? "Also retrieved" : "Retrieved"} <span class="count">${rest.length}</span></h3><ul class="source-rows dim">${rest.map(row).join("")}</ul>` : ""}`;
}

function renderMediaPanel(msg, index) {
  const images = (msg.sources || []).filter((s) => s.modality === "image");
  const kb = currentChat()?.kb || "";
  return `<div class="media-grid">${images
    .map(
      (s) => `<button type="button" class="media-item" data-cite="${s.index}" data-msg="${index}">
        <span class="media-frame" data-thumb="${esc(s.doc_id)}" data-kb="${esc(kb)}"></span>
        <span class="media-cap"><span class="row-n">${s.index}</span>${esc(shortName(s))}</span></button>`,
    )
    .join("")}</div>`;
}

function renderTurn(msg, index, question) {
  const images = (msg.sources || []).filter((s) => s.modality === "image").length;
  const n = msg.sources?.length || 0;
  const tab = msg.tab === "media" && !images ? "answer" : msg.tab || "answer";
  const tabs = [
    ["answer", "Answer", ""],
    ["sources", "Sources", n || ""],
    ...(images ? [["media", "Media", images]] : []),
  ];
  const id = `t${index}`;
  const panel =
    tab === "sources" ? renderSourcesPanel(msg, index) : tab === "media" ? renderMediaPanel(msg, index) : renderAnswerPanel(msg, index);
  return `<header class="turn-head">
      <h2 class="turn-q">${esc(question)}</h2>
      <div class="turn-tabs" role="tablist" aria-label="Answer views">${tabs
        .map(
          ([key, label, count]) => `<button type="button" role="tab" id="${id}-${key}" data-tab="${key}" data-msg="${index}"
            aria-selected="${key === tab}" aria-controls="${id}-panel" tabindex="${key === tab ? 0 : -1}">${label}${count !== "" ? `<span class="tab-count">${count}</span>` : ""}</button>`,
        )
        .join("")}</div>
    </header>
    <div class="turn-status">${msg.pending ? renderSteps(msg) : renderRunSummary(msg)}</div>
    <div class="turn-panel" role="tabpanel" id="${id}-panel" aria-labelledby="${id}-${tab}" data-panel="${tab}">${panel}</div>`;
}

function renderThread(scrollToEnd = false) {
  if (state.view !== "chat") return;
  const chat = currentChat();
  const thread = $("#thread");
  hideCiteCard();
  if (!chat || !chat.messages.length) {
    renderEmptyThread();
    return;
  }
  setEmptyMode(false);
  $("#starters").innerHTML = "";
  $("#question").placeholder = state.scope.size ? `Ask a follow-up about the ${plural(state.scope.size, "selected source")}` : "Ask a follow-up";
  const turns = [];
  chat.messages.forEach((m, i) => {
    if (m.role !== "assistant") return;
    turns.push(`<article class="turn" data-index="${i}">${renderTurn(m, i, chat.messages[i - 1]?.text || "")}</article>`);
  });
  thread.innerHTML = turns.join("");
  markActiveSource();
  hydrateThumbs(thread);
  if (scrollToEnd) thread.scrollTop = thread.scrollHeight;
}

let renderQueued = new Set();
function updateTurn(index) {
  const first = renderQueued.size === 0;
  renderQueued.add(index);
  if (!first) return;
  requestAnimationFrame(() => {
    const indices = [...renderQueued];
    renderQueued = new Set();
    const chat = currentChat();
    if (!chat || state.view !== "chat") return;
    for (const i of indices) {
      const el = $(`#thread .turn[data-index="${i}"]`);
      if (!el) continue;
      const focusedTab = document.activeElement?.closest?.(`.turn[data-index="${i}"] [role="tab"]`)?.dataset.tab;
      el.innerHTML = renderTurn(chat.messages[i], i, chat.messages[i - 1]?.text || "");
      if (focusedTab) $(`[role="tab"][data-tab="${focusedTab}"]`, el)?.focus();
      hydrateThumbs(el);
    }
    markActiveSource();
  });
}

function setTab(index, tab, focus = false) {
  const msg = currentChat()?.messages[index];
  if (!msg) return;
  msg.tab = tab;
  saveChats();
  const el = $(`#thread .turn[data-index="${index}"]`);
  if (!el) return;
  hideCiteCard();
  el.innerHTML = renderTurn(msg, index, currentChat().messages[index - 1]?.text || "");
  hydrateThumbs(el);
  markActiveSource();
  if (focus) $(`[role="tab"][data-tab="${tab}"]`, el)?.focus();
}

function setComposerBusy(busy) {
  const send = $("#send");
  send.classList.toggle("stop", busy);
  send.innerHTML = icon(busy ? "stop" : "send");
  send.setAttribute("aria-label", busy ? "Stop generating" : "Send");
  send.title = busy ? "Stop generating (Esc)" : "Send (Enter)";
  updateSendEnabled();
}

function updateSendEnabled() {
  const busy = Boolean(state.controller);
  const noKb = !state.kb || state.stats?.documents === 0;
  $("#send").disabled = !busy && (!$("#question").value.trim() || noKb);
  $("#question").disabled = !state.kb;
}

function stopStreaming() {
  if (state.controller) state.controller.abort();
}

function parseSse(block) {
  let event = "message";
  const data = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  return { event, data: data.length ? JSON.parse(data.join("\n")) : null };
}

/** How many chunks the next question searches (the scope, or the whole KB). */
function searchableChunks() {
  if (state.scope.size) return scopedDocs().reduce((n, d) => n + (d.chunks || 0), 0) || null;
  return state.stats?.chunks ?? null;
}

async function ask(question) {
  if (!state.kb || state.controller) return;
  question = question.trim();
  if (!question) return;
  hideCiteCard();
  let chat = currentChat();
  if (!chat) {
    chat = {
      id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
      kb: state.kb,
      title: question.length > 60 ? `${question.slice(0, 57)}…` : question,
      created: Date.now(),
      updated: Date.now(),
      messages: [],
    };
    state.chats.push(chat);
    state.chatId = chat.id;
  }
  if (state.view !== "chat") location.hash = "#/chat";
  const scopeIds = [...state.scope];
  const scope = scopeIds.length ? { ids: scopeIds, names: scopedDocs().map((d) => d.name) } : null;
  chat.messages.push({ role: "user", text: question });
  const msg = { role: "assistant", text: "", pending: true, phase: "search", searched: searchableChunks(), scope, tab: "answer" };
  chat.messages.push(msg);
  const index = chat.messages.length - 1;
  chat.updated = Date.now();
  saveChats();
  renderChatList();
  renderThread();
  const turnEl = $(`#thread .turn[data-index="${index}"]`);
  if (turnEl) turnEl.scrollIntoView({ block: "start" });

  const controller = new AbortController();
  state.controller = controller;
  setComposerBusy(true);
  const body = {
    query: question,
    kb: chat.kb,
    modalities: state.filters.size ? [...state.filters] : null,
    doc_ids: scopeIds.length ? scopeIds : null,
  };
  try {
    const res = await api("/api/query/stream", { method: "POST", body, signal: controller.signal, raw: true });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let cut;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const { event, data } = parseSse(buffer.slice(0, cut));
        buffer = buffer.slice(cut + 2);
        if (event === "sources") {
          msg.sources = data.sources.map(slimSource);
          msg.phase = "read";
        } else if (event === "delta") {
          msg.text += data.text;
          msg.phase = "write";
        } else if (event === "done") {
          msg.text = data.answer;
          msg.cited = data.cited;
          msg.backend = data.backend;
          msg.timings = data.timings;
          msg.warnings = data.warnings;
          msg.sources = data.sources.map(slimSource);
          msg.phase = "done";
        } else if (event === "error") msg.error = data.detail;
        if (state.chatId === chat.id) updateTurn(index);
      }
    }
  } catch (err) {
    if (err.name === "AbortError") msg.stopped = true;
    else msg.error = err.message || "The request failed.";
  } finally {
    msg.pending = false;
    msg.phase = "done";
    if (!msg.text && !msg.error && !msg.stopped) msg.error = "No answer was returned.";
    if (!msg.cited && msg.text) {
      // Interrupted answers: mark whatever was cited so far.
      const known = new Set((msg.sources || []).map((s) => s.index));
      msg.cited = [...new Set([...msg.text.matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1])))].filter((n) => known.has(n));
    }
    state.controller = null;
    chat.updated = Date.now();
    saveChats();
    setComposerBusy(false);
    if (state.chatId === chat.id) updateTurn(index);
    renderChatList();
    if (msg.text && !msg.error) {
      announce(`Answer ready, ${plural(msg.cited?.length || 0, "citation")}.`);
      loadRelated(chat, index);
    }
  }
}

async function loadRelated(chat, index) {
  const msg = chat.messages[index];
  if (!msg?.sources?.length) return;
  const { cited, rest } = orderedSources(msg);
  const asked = new Set(chat.messages.filter((m) => m.role === "user").map((m) => m.text.toLowerCase()));
  try {
    const r = await api(`${kbPath(chat.kb)}/related`, {
      method: "POST",
      body: {
        query: chat.messages[index - 1]?.text || "",
        chunk_ids: [...cited, ...rest].map((s) => s.chunk_id),
        doc_ids: msg.scope?.ids?.length ? msg.scope.ids : null,
        limit: 4,
      },
    });
    msg.related = r.questions.filter((q) => !asked.has(q.question.toLowerCase()));
    saveChats();
    if (state.chatId === chat.id) updateTurn(index);
  } catch {
    /* related questions are optional */
  }
}

function copyText(msg) {
  const cited = new Set(msg.cited || []);
  const refs = (msg.sources || [])
    .filter((s) => cited.has(s.index))
    .map((s) => `[${s.index}] ${s.metadata?.path || s.source}${shortLoc(s) ? ` — ${shortLoc(s)}` : ""}`);
  return refs.length ? `${msg.text}\n\nSources:\n${refs.join("\n")}` : msg.text;
}

async function copyAnswer(index, button) {
  const msg = currentChat()?.messages[index];
  if (!msg?.text) return;
  try {
    await navigator.clipboard.writeText(copyText(msg));
    button.innerHTML = `${icon("check")}<span>Copied</span>`;
    setTimeout(() => (button.innerHTML = `${icon("copy")}<span>Copy</span>`), 1600);
  } catch {
    toast("Copy failed: clipboard access was blocked", { error: true });
  }
}

// --------------------------------------------------------- raw files/thumbs
const rawCache = new Map(); // "kb/doc" -> Promise<blob url>
function rawUrl(kb, docId) {
  const key = `${kb}/${docId}`;
  if (!rawCache.has(key)) {
    const p = api(`${kbPath(kb)}/documents/${encodeURIComponent(docId)}/raw`, { raw: true }).then(async (res) =>
      URL.createObjectURL(await res.blob()),
    );
    p.catch(() => rawCache.delete(key));
    rawCache.set(key, p);
  }
  return rawCache.get(key);
}

function hydrateThumbs(root) {
  for (const el of $$("[data-thumb]", root)) {
    if (el.firstChild) continue;
    rawUrl(el.dataset.kb || state.kb, el.dataset.thumb)
      .then((url) => {
        if (el.firstChild) return;
        const img = new Image();
        img.alt = "";
        img.decoding = "async";
        img.src = url;
        el.append(img);
      })
      .catch(() => el.classList.add("thumb-missing"));
  }
}

async function openRaw(docId, kb = state.kb) {
  // Open the tab synchronously so popup blockers allow it, then point it at the file.
  const win = window.open("", "_blank");
  try {
    const url = await rawUrl(kb, docId);
    if (win) win.location.href = url;
    else window.open(url, "_blank", "noopener");
  } catch (err) {
    win?.close();
    toast(`Could not open the file: ${err.message}`, { error: true });
  }
}

// ------------------------------------------------------------- citation card
const card = () => $("#cite-card");
let cardShowTimer = null;
let cardHideTimer = null;
let cardPill = null;

const STOP = new Set(
  "what when where which while with would about does have from that this there their them they into your how why who the and for are was were will been being can could should tell show".split(" "),
);
function questionWords(chat, index) {
  const q = chat?.messages[index - 1]?.text || "";
  return [...new Set(q.toLowerCase().match(/[a-z0-9]{4,}/g) || [])].filter((w) => !STOP.has(w)).map((w) => w.slice(0, Math.max(4, w.length - 2)));
}

function highlight(text, words) {
  if (!words.length) return esc(text);
  const re = new RegExp(`\\b(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})\\w*`, "gi");
  let out = "";
  let last = 0;
  for (const m of text.matchAll(re)) {
    out += esc(text.slice(last, m.index)) + `<mark class="highlight">${esc(m[0])}</mark>`;
    last = m.index + m[0].length;
  }
  return out + esc(text.slice(last));
}

function showCiteCard(pill) {
  clearTimeout(cardHideTimer);
  const chat = currentChat();
  const index = Number(pill.dataset.msg);
  const msg = chat?.messages[index];
  if (!msg?.sources) return;
  const nums = pill.dataset.cites.split(",").map(Number);
  const words = questionWords(chat, index);
  const items = nums
    .slice(0, 3)
    .map((n) => msg.sources.find((s) => s.index === n))
    .filter(Boolean);
  const el = card();
  el.innerHTML = items
    .map(
      (s) => `<div class="cc-item">
        <div class="cc-top"><span class="row-n">${s.index}</span>${mIcon(s.modality)}<span class="cc-name">${esc(shortName(s))}</span><span class="cc-loc">${esc(shortLoc(s))}</span></div>
        <p class="cc-text">${highlight(excerptOf(s, 240), words)}</p>
        <button type="button" class="btn btn-ghost btn-xs" tabindex="-1" data-cite="${s.index}" data-msg="${index}">${icon("arrow-right")}Open source</button>
      </div>`,
    )
    .join("") + (nums.length > 3 ? `<p class="cc-more">+${nums.length - 3} more in the Sources tab</p>` : "");
  el.hidden = false;
  cardPill?.removeAttribute("aria-describedby");
  cardPill = pill;
  pill.setAttribute("aria-describedby", "cite-card");
  // Position below the pill, flipping above when there is no room.
  const r = pill.getBoundingClientRect();
  const w = Math.min(360, window.innerWidth - 16);
  el.style.width = `${w}px`;
  const h = el.offsetHeight;
  const below = r.bottom + 8 + h < window.innerHeight - 8;
  el.style.top = `${below ? r.bottom + 6 : Math.max(8, r.top - h - 6)}px`;
  el.style.left = `${Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8)}px`;
  el.dataset.side = below ? "below" : "above";
}

function hideCiteCard() {
  clearTimeout(cardShowTimer);
  clearTimeout(cardHideTimer);
  const el = card();
  if (el) el.hidden = true;
  cardPill?.removeAttribute("aria-describedby");
  cardPill = null;
}

function scheduleHideCard() {
  clearTimeout(cardShowTimer);
  clearTimeout(cardHideTimer);
  cardHideTimer = setTimeout(hideCiteCard, 160);
}

function bindCiteCard() {
  document.addEventListener("pointerover", (e) => {
    const pill = e.target.closest?.(".cite[data-cites]");
    if (!pill || e.pointerType === "touch" || !finePointer()) return;
    clearTimeout(cardHideTimer);
    if (cardPill === pill && !card().hidden) return;
    clearTimeout(cardShowTimer);
    cardShowTimer = setTimeout(() => showCiteCard(pill), 120);
  });
  document.addEventListener("pointerout", (e) => {
    const pill = e.target.closest?.(".cite[data-cites]");
    if (pill && !pill.contains(e.relatedTarget) && !card().contains(e.relatedTarget)) scheduleHideCard();
  });
  card().addEventListener("pointerenter", () => clearTimeout(cardHideTimer));
  card().addEventListener("pointerleave", scheduleHideCard);
  document.addEventListener("focusin", (e) => {
    const pill = e.target.closest?.(".cite[data-cites]");
    if (pill) showCiteCard(pill);
    else if (!card().contains(e.target)) hideCiteCard();
  });
  $("#thread").addEventListener("scroll", () => cardPill && hideCiteCard(), { passive: true });
  window.addEventListener("resize", hideCiteCard);
}

// ------------------------------------------------------------------ drawer
function openDrawer(mode, extra = {}) {
  state.drawer = { mode, ...extra };
  const drawer = $("#drawer");
  const wasHidden = drawer.hidden;
  drawer.hidden = false;
  drawer.dataset.mode = mode;
  $("#app").classList.add("has-drawer");
  if (isSheet()) $("#scrim").hidden = false;
  if (wasHidden && !reducedMotion()) drawer.animate(isSheet() ? [{ transform: "translateY(24px)", opacity: 0 }, { transform: "none", opacity: 1 }] : [{ opacity: 0, transform: "translateX(8px)" }, { opacity: 1, transform: "none" }], { duration: 180, easing: "cubic-bezier(0.16, 1, 0.3, 1)" });
  renderTopbar();
}

function closeDrawer() {
  if (!state.drawer) return;
  const mode = state.drawer.mode;
  state.drawer = null;
  $("#drawer").hidden = true;
  $("#app").classList.remove("has-drawer");
  if (!$("#app").classList.contains("sidebar-open")) $("#scrim").hidden = true;
  markActiveSource();
  renderTopbar();
  if (mode === "scope") $("#toggle-scope")?.focus();
}

const isSheet = () => window.matchMedia("(max-width: 1180px)").matches;

function markActiveSource() {
  const p = state.drawer?.mode === "preview" ? state.drawer : null;
  for (const el of $$("#thread [data-cite]")) {
    const on = p && p.chatId === state.chatId && +el.dataset.msg === p.index && +el.dataset.cite === p.n;
    el.toggleAttribute("data-active", Boolean(on));
  }
}

// ---- scope panel (choose documents)
function toggleScopePanel() {
  if (state.drawer?.mode === "scope") closeDrawer();
  else openScopePanel();
}

function openScopePanel() {
  if (!state.kb) return;
  openDrawer("scope");
  renderScopePanel();
  loadDocs();
  setTimeout(() => $("#scope-search")?.focus(), 0);
}

function renderScopePanel() {
  const docs = state.docs && state.docsKb === state.kb ? state.docs : null;
  const n = state.scope.size;
  $("#drawer-title").innerHTML = `<h2>Sources</h2><p class="drawer-sub">${n ? `${n} of ${docs?.length ?? "…"} selected · answers use only these` : "Tick documents to limit answers to them"}</p>`;
  const body = $("#drawer-body");
  const prev = $("#scope-search")?.value || "";
  const hadFocus = document.activeElement?.id === "scope-search";
  if (!docs) {
    body.innerHTML = `<div class="skeleton-list">${'<div class="skeleton"></div>'.repeat(6)}</div>`;
    return;
  }
  const q = prev.trim().toLowerCase();
  const list = q ? docs.filter((d) => `${d.name} ${d.path} ${d.title} ${d.modality}`.toLowerCase().includes(q)) : docs;
  const allOn = list.length > 0 && list.every((d) => state.scope.has(d.doc_id));
  body.innerHTML = `<div class="scope-tools">
      <div class="search">${icon("search")}<label class="sr-only" for="scope-search">Filter sources</label><input type="search" id="scope-search" placeholder="Filter sources" value="${esc(prev)}"></div>
      <label class="check-row check-all"><input type="checkbox" id="scope-all" ${allOn ? "checked" : ""}><span>${q ? "Select matching" : "Select all"}</span></label>
    </div>
    <ul class="scope-list" aria-label="Documents">${list
      .map(
        (d) => `<li><label class="check-row"><input type="checkbox" data-scope-doc="${esc(d.doc_id)}" ${state.scope.has(d.doc_id) ? "checked" : ""}>
          ${mIcon(d.modality)}<span class="scope-name"><span>${esc(d.name)}</span><small>${esc(d.path !== d.name ? d.path : d.title || d.modality)}</small></span><span class="scope-meta">${d.chunks}</span></label></li>`,
      )
      .join("") || `<li class="panel-empty">No documents match.</li>`}</ul>
    <div class="drawer-foot">${n ? `<button class="btn btn-ghost btn-sm" type="button" data-action="clear-scope">Use all sources</button>` : `<span class="drawer-note">All ${plural(docs.length, "document")} are searched.</span>`}
      <button class="btn btn-primary btn-sm" type="button" data-action="scope-done">Done</button></div>`;
  const all = $("#scope-all");
  all.indeterminate = !allOn && list.some((d) => state.scope.has(d.doc_id));
  if (hadFocus) {
    const input = $("#scope-search");
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  }
}

// ---- source preview (one chunk)
let previewToken = 0;
function codeLines(text, start) {
  return `<pre class="code-lines"><code>${text
    .split("\n")
    .map((line, i) => `<span class="ln"><span class="ln-n">${start + i}</span><span class="ln-c">${esc(line) || " "}</span></span>`)
    .join("")}</code></pre>`;
}

async function openSource(index, n) {
  const chat = currentChat();
  const msg = chat?.messages[index];
  const s = msg?.sources?.find((x) => x.index === n);
  if (!s) return;
  hideCiteCard();
  const token = ++previewToken;
  openDrawer("preview", { chatId: chat.id, index, n });
  markActiveSource();
  const meta = s.metadata || {};
  $("#drawer-title").innerHTML = `<h2><span class="row-n">${n}</span>${esc(shortName(s))}</h2>
    <p class="drawer-sub">${mIcon(s.modality)}<span>${esc(shortLoc(s) || s.modality)}</span><span class="path">${esc(meta.path || s.source)}</span></p>`;
  const body = $("#drawer-body");
  body.innerHTML = `<span class="thinking">Loading source…</span>`;

  let chunk = null;
  let note = "";
  try {
    chunk = await api(`${kbPath(chat.kb)}/chunks/${encodeURIComponent(s.chunk_id)}?window=1`);
  } catch (err) {
    note = err.status === 404 ? "This chunk is no longer in the knowledge base; showing the saved copy." : err.message;
  }
  if (token !== previewToken) return;
  const content = chunk?.content ?? s.content;
  const words = questionWords(chat, index);
  const isCode = s.modality === "code" && Number.isInteger(Number(meta.line_start)) && meta.line_start !== undefined;
  // Code chunks are "description + fenced code"; number only the code lines.
  const fenced = isCode ? content.match(/^([\s\S]*?)```[\w+#.-]*\n([\s\S]*?)\n?```\s*$/) : null;
  const cited = isCode
    ? `${fenced?.[1].trim() ? `<pre class="code-head">${highlight(fenced[1].trim(), words)}</pre>` : ""}${codeLines(fenced ? fenced[2] : content, Number(meta.line_start))}`
    : `<pre>${highlight(content, words)}</pre>`;
  const ctx = (list, label) =>
    list?.length
      ? `<div class="excerpt context"><div class="excerpt-label"><span>${label}</span></div><pre>${esc(list.map((c) => c.content).join("\n\n"))}</pre></div>`
      : "";
  const metaRows = Object.entries(meta)
    .filter(([k, v]) => v !== "" && v !== null && !["title", "path"].includes(k))
    .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(typeof v === "object" ? JSON.stringify(v) : v)}</td></tr>`)
    .join("");
  const ranks = s.retrieval?.ranks ? Object.entries(s.retrieval.ranks).map(([k, v]) => `${k} #${v}`).join(" · ") : "";
  const wasCited = msg.cited?.includes(n);
  body.innerHTML = `
    ${note ? `<div class="notice">${esc(note)}</div>` : ""}
    ${s.modality === "image" ? `<figure class="preview-image"><span class="media-frame" data-thumb="${esc(s.doc_id)}" data-kb="${esc(chat.kb)}"></span></figure>` : ""}
    ${ctx(chunk?.before, "Before")}
    <div class="excerpt cited"><div class="excerpt-label"><span>${wasCited ? "Cited passage" : "Retrieved passage"}${shortLoc(s) ? ` · ${esc(shortLoc(s))}` : ""}</span></div>${cited}</div>
    ${ctx(chunk?.after, "After")}
    <div class="preview-actions">
      <button class="btn btn-secondary btn-sm" type="button" data-open-raw="${esc(s.doc_id)}">${icon("external")}Open original</button>
      <button class="btn btn-ghost btn-sm" type="button" data-copy-excerpt>${icon("copy")}Copy excerpt</button>
    </div>
    <details class="more"><summary>Retrieval details${ranks ? ` · ${esc(ranks)}` : ""}</summary><table class="meta-table"><tr><th>score</th><td>${Number(s.score).toFixed(3)}</td></tr>${metaRows}</table></details>`;
  hydrateThumbs(body);
  body.querySelector("[data-copy-excerpt]").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    try {
      await navigator.clipboard.writeText(content);
      btn.innerHTML = `${icon("check")}Copied`;
    } catch {
      toast("Copy failed: clipboard access was blocked", { error: true });
    }
  });
  if (isSheet()) $("#drawer-close").focus();
}

// ---- document panel (from the palette or the library)
function openDocPanel(docId) {
  openDrawer("doc", { docId });
  renderDocPanel();
  if (isSheet()) $("#drawer-close").focus();
}

let docToken = 0;
function renderDocPanel() {
  const d = state.docs?.find((x) => x.doc_id === state.drawer?.docId);
  if (!d) {
    closeDrawer();
    return;
  }
  const inScope = state.scope.has(d.doc_id);
  $("#drawer-title").innerHTML = `<h2>${esc(d.name)}</h2><p class="drawer-sub">${mIcon(d.modality)}<span>${esc(d.modality)}</span><span class="path">${esc(d.path)}</span></p>`;
  const body = $("#drawer-body");
  body.innerHTML = `
    <dl class="doc-facts">
      <dt>Chunks</dt><dd>${d.chunks}</dd><dt>Size</dt><dd>${formatBytes(d.size_bytes)}</dd>
      <dt>Ingested</dt><dd title="${esc(exactTime(d.updated_at))}">${esc(relativeTime(d.updated_at))}</dd>
      ${d.title && d.title !== d.name ? `<dt>Title</dt><dd>${esc(d.title)}</dd>` : ""}
    </dl>
    ${d.modality === "image" ? `<figure class="preview-image"><span class="media-frame" data-thumb="${esc(d.doc_id)}" data-kb="${esc(state.kb)}"></span></figure>` : ""}
    <div class="preview-actions">
      <button class="btn btn-primary btn-sm" type="button" data-ask-doc="${esc(d.doc_id)}">${icon("chat")}Ask about this document</button>
      <button class="btn btn-secondary btn-sm" type="button" data-scope-toggle="${esc(d.doc_id)}" aria-pressed="${inScope}">${icon(inScope ? "check" : "plus")}${inScope ? "In scope" : "Add to scope"}</button>
      <button class="btn btn-ghost btn-sm" type="button" data-open-raw="${esc(d.doc_id)}">${icon("external")}Open original</button>
    </div>
    <div class="excerpt" id="doc-start" hidden><div class="excerpt-label"><span>Beginning of the document</span></div><pre></pre></div>`;
  hydrateThumbs(body);
  const token = ++docToken;
  // Chunk ids are "<doc_id>-<position>"; the first chunk gives a quick look inside.
  api(`${kbPath()}/chunks/${encodeURIComponent(`${d.doc_id}-0000`)}?window=1`)
    .then((c) => {
      if (token !== docToken) return;
      const el = $("#doc-start");
      if (!el) return;
      el.querySelector("pre").textContent = [c.content, ...(c.after || []).map((x) => x.content)].join("\n\n").slice(0, 1600);
      el.hidden = false;
    })
    .catch(() => {});
}

function askAboutDoc(docId) {
  setScope([docId]);
  closeDrawer();
  if (currentChat()?.messages.length) state.chatId = null;
  location.hash = "#/chat";
  renderThread();
  renderChatList();
  $("#question").focus();
}

// ----------------------------------------------------------------- library
function renderDropHint() {
  const s = state.status;
  $("#drop-kb").textContent = state.kb || "a knowledge base";
  if (s?.upload_extensions) {
    $("#file-input").setAttribute("accept", s.upload_extensions.join(","));
    $("#drop-sub").textContent = `Documents, code, tables, images and transcripts · up to ${s.max_upload_mb} MB per file`;
  }
}

function renderLibrary() {
  renderDropHint();
  const disabled = !state.kb;
  $("#dropzone").hidden = disabled;
  if (disabled) {
    $("#doc-count").textContent = "";
    $("#selection-bar").hidden = true;
    $("#doc-table").innerHTML = `<div class="table-empty"><strong>No knowledge base selected</strong>Create one to start adding files.
      <div class="hero-actions"><button class="btn btn-primary" type="button" data-action="new-kb">${icon("plus")}New knowledge base</button></div></div>`;
  } else renderDocs();
}

async function loadDocs() {
  if (!state.kb) return;
  const name = state.kb;
  if (state.docsKb !== name) {
    state.docs = null;
    if (state.view === "library") renderDocs();
  }
  try {
    const docs = await api(`${kbPath(name)}/documents`);
    if (name !== state.kb) return;
    state.docs = docs;
    state.docsKb = name;
    state.docsError = null;
    pruneScope();
  } catch (err) {
    state.docsError = err.message;
  }
  if (state.view === "library") renderDocs();
  if (state.drawer?.mode === "scope") renderScopePanel();
  renderComposerContext();
  renderTopbar();
}

function filteredDocs() {
  const q = $("#doc-search").value.trim().toLowerCase();
  return q ? state.docs.filter((d) => `${d.name} ${d.path} ${d.title} ${d.modality}`.toLowerCase().includes(q)) : state.docs;
}

function renderSelectionBar() {
  const bar = $("#selection-bar");
  const n = state.scope.size;
  bar.hidden = !n || !state.docs;
  if (!n) return;
  bar.innerHTML = `${icon("layers")}<span><strong>${plural(n, "source")} selected</strong> · chat answers use only these</span>
    <span class="selection-actions"><button class="btn btn-ghost btn-sm" type="button" data-action="clear-scope">Clear</button>
    <button class="btn btn-primary btn-sm" type="button" data-action="chat-scope">${icon("chat")}Ask the selected sources</button></span>`;
}

function renderDocs() {
  const wrap = $("#doc-table");
  if (state.docsError && !state.docs) {
    wrap.innerHTML = `<div class="table-empty"><strong>Could not load documents</strong>${esc(state.docsError)}
      <div class="hero-actions"><button class="btn btn-secondary" type="button" data-action="reload-docs">${icon("refresh")}Try again</button></div></div>`;
    return;
  }
  if (!state.docs || state.docsKb !== state.kb) {
    $("#doc-count").textContent = "";
    wrap.innerHTML = `<div class="skeleton-list">${'<div class="skeleton"></div>'.repeat(5)}</div>`;
    return;
  }
  renderSelectionBar();
  const q = $("#doc-search").value.trim();
  const docs = filteredDocs();
  $("#doc-count").textContent = q ? `${docs.length} of ${state.docs.length}` : String(state.docs.length);
  if (!state.docs.length) {
    wrap.innerHTML = `<div class="table-empty"><strong>No documents yet</strong>Drop files above, or ingest a folder with <code>omnirag ingest PATH --kb ${esc(state.kb)}</code>.</div>`;
    return;
  }
  if (!docs.length) {
    wrap.innerHTML = `<div class="table-empty"><strong>No matches</strong>Nothing matches “${esc(q)}”.</div>`;
    return;
  }
  const allOn = docs.every((d) => state.scope.has(d.doc_id));
  const someOn = docs.some((d) => state.scope.has(d.doc_id));
  wrap.innerHTML = `<table class="doc-table">
    <thead><tr><th class="c-check"><input type="checkbox" id="lib-all" aria-label="Select all ${q ? "matching " : ""}documents" ${allOn ? "checked" : ""}></th>
      <th>Name</th><th>Type</th><th class="num">Chunks</th><th class="num">Size</th><th>Ingested</th><th><span class="sr-only">Actions</span></th></tr></thead>
    <tbody>${docs
      .map((d) => {
        const on = state.scope.has(d.doc_id);
        return `<tr${on ? ' class="selected"' : ""}>
        <td class="c-check"><input type="checkbox" data-scope-doc="${esc(d.doc_id)}" aria-label="Select ${esc(d.name)}" ${on ? "checked" : ""}></td>
        <td class="c-name"><button type="button" class="doc-name" data-open-doc="${esc(d.doc_id)}" title="${esc(d.source)}"><strong>${esc(d.name)}${d.missing ? '<span class="doc-flag">missing</span>' : ""}</strong>${d.path !== d.name ? `<span>${esc(d.path)}</span>` : d.title && d.title !== d.name ? `<span>${esc(d.title)}</span>` : ""}</button></td>
        <td class="hide-sm"><span class="type-cell">${mIcon(d.modality)}${esc(d.modality)}</span></td>
        <td class="num hide-sm">${d.chunks}</td>
        <td class="num hide-sm">${formatBytes(d.size_bytes)}</td>
        <td class="hide-sm"><span class="doc-time" title="${esc(exactTime(d.updated_at))}">${esc(relativeTime(d.updated_at))}</span></td>
        <td class="c-meta">${mIcon(d.modality)}${esc(d.modality)} · ${plural(d.chunks, "chunk")} · ${formatBytes(d.size_bytes)}</td>
        <td class="c-actions"><div class="doc-actions">
          <button class="icon-btn sm" type="button" data-reingest="${esc(d.doc_id)}" aria-label="Re-ingest ${esc(d.name)}" title="Re-ingest"${d.missing ? " disabled" : ""}>${icon("refresh")}</button>
          <button class="icon-btn sm danger" type="button" data-delete-doc="${esc(d.doc_id)}" aria-label="Delete ${esc(d.name)}" title="Delete">${icon("trash")}</button>
        </div></td>
      </tr>`;
      })
      .join("")}</tbody></table>`;
  const all = $("#lib-all");
  all.indeterminate = someOn && !allOn;
}

async function deleteDoc(docId) {
  const d = state.docs?.find((x) => x.doc_id === docId);
  if (!d) return;
  const ok = await confirmAction({
    title: `Delete ${d.name}?`,
    body: `Its ${plural(d.chunks, "chunk")} are removed from ${state.kb}. ${d.uploaded ? "The uploaded copy is deleted too." : "The source file on disk is not touched."}`,
    ok: "Delete document",
  });
  if (!ok) return;
  try {
    await api(`${kbPath()}/documents/${encodeURIComponent(docId)}`, { method: "DELETE" });
    state.docs = state.docs.filter((x) => x.doc_id !== docId);
    if (state.scope.delete(docId)) saveScope();
    if (state.drawer?.mode === "doc" && state.drawer.docId === docId) closeDrawer();
    renderDocs();
    renderComposerContext();
    toast(`Deleted ${d.name}`);
    afterLibraryChange();
  } catch (err) {
    toast(err.message, { error: true });
  }
}

async function reingestDoc(docId, button) {
  const d = state.docs?.find((x) => x.doc_id === docId);
  button.disabled = true;
  button.dataset.busy = "true";
  try {
    const r = await api(`${kbPath()}/documents/${encodeURIComponent(docId)}/reingest`, { method: "POST" });
    const failed = Object.values(r.report.failed)[0];
    if (failed) toast(`Re-ingest failed: ${failed}`, { error: true });
    else toast(`Re-ingested ${d?.name || "document"} · ${plural(r.document.chunks, "chunk")}`);
    await loadDocs();
    afterLibraryChange();
  } catch (err) {
    toast(err.message, { error: true });
    button.disabled = false;
  }
}

async function afterLibraryChange() {
  state.starters = null;
  await loadKbs();
  try {
    state.stats = await api(`${kbPath()}/stats`);
  } catch {
    /* keep old stats */
  }
  renderTopbar();
}

function uploadOne(file, item) {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("files", file, file.name);
    xhr.open("POST", `${kbPath()}/upload`);
    for (const [k, v] of Object.entries(authHeaders())) xhr.setRequestHeader(k, v);
    const bar = item.querySelector("progress");
    const stateEl = item.querySelector(".ustate");
    xhr.upload.addEventListener("progress", (e) => {
      if (!e.lengthComputable) return;
      bar.value = e.loaded / e.total;
      stateEl.textContent = e.loaded >= e.total ? "Indexing…" : `${Math.round((e.loaded / e.total) * 100)}%`;
    });
    xhr.addEventListener("load", async () => {
      let data = {};
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch {
        /* non-JSON error */
      }
      if (xhr.status === 401) {
        await requestApiKey(true);
        resolve(uploadOne(file, item));
        return;
      }
      if (xhr.status >= 400) {
        item.dataset.state = "error";
        stateEl.textContent = detailText(data.detail) || `Upload failed (${xhr.status})`;
        resolve(false);
        return;
      }
      const f = data.files?.[0] || {};
      if (f.status === "failed") {
        item.dataset.state = "error";
        stateEl.textContent = `Could not ingest: ${f.error}`;
      } else {
        item.dataset.state = "done";
        stateEl.textContent =
          f.status === "unchanged" ? "Unchanged · already indexed" : `${f.status === "updated" ? "Updated" : "Added"} · ${plural(f.chunks, "chunk")}`;
      }
      resolve(f.status !== "failed");
    });
    xhr.addEventListener("error", () => {
      item.dataset.state = "error";
      stateEl.textContent = "Network error";
      resolve(false);
    });
    xhr.send(form);
  });
}

async function uploadFiles(fileList) {
  if (!state.kb) return;
  const files = [...fileList];
  if (!files.length) return;
  const allowed = new Set(state.status?.upload_extensions || []);
  const max = (state.status?.max_upload_mb || 50) * 1024 * 1024;
  const list = $("#uploads");
  const jobs = [];
  for (const file of files) {
    const item = document.createElement("li");
    item.className = "upload-item";
    item.innerHTML = `<span class="uname" title="${esc(file.name)}">${esc(file.name)}</span><span class="ustate">Waiting</span><progress max="1" value="0"></progress>`;
    list.prepend(item);
    const ext = file.name.includes(".") ? `.${file.name.split(".").pop().toLowerCase()}` : "";
    if (allowed.size && !allowed.has(ext)) {
      item.dataset.state = "error";
      item.querySelector(".ustate").textContent = `Unsupported type${ext ? ` (${ext})` : ""}`;
      continue;
    }
    if (file.size > max) {
      item.dataset.state = "error";
      item.querySelector(".ustate").textContent = `Larger than ${state.status.max_upload_mb} MB`;
      continue;
    }
    jobs.push([file, item]);
  }
  let changed = 0;
  for (const [file, item] of jobs) {
    item.dataset.state = "uploading";
    item.querySelector(".ustate").textContent = "Uploading…";
    if (await uploadOne(file, item)) changed += 1;
  }
  if (changed) {
    await loadDocs();
    afterLibraryChange();
  }
}

// ---------------------------------------------------------------- settings
async function loadSettings() {
  renderKeyRow();
  const form = $("#settings-form");
  form.hidden = !state.kb;
  $(".card-danger").hidden = !state.kb;
  if (state.status) renderStatusGrid();
  if (!state.kb) return;
  const name = state.kb;
  try {
    const prefs = await api(`${kbPath(name)}/settings`);
    if (name !== state.kb) return;
    const radio = $(`#llm-backend input[value="${prefs.llm}"]`);
    if (radio) radio.checked = true;
    $("#llm-model").value = prefs.model;
    $("#llm-url").value = prefs.base_url;
    $("#top-k").value = prefs.top_k;
    $("#settings-msg").textContent = "";
    updateLlmFields();
  } catch (err) {
    $("#settings-msg").className = "form-msg error";
    $("#settings-msg").textContent = err.message;
  }
}

function updateLlmFields() {
  const backend = $("#llm-backend input:checked")?.value ?? "";
  const d = state.status?.defaults;
  const needsModel = backend === "ollama" || backend === "openai";
  $("#llm-model").disabled = !needsModel;
  $("#llm-url").disabled = !needsModel;
  const def = needsModel && d ? d[backend] : null;
  $("#llm-model").placeholder = def ? def.model : "not used";
  $("#llm-url").placeholder = def ? def.base_url : "not used";
  const help = {
    "": `Uses the server's OMNIRAG_LLM setting${d ? ` (currently “${d.llm}”)` : ""}.`,
    none: "Offline: answers are assembled from the most relevant source sentences. No model server needed.",
    ollama: "A local Ollama server writes the answer. Leave fields empty to use OLLAMA_HOST and OMNIRAG_OLLAMA_MODEL.",
    openai: "Any /chat/completions endpoint (OpenAI, vLLM, LM Studio, llama.cpp). The key comes from OPENAI_API_KEY.",
  }[backend];
  $("#llm-help").textContent = help;
  const models = state.status?.llm?.backend === backend ? state.status.llm.models : [];
  $("#model-options").innerHTML = (models || []).map((m) => `<option value="${esc(m)}"></option>`).join("");
}

async function saveSettings(event) {
  event.preventDefault();
  const msg = $("#settings-msg");
  const topK = Number($("#top-k").value);
  if (!Number.isInteger(topK) || topK < 1 || topK > 50) {
    $("#top-k").setAttribute("aria-invalid", "true");
    msg.className = "form-msg error";
    msg.textContent = "Top-k must be a whole number from 1 to 50.";
    $("#top-k").focus();
    return;
  }
  $("#top-k").removeAttribute("aria-invalid");
  const body = {
    llm: $("#llm-backend input:checked")?.value ?? "",
    model: $("#llm-model").disabled ? "" : $("#llm-model").value.trim(),
    base_url: $("#llm-url").disabled ? "" : $("#llm-url").value.trim(),
    top_k: topK,
  };
  const btn = $("#settings-save");
  btn.disabled = true;
  msg.className = "form-msg";
  msg.textContent = "Saving…";
  try {
    await api(`${kbPath()}/settings`, { method: "PUT", body });
    msg.className = "form-msg ok";
    msg.textContent = "Saved. Checking the endpoint…";
    await loadStatus();
    msg.textContent = "Saved.";
  } catch (err) {
    msg.className = "form-msg error";
    msg.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}

function renderStatusGrid() {
  const s = state.status;
  const grid = $("#status-grid");
  if (!s) {
    grid.innerHTML = `<dt>Status</dt><dd><span class="thinking">Checking…</span></dd>`;
    return;
  }
  if (s.error) {
    grid.innerHTML = `<dt>Server</dt><dd><span class="dot" data-state="down"></span>${esc(s.error)}</dd>`;
    return;
  }
  const llm = s.llm;
  let reach;
  if (llm.backend === "none") reach = `<span class="dot" data-state="offline"></span>Not needed — answers are extractive`;
  else if (llm.reachable)
    reach = `<span class="dot" data-state="ok"></span>Reachable${llm.latency_ms != null ? ` · ${Math.round(llm.latency_ms)} ms` : ""}${llm.detail ? ` · ${esc(llm.detail)}` : ""}`;
  else reach = `<span class="dot" data-state="down"></span>Not reachable${llm.detail ? ` — <span class="mono">${esc(llm.detail)}</span>` : ""}`;
  const emb = s.embedder;
  grid.innerHTML = `
    <dt>Answer backend</dt><dd>${esc(llmLabel(llm))}<span class="badge">${llm.source === "kb" ? "this knowledge base" : "server default"}</span></dd>
    ${llm.backend !== "none" ? `<dt>Endpoint</dt><dd class="mono">${esc(llm.base_url)}</dd>` : ""}
    <dt>Reachability</dt><dd>${reach}</dd>
    <dt>Embedder</dt><dd>${emb ? `<span class="mono">${esc(emb.spec)}</span>${emb.dimension ? `<span class="badge">${emb.dimension} dims</span>` : ""}${emb.offline ? '<span class="badge">offline</span>' : ""}` : "—"}</dd>
    <dt>Server</dt><dd>OmniRAG ${esc(s.version)} · ${s.auth_required ? "API key required" : "no API key"} · uploads up to ${s.max_upload_mb} MB</dd>`;
  updateLlmFields();
}

// --------------------------------------------------------- command palette
const SHORTCUTS = [
  [`${MOD} K`, "Open the command palette"],
  ["/", "Focus the question box"],
  ["N", "New chat"],
  ["S", "Choose sources (scope the chat)"],
  ["G then C", "Go to Chat"],
  ["G then L", "Go to Library"],
  ["G then S", "Go to Settings"],
  ["Enter", "Send the question"],
  ["Shift Enter", "New line in the question"],
  ["← →", "Switch answer tabs (when a tab is focused)"],
  ["Esc", "Stop generating, close panels and menus"],
  ["?", "Show these shortcuts"],
];

function paletteCommands() {
  const cmds = [];
  const add = (group, label, run, extra = {}) => cmds.push({ group, label, run, ...extra });
  if (palette.mode === "kb") {
    for (const k of state.kbs || []) {
      const current = k.name === state.kb;
      add("Knowledge bases", k.name, () => switchKb(k.name), { icon: current ? "check" : "db", meta: `${plural(k.documents, "doc")}${current ? " · current" : ""}` });
    }
    add("Knowledge bases", "Create knowledge base…", openKbDialog, { icon: "plus" });
    return cmds;
  }
  add("Actions", "New chat", newChat, { icon: "compose", hint: "N" });
  add("Actions", "Focus the question box", focusComposer, { icon: "chat", hint: "/" });
  if (state.kb) add("Actions", "Choose sources…", () => (state.view === "chat" ? openScopePanel() : ((location.hash = "#/chat"), setTimeout(openScopePanel, 0))), { icon: "layers", hint: "S" });
  if (state.scope.size) add("Actions", `Clear source scope (${plural(state.scope.size, "source")})`, clearScope, { icon: "close" });
  add("Actions", `Toggle theme (now ${currentTheme()})`, cycleTheme, { icon: currentTheme() === "dark" ? "moon" : currentTheme() === "light" ? "sun" : "auto" });
  add("Actions", "Keyboard shortcuts", openShortcuts, { icon: "keyboard", hint: "?" });
  add("Actions", "Create knowledge base…", openKbDialog, { icon: "plus" });
  add("Go to", "Chat", () => (location.hash = "#/chat"), { icon: "chat", hint: "G C" });
  add("Go to", "Library", () => (location.hash = "#/library"), { icon: "library", hint: "G L" });
  add("Go to", "Settings", () => (location.hash = "#/settings"), { icon: "settings", hint: "G S" });
  for (const k of state.kbs || []) {
    if (k.name === state.kb) continue;
    add("Knowledge bases", `Switch to ${k.name}`, () => switchKb(k.name), { icon: "db", meta: plural(k.documents, "doc") });
  }
  for (const d of state.docsKb === state.kb ? state.docs || [] : []) {
    add("Documents", d.name, () => openDocPanel(d.doc_id), { icon: `m-${d.modality}`, meta: d.path !== d.name ? d.path : d.modality, doc: true });
  }
  for (const c of kbChats()) {
    if (c.id === state.chatId) continue;
    add("Conversations", c.title, () => openChat(c.id), { icon: "chat", chat: true });
  }
  return cmds;
}

/** Subsequence match score (higher is better), or -1. */
function fuzzy(text, query) {
  if (!query) return 0;
  const t = text.toLowerCase();
  const q = query.toLowerCase();
  const at = t.indexOf(q);
  if (at >= 0) return 100 - at + (at === 0 || /\W/.test(t[at - 1]) ? 50 : 0);
  let ti = 0;
  let score = 0;
  for (const ch of q) {
    const found = t.indexOf(ch, ti);
    if (found < 0) return -1;
    score += found === ti ? 2 : 0;
    ti = found + 1;
  }
  return score;
}

const palette = { items: [], active: 0, opener: null, mode: "all" };

function openPalette(mode = "all") {
  const dialog = $("#palette");
  palette.mode = mode;
  palette.opener = document.activeElement;
  closeSidebar();
  hideCiteCard();
  openDialog(dialog);
  const input = $("#palette-input");
  input.value = "";
  input.placeholder = mode === "kb" ? "Switch knowledge base" : "Type a command, document or knowledge base";
  renderPalette();
  input.focus();
  if (state.kb) loadDocs();
}

function renderPalette() {
  const query = $("#palette-input").value.trim();
  let items = paletteCommands()
    .map((c) => ({ ...c, score: fuzzy(`${c.label} ${c.meta || ""}`, query) }))
    .filter((c) => c.score >= 0);
  if (query) items.sort((a, b) => b.score - a.score);
  else {
    // Without a query keep it short: a few documents and conversations.
    const caps = { Documents: 5, Conversations: 4 };
    const seen = {};
    items = items.filter((c) => (seen[c.group] = (seen[c.group] || 0) + 1) <= (caps[c.group] ?? 99));
  }
  items = items.slice(0, 40);
  palette.items = items;
  palette.active = Math.min(palette.active, Math.max(0, items.length - 1));
  if (!query) palette.active = 0;
  const list = $("#palette-list");
  if (!items.length) {
    list.innerHTML = `<li class="palette-empty" role="presentation">No matches for “${esc(query)}”</li>`;
    $("#palette-input").removeAttribute("aria-activedescendant");
    return;
  }
  let group = "";
  let html = "";
  items.forEach((c, i) => {
    if (!query && c.group !== group) {
      group = c.group;
      html += `<li class="palette-group" role="presentation">${esc(group)}</li>`;
    }
    html += `<li class="palette-item" role="option" id="pal-${i}" data-index="${i}" aria-selected="${i === palette.active}">
      ${icon(c.icon || "arrow-right")}<span class="pi-label">${esc(c.label)}</span>${c.meta ? `<span class="pi-meta">${esc(c.meta)}</span>` : ""}${query ? `<span class="pi-group">${esc(c.group)}</span>` : ""}${c.hint ? `<kbd>${esc(c.hint)}</kbd>` : ""}</li>`;
  });
  list.innerHTML = html;
  setPaletteActive(palette.active);
}

function setPaletteActive(i) {
  palette.active = i;
  for (const el of $$("#palette-list .palette-item")) el.setAttribute("aria-selected", String(+el.dataset.index === i));
  const el = $(`#pal-${i}`);
  if (el) {
    $("#palette-input").setAttribute("aria-activedescendant", el.id);
    el.scrollIntoView({ block: "nearest" });
  }
}

function runPalette(i) {
  const cmd = palette.items[i];
  if (!cmd) return;
  $("#palette").close();
  palette.opener = null;
  cmd.run();
}

function bindPalette() {
  const input = $("#palette-input");
  input.addEventListener("input", () => {
    palette.active = 0;
    renderPalette();
  });
  input.addEventListener("keydown", (e) => {
    const n = palette.items.length;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (n) setPaletteActive((palette.active + 1) % n);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (n) setPaletteActive((palette.active - 1 + n) % n);
    } else if (e.key === "Enter") {
      e.preventDefault();
      runPalette(palette.active);
    }
  });
  $("#palette-list").addEventListener("click", (e) => {
    const item = e.target.closest(".palette-item");
    if (item) runPalette(+item.dataset.index);
  });
  $("#palette-list").addEventListener("pointermove", (e) => {
    const item = e.target.closest(".palette-item");
    if (item && +item.dataset.index !== palette.active) setPaletteActive(+item.dataset.index);
  });
  const dialog = $("#palette");
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) dialog.close(); // backdrop
  });
  dialog.addEventListener("close", () => {
    if (palette.opener?.isConnected) palette.opener.focus();
    palette.opener = null;
  });
}

function openShortcuts() {
  $("#shortcut-list").innerHTML = SHORTCUTS.map(
    ([keys, label]) => `<div><dt>${keys
      .split(" ")
      .map((k) => (k === "then" ? '<span class="then">then</span>' : `<kbd>${esc(k)}</kbd>`))
      .join("")}</dt><dd>${esc(label)}</dd></div>`,
  ).join("");
  openDialog($("#shortcuts-dialog"));
}

function focusComposer() {
  if (state.view !== "chat") location.hash = "#/chat";
  setTimeout(() => $("#question").focus(), 0);
}

// ------------------------------------------------------------------ mobile
function openSidebar() {
  $("#app").classList.add("sidebar-open");
  $("#scrim").hidden = false;
  $("#open-sidebar").setAttribute("aria-expanded", "true");
  $("#close-sidebar").focus();
}
function closeSidebar() {
  if (!$("#app").classList.contains("sidebar-open")) return;
  $("#app").classList.remove("sidebar-open");
  if (!(state.drawer && isSheet())) $("#scrim").hidden = true;
  $("#open-sidebar").setAttribute("aria-expanded", "false");
}

// ------------------------------------------------------------------ events
function bindEvents() {
  window.addEventListener("hashchange", () => showView(viewFromHash()));

  document.addEventListener("click", (e) => {
    const t = e.target.closest("button, a");
    if (!t || t.closest("#palette")) return;
    const d = t.dataset;
    if (d.kb) {
      switchKb(d.kb);
      closeSidebar();
    } else if (d.deleteKb) deleteKb(d.deleteKb);
    else if (d.openChat) {
      openChat(d.openChat);
      closeSidebar();
    } else if (d.deleteChat) deleteChat(d.deleteChat);
    else if (d.cites && d.msg !== undefined) openSource(+d.msg, +d.cites.split(",")[0]);
    else if (d.cite && d.msg !== undefined && !t.disabled) openSource(+d.msg, +d.cite);
    else if (d.tab && d.msg !== undefined) setTab(+d.msg, d.tab, t.getAttribute("role") === "tab");
    else if (d.copy !== undefined) copyAnswer(+d.copy, t);
    else if (d.filter !== undefined) toggleFilter(d.filter);
    else if (d.ask) ask(d.ask);
    else if (d.askDoc) askAboutDoc(d.askDoc);
    else if (d.scopeToggle) toggleScope(d.scopeToggle);
    else if (d.openDoc) openDocPanel(d.openDoc);
    else if (d.openRaw) openRaw(d.openRaw, state.drawer?.chatId ? currentChat()?.kb : state.kb);
    else if (d.deleteDoc) deleteDoc(d.deleteDoc);
    else if (d.reingest) reingestDoc(d.reingest, t);
    else if (d.action === "new-kb") openKbDialog();
    else if (d.action === "reload-docs") loadDocs();
    else if (d.action === "open-scope") openScopePanel();
    else if (d.action === "clear-scope") clearScope();
    else if (d.action === "scope-done") closeDrawer();
    else if (d.action === "chat-scope") {
      if (currentChat()?.messages.length) state.chatId = null;
      location.hash = "#/chat";
      renderChatList();
      focusComposer();
    } else if (d.close !== undefined) t.closest("dialog")?.close("cancel");
    else if (t.id === "new-chat-top" || t.id === "new-chat-side") {
      newChat();
      closeSidebar();
    } else if (t.id === "toggle-scope") toggleScopePanel();
    else if (t.id === "topbar-kb") openPalette("kb");
    else if (t.classList.contains("nav-link")) closeSidebar();
  });

  // Checkboxes that select documents (library table, sources panel).
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset?.scopeDoc) toggleScope(t.dataset.scopeDoc, t.checked);
    else if (t.id === "lib-all") {
      const ids = filteredDocs().map((d) => d.doc_id);
      const next = new Set(state.scope);
      for (const id of ids) t.checked ? next.add(id) : next.delete(id);
      setScope(next);
    } else if (t.id === "scope-all") {
      const q = ($("#scope-search")?.value || "").trim().toLowerCase();
      const ids = (state.docs || []).filter((d) => !q || `${d.name} ${d.path} ${d.title} ${d.modality}`.toLowerCase().includes(q)).map((d) => d.doc_id);
      const next = new Set(state.scope);
      for (const id of ids) t.checked ? next.add(id) : next.delete(id);
      setScope(next);
    }
  });
  document.addEventListener("input", (e) => {
    if (e.target.id === "scope-search") renderScopePanel();
  });

  // Arrow keys move between answer tabs (WAI-ARIA tabs pattern).
  $("#thread").addEventListener("keydown", (e) => {
    const tab = e.target.closest?.('[role="tab"]');
    if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const tabs = $$('[role="tab"]', tab.parentElement);
    let i = tabs.indexOf(tab);
    if (e.key === "ArrowLeft") i = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === "ArrowRight") i = (i + 1) % tabs.length;
    else if (e.key === "Home") i = 0;
    else i = tabs.length - 1;
    setTab(+tab.dataset.msg, tabs[i].dataset.tab, true);
  });

  $("#new-kb").addEventListener("click", openKbDialog);
  $("#kb-form").addEventListener("submit", createKb);
  $("#delete-kb-settings").addEventListener("click", () => state.kb && deleteKb(state.kb));
  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#open-sidebar").addEventListener("click", openSidebar);
  $("#close-sidebar").addEventListener("click", closeSidebar);
  $("#scrim").addEventListener("click", () => {
    closeSidebar();
    if (isSheet()) closeDrawer();
  });
  $("#open-palette").addEventListener("click", () => openPalette());
  $("#open-shortcuts").addEventListener("click", openShortcuts);
  $("#status-pill").addEventListener("click", () => (location.hash = "#/settings"));
  $("#status-refresh").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    state.status = null;
    renderStatusGrid();
    await loadStatus();
    btn.disabled = false;
  });
  $("#theme-toggle").addEventListener("click", () => setTheme(THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length]));
  $("#theme-choice").addEventListener("change", (e) => setTheme(e.target.value));
  $("#forget-key").addEventListener("click", () => {
    store.remove("omnirag.apiKey");
    renderKeyRow();
    requestApiKey();
  });
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#llm-backend").addEventListener("change", updateLlmFields);

  const q = $("#question");
  q.addEventListener("input", autosize);
  q.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      $("#composer").requestSubmit();
    }
  });
  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    if (state.controller) {
      stopStreaming();
      return;
    }
    const text = q.value.trim();
    if (!text || !state.kb) return;
    q.value = "";
    autosize();
    ask(text);
  });

  $("#doc-search").addEventListener("input", renderDocs);
  $("#file-input").addEventListener("change", (e) => {
    uploadFiles(e.target.files);
    e.target.value = "";
  });
  const zone = $("#dropzone");
  let depth = 0;
  zone.addEventListener("dragenter", (e) => {
    e.preventDefault();
    depth += 1;
    zone.classList.add("dragging");
  });
  zone.addEventListener("dragover", (e) => e.preventDefault());
  zone.addEventListener("dragleave", () => {
    depth -= 1;
    if (depth <= 0) zone.classList.remove("dragging");
  });
  zone.addEventListener("drop", (e) => {
    e.preventDefault();
    depth = 0;
    zone.classList.remove("dragging");
    uploadFiles(e.dataTransfer.files);
  });
  // Dropping a file anywhere else should not navigate away from the app.
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => e.preventDefault());

  let chord = 0; // timestamp of a pending "g" chord
  document.addEventListener("keydown", (e) => {
    const typing = e.target.closest?.("input, textarea, select, [contenteditable]");
    const dialogOpen = document.querySelector("dialog[open]");
    if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "k") {
      e.preventDefault();
      const pal = $("#palette");
      if (pal.open) pal.close();
      else if (!dialogOpen) openPalette();
      return;
    }
    if (dialogOpen) return;
    if (e.key === "Escape") {
      if (cardPill) hideCiteCard();
      else if (state.controller && !typing) stopStreaming();
      else if ($("#app").classList.contains("sidebar-open")) closeSidebar();
      else if (state.drawer) closeDrawer();
      return;
    }
    if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
    const key = e.key.toLowerCase();
    if (chord && Date.now() - chord < 1200) {
      chord = 0;
      const to = { c: "chat", l: "library", s: "settings" }[key];
      if (to) {
        e.preventDefault();
        location.hash = `#/${to}`;
      }
      return;
    }
    if (e.key === "?") {
      e.preventDefault();
      openShortcuts();
    } else if (e.key === "/") {
      e.preventDefault();
      focusComposer();
    } else if (key === "g") chord = Date.now();
    else if (key === "n") {
      e.preventDefault();
      newChat();
    } else if (key === "s" && state.kb) {
      e.preventDefault();
      if (state.view !== "chat") location.hash = "#/chat";
      toggleScopePanel();
    }
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => applyTheme(currentTheme()));
  window.matchMedia("(max-width: 1180px)").addEventListener?.("change", () => {
    if (state.drawer) $("#scrim").hidden = !isSheet() && !$("#app").classList.contains("sidebar-open");
  });
}

// -------------------------------------------------------------------- boot
async function boot() {
  applyTheme(currentTheme());
  $("#version").textContent = `v${state.version}`;
  for (const k of $$("[data-mod]")) k.textContent = `${MOD} K`;
  renderFilters();
  renderKbList();
  bindEvents();
  bindPalette();
  bindCiteCard();
  showView(viewFromHash());
  try {
    state.health = await (await fetch("/api/health")).json();
  } catch {
    state.health = null;
  }
  if (state.health?.auth_required && !store.get("omnirag.apiKey")) await requestApiKey();
  await loadKbs();
  state.chatId = null; // start on the home screen; past chats are in the sidebar
  renderChatList();
  renderComposerContext();
  renderTopbar();
  renderView();
  await refreshKb();
  updateSendEnabled();
}

boot();
