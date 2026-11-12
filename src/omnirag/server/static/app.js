// OmniRAG web app. Plain ES module, no build step.
import { escapeHtml as esc, renderMarkdown } from "./markdown.js";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const MODALITIES = ["text", "code", "table", "image", "audio"];
const MODALITY_LABEL = { text: "Text", code: "Code", table: "Tables", image: "Images", audio: "Audio" };
const VIEWS = { chat: "Chat", library: "Library", settings: "Settings" };
const CHATS_KEY = "omnirag.chats.v1";
const MAX_CHATS = 40;

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
  docsError: null,
  status: null,
  view: "chat",
  chats: store.get(CHATS_KEY, []),
  chatId: null,
  filters: new Set(),
  controller: null,
  preview: null, // {chatId, index, n}
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
function icon(name) {
  return `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

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

const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
function relativeTime(iso) {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const secs = (t - Date.now()) / 1000;
  const steps = [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
    [4.35, "week"],
    [12, "month"],
    [Infinity, "year"],
  ];
  let v = secs;
  for (const [size, unit] of steps) {
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
function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  const btn = $("#theme-toggle");
  const iconName = theme === "light" ? "sun" : theme === "dark" ? "moon" : "auto";
  btn.innerHTML = icon(iconName);
  btn.setAttribute("aria-label", `Theme: ${theme}. Change theme`);
  btn.title = `Theme: ${theme}`;
  const radio = $(`#theme-choice input[value="${theme}"]`);
  if (radio) radio.checked = true;
}
function setTheme(theme) {
  store.set("omnirag.theme", theme);
  applyTheme(theme);
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
  closePreview();
  renderChatList();
  renderThread();
  if (state.view !== "chat") location.hash = "#/chat";
  $("#question").focus();
}

function openChat(id) {
  stopStreaming();
  state.chatId = id;
  closePreview();
  renderChatList();
  renderThread(true);
  if (state.view !== "chat") location.hash = "#/chat";
}

async function deleteChat(id) {
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
  const chats = kbChats();
  if (!state.kb) {
    list.innerHTML = "";
    return;
  }
  if (!chats.length) {
    list.innerHTML = `<li class="side-empty">No conversations yet.</li>`;
    return;
  }
  list.innerHTML = chats
    .map(
      (c) => `<li class="side-item" ${c.id === state.chatId ? 'aria-current="true"' : ""}>
        <button type="button" data-open-chat="${esc(c.id)}"><span class="label">${esc(c.title)}</span></button>
        <button class="icon-btn danger" type="button" data-delete-chat="${esc(c.id)}" aria-label="Delete conversation ${esc(c.title)}">${icon("trash")}</button>
      </li>`,
    )
    .join("");
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
    list.innerHTML = `<li class="side-empty">No knowledge bases yet.</li>`;
    return;
  }
  list.innerHTML = state.kbs
    .map(
      (k) => `<li class="side-item" ${k.name === state.kb ? 'aria-current="true"' : ""}>
        <button type="button" data-kb="${esc(k.name)}" title="${esc(k.description || k.name)}">
          <svg class="kb-glyph" aria-hidden="true"><use href="#i-db"/></svg>
          <span class="label">${esc(k.name)}</span>
          <span class="meta" aria-label="${plural(k.documents, "document")}">${k.documents}</span>
        </button>
        <button class="icon-btn danger" type="button" data-delete-kb="${esc(k.name)}" aria-label="Delete knowledge base ${esc(k.name)}">${icon("trash")}</button>
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
  state.chatId = kbChats()[0]?.id ?? null;
  closePreview();
  renderKbList();
  renderChatList();
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
  if (state.view === "chat" && !currentChat()) renderThread();
  if (state.view === "library") loadDocs();
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
  for (const a of $$(".nav-link")) {
    if (a.dataset.nav === view) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  if (view !== "chat") closePreview();
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
  document.title = `${VIEWS[state.view]} · OmniRAG`;
  const kbEl = $("#topbar-kb");
  if (!state.kb) kbEl.textContent = "";
  else {
    const s = state.stats;
    kbEl.innerHTML = `<strong>${esc(state.kb)}</strong>${s ? ` · ${plural(s.documents, "document")} · ${plural(s.chunks, "chunk")}` : ""}`;
  }
  const actions = $("#topbar-actions");
  actions.innerHTML =
    state.view === "chat" && state.kb
      ? `<button class="btn btn-ghost" type="button" id="new-chat-top">${icon("plus")}<span>New chat</span></button>`
      : "";
  for (const el of $$(".kb-name-ref")) el.textContent = state.kb || "";
}

// --------------------------------------------------------------- chat view
function renderFilters() {
  const box = $("#filters");
  const all = state.filters.size === 0;
  box.innerHTML =
    `<button type="button" class="filter-chip" data-filter="" aria-pressed="${all}">All sources</button>` +
    MODALITIES.map(
      (m) =>
        `<button type="button" class="filter-chip" data-filter="${m}" aria-pressed="${state.filters.has(m)}"><span class="mdot" data-m="${m}"></span>${MODALITY_LABEL[m]}</button>`,
    ).join("");
}

function toggleFilter(m) {
  if (!m) state.filters.clear();
  else if (state.filters.has(m)) state.filters.delete(m);
  else state.filters.add(m);
  renderFilters();
}

function suggestionsFor(docs) {
  const picks = [];
  const seen = new Set();
  for (const d of docs) {
    if (seen.has(d.modality) || picks.length >= 4) continue;
    seen.add(d.modality);
    const name = d.title || d.name;
    const q = {
      text: `Summarise “${name}”`,
      code: `How does ${d.name} work?`,
      table: `What does ${d.name} contain?`,
      image: `What does ${d.name} show?`,
      audio: `Summarise the ${name} transcript`,
    }[d.modality];
    if (q) picks.push({ q, d });
  }
  return picks;
}

function renderEmptyThread() {
  const thread = $("#thread");
  if (state.kbs === null) {
    thread.innerHTML = `<div class="empty-state"><span class="thinking">Loading…</span></div>`;
    return;
  }
  if (!state.kb) {
    thread.innerHTML = `<div class="empty-state">
      <h2>Create a knowledge base</h2>
      <p>A knowledge base holds the documents, code, tables, images and transcripts OmniRAG answers from. Everything stays on this server.</p>
      <div class="empty-actions"><button class="btn btn-primary" type="button" data-action="new-kb">${icon("plus")}New knowledge base</button></div>
    </div>`;
    return;
  }
  const s = state.stats;
  if (s && s.documents === 0) {
    thread.innerHTML = `<div class="empty-state">
      <h2>${esc(state.kb)} is empty</h2>
      <p>Add files in the library, then ask questions about them here. Answers cite the exact chunk, line range, table rows or timestamp they came from.</p>
      <div class="empty-actions"><a class="btn btn-primary" href="#/library">${icon("upload")}Add files</a></div>
    </div>`;
    return;
  }
  const facts = s
    ? MODALITIES.filter((m) => s.documents_by_modality?.[m])
        .map(
          (m) =>
            `<span class="kb-fact"><span class="mdot" data-m="${m}"></span><b>${s.documents_by_modality[m]}</b> ${MODALITY_LABEL[m].toLowerCase()}</span>`,
        )
        .join("")
    : "";
  thread.innerHTML = `<div class="empty-state">
    <h2>Ask ${esc(state.kb)}</h2>
    <p>Answers are built only from this knowledge base, with numbered citations you can open to see the source.</p>
    ${facts ? `<div class="kb-facts">${facts}<span class="kb-fact">embedder <b>${esc(s.embedder)}</b></span></div>` : ""}
    <div class="suggestions" id="suggestions"></div>
  </div>`;
  loadSuggestions();
}

async function loadSuggestions() {
  const name = state.kb;
  try {
    const docs = state.docs && state.docsKb === name ? state.docs : await api(`${kbPath(name)}/documents`);
    if (name !== state.kb) return;
    state.docs = docs;
    state.docsKb = name;
    const box = $("#suggestions");
    if (!box) return;
    box.innerHTML = suggestionsFor(docs)
      .map(
        ({ q, d }) =>
          `<button class="suggestion" type="button" data-ask="${esc(q)}"><span>${esc(q)}</span><small>${esc(d.path)}</small></button>`,
      )
      .join("");
  } catch {
    /* suggestions are optional */
  }
}

function citeButton(msgIndex, sources) {
  return (n) => {
    const known = sources?.some((s) => s.index === n);
    return `<button type="button" class="cite${known ? "" : " missing"}" data-cite="${n}" data-msg="${msgIndex}" aria-label="Source ${n}"${known ? "" : " disabled"}>${n}</button>`;
  };
}

function renderAnswerInner(msg, index) {
  const parts = [];
  const streaming = msg.pending && !msg.error;
  if (!msg.text && streaming) {
    parts.push(
      `<span class="thinking">${msg.sources ? `Writing from ${plural(msg.sources.length, "source")}…` : "Searching the knowledge base…"}</span>`,
    );
  } else if (msg.text) {
    parts.push(
      `<div class="answer-body${streaming ? " streaming" : ""}">${renderMarkdown(msg.text, { cite: citeButton(index, msg.sources) })}</div>`,
    );
  }
  if (msg.error) parts.push(`<div class="notice error">${esc(msg.error)}</div>`);
  if (msg.stopped) parts.push(`<div class="notice">Stopped. The answer above is incomplete.</div>`);
  for (const w of msg.warnings || []) parts.push(`<div class="notice">${esc(w)}</div>`);
  if (msg.sources?.length) {
    const cited = new Set(msg.cited || []);
    const chip = (s) => `<button type="button" class="source-chip${cited.has(s.index) ? " cited" : ""}" data-cite="${s.index}" data-msg="${index}" title="${esc(s.source)}">
            <span class="mdot" data-m="${esc(s.modality)}"></span><span class="n">${s.index}</span>
            <span class="name">${esc(s.metadata?.path || s.label || s.title)}</span>${s.location ? `<span class="loc">${esc(s.location)}</span>` : ""}</button>`;
    // Once citations are known, lead with the sources the answer actually used
    // and fold the rest of the retrieved set away so it doesn't read as evidence.
    const settled = !msg.pending && cited.size > 0;
    const primary = settled ? msg.sources.filter((s) => cited.has(s.index)) : msg.sources;
    const rest = settled ? msg.sources.filter((s) => !cited.has(s.index)) : [];
    parts.push(
      `<div class="answer-sources" aria-label="Sources">${primary.map(chip).join("")}</div>` +
        (rest.length
          ? `<details class="more-sources"><summary>${plural(rest.length, "more retrieved source")}</summary>
              <div class="answer-sources">${rest.map(chip).join("")}</div></details>`
          : ""),
    );
  }
  if (!msg.pending && (msg.text || msg.error)) {
    const t = msg.timings || {};
    const meta = [msg.backend, t.total_ms ? `${(t.total_ms / 1000).toFixed(2)} s` : ""].filter(Boolean).join(" · ");
    const offline = msg.backend === "extractive" && msg.text;
    parts.push(`<div class="answer-foot">
      ${msg.text ? `<button class="btn btn-ghost" type="button" data-copy="${index}">${icon("copy")}<span>Copy</span></button>` : ""}
      ${meta ? `<span class="meta">${esc(meta)}</span>` : ""}
      ${offline ? `<a class="foot-hint" href="#/settings" title="Answers are quoted from your sources. Connect Ollama or an OpenAI-compatible model for written answers.">Quoted from sources · connect a model for written answers</a>` : ""}
    </div>`);
  }
  return parts.join("");
}

function renderThread(scrollToEnd = false) {
  if (state.view !== "chat") return;
  const chat = currentChat();
  const thread = $("#thread");
  if (!chat || !chat.messages.length) {
    renderEmptyThread();
    return;
  }
  thread.innerHTML = chat.messages
    .map((m, i) =>
      m.role === "user"
        ? `<div class="turn turn-user"><div class="bubble-user">${esc(m.text)}</div></div>`
        : `<div class="turn answer" data-index="${i}">${renderAnswerInner(m, i)}</div>`,
    )
    .join("");
  markPreviewChip();
  if (scrollToEnd) thread.scrollTop = thread.scrollHeight;
}

let renderQueued = false;
function updateAnswer(index) {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => {
    renderQueued = false;
    const chat = currentChat();
    const el = $(`#thread .answer[data-index="${index}"]`);
    if (!chat || !el) return;
    const thread = $("#thread");
    const nearBottom = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 120;
    el.innerHTML = renderAnswerInner(chat.messages[index], index);
    markPreviewChip();
    if (nearBottom) thread.scrollTop = thread.scrollHeight;
  });
}

function setComposerBusy(busy) {
  const send = $("#send");
  send.classList.toggle("stop", busy);
  send.innerHTML = icon(busy ? "stop" : "send");
  send.setAttribute("aria-label", busy ? "Stop generating" : "Send");
  send.title = busy ? "Stop generating" : "Send";
  updateSendEnabled();
}

function updateSendEnabled() {
  const busy = Boolean(state.controller);
  $("#send").disabled = !busy && (!$("#question").value.trim() || !state.kb);
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

async function ask(question) {
  if (!state.kb || state.controller) return;
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
  chat.messages.push({ role: "user", text: question });
  const msg = { role: "assistant", text: "", pending: true };
  chat.messages.push(msg);
  const index = chat.messages.length - 1;
  chat.updated = Date.now();
  saveChats();
  renderChatList();
  renderThread(true);

  const controller = new AbortController();
  state.controller = controller;
  setComposerBusy(true);
  const body = { query: question, kb: chat.kb, modalities: state.filters.size ? [...state.filters] : null };
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
        if (event === "sources") msg.sources = data.sources.map(slimSource);
        else if (event === "delta") msg.text += data.text;
        else if (event === "done") {
          msg.text = data.answer;
          msg.cited = data.cited;
          msg.backend = data.backend;
          msg.timings = data.timings;
          msg.warnings = data.warnings;
          msg.sources = data.sources.map(slimSource);
        } else if (event === "error") msg.error = data.detail;
        if (state.chatId === chat.id) updateAnswer(index);
      }
    }
  } catch (err) {
    if (err.name === "AbortError") msg.stopped = true;
    else msg.error = err.message || "The request failed.";
  } finally {
    msg.pending = false;
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
    if (state.chatId === chat.id) {
      updateAnswer(index);
      const firstCited = msg.cited?.[0];
      if (firstCited && window.matchMedia("(min-width: 1181px)").matches) openSource(index, firstCited);
    }
    renderChatList();
  }
}

async function copyAnswer(index, button) {
  const msg = currentChat()?.messages[index];
  if (!msg?.text) return;
  try {
    await navigator.clipboard.writeText(msg.text);
    button.innerHTML = `${icon("check")}<span>Copied</span>`;
    setTimeout(() => (button.innerHTML = `${icon("copy")}<span>Copy</span>`), 1600);
  } catch {
    toast("Copy failed: clipboard access was blocked", { error: true });
  }
}

// ----------------------------------------------------------------- preview
function closePreview() {
  state.preview = null;
  $("#preview").hidden = true;
  $("#app").classList.remove("has-preview");
  markPreviewChip();
}

function markPreviewChip() {
  for (const el of $$("#thread [data-cite]")) {
    const on = state.preview && state.preview.chatId === state.chatId && +el.dataset.msg === state.preview.index && +el.dataset.cite === state.preview.n;
    el.setAttribute("aria-pressed", on ? "true" : "false");
  }
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

const STOP = new Set("what when where which while with would about does have from that this there their them they into your how why who the and for are was were will been being can could should".split(" "));
function questionWords(chat, index) {
  const q = chat.messages[index - 1]?.text || "";
  return [...new Set(q.toLowerCase().match(/[a-z0-9]{4,}/g) || [])].filter((w) => !STOP.has(w)).map((w) => w.slice(0, Math.max(4, w.length - 2)));
}

function codeLines(text, start) {
  return `<pre class="code-lines"><code>${text
    .split("\n")
    .map((line, i) => `<span class="ln"><span class="ln-n">${start + i}</span><span class="ln-c">${esc(line) || " "}</span></span>`)
    .join("")}</code></pre>`;
}

let previewToken = 0;
const blobUrls = [];
async function fetchRaw(docId) {
  const res = await api(`${kbPath(currentChat()?.kb)}/documents/${encodeURIComponent(docId)}/raw`, { raw: true });
  const url = URL.createObjectURL(await res.blob());
  blobUrls.push(url);
  while (blobUrls.length > 12) URL.revokeObjectURL(blobUrls.shift());
  return url;
}

async function openSource(index, n) {
  const chat = currentChat();
  const msg = chat?.messages[index];
  const s = msg?.sources?.find((x) => x.index === n);
  if (!s) return;
  const token = ++previewToken;
  state.preview = { chatId: chat.id, index, n };
  markPreviewChip();
  const panel = $("#preview");
  panel.hidden = false;
  $("#app").classList.add("has-preview");
  const meta = s.metadata || {};
  $("#preview-title").innerHTML = `<h2>[${n}] ${esc(s.title || s.label)}</h2>
    <div class="preview-meta"><span class="badge"><span class="mdot" data-m="${esc(s.modality)}"></span>${esc(s.modality)}</span>
    <span class="path">${esc(meta.path || s.source)}</span>${s.location ? `<span>${esc(s.location)}</span>` : ""}</div>`;
  const body = $("#preview-body");
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
  const isCode = s.modality === "code" && Number.isInteger(meta.line_start);
  // Code chunks are "description + fenced code"; number only the code lines.
  const fenced = isCode ? content.match(/^([\s\S]*?)```[\w+#.-]*\n([\s\S]*?)\n?```\s*$/) : null;
  const cited = isCode
    ? `${fenced?.[1].trim() ? `<pre class="code-head">${highlight(fenced[1].trim(), words)}</pre>` : ""}${codeLines(fenced ? fenced[2] : content, meta.line_start)}`
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
  body.innerHTML = `
    ${note ? `<div class="notice">${esc(note)}</div>` : ""}
    ${s.modality === "image" ? `<figure class="preview-image" id="preview-image"><span class="thinking">Loading image…</span></figure>` : ""}
    ${ctx(chunk?.before, "Before")}
    <div class="excerpt cited"><div class="excerpt-label"><span>Cited chunk${s.location ? ` · ${esc(s.location)}` : ""}</span><span>score ${Number(s.score).toFixed(3)}</span></div>${cited}</div>
    ${ctx(chunk?.after, "After")}
    <div class="preview-actions">
      <button class="btn btn-secondary" type="button" data-open-raw="${esc(s.doc_id)}">${icon("external")}Open original</button>
      <button class="btn btn-ghost" type="button" data-copy-excerpt>${icon("copy")}Copy excerpt</button>
    </div>
    <details class="more"><summary>Metadata${ranks ? ` · ${esc(ranks)}` : ""}</summary><table class="meta-table">${metaRows}</table></details>`;
  body.querySelector("[data-copy-excerpt]").addEventListener("click", async (e) => {
    try {
      await navigator.clipboard.writeText(content);
      e.currentTarget.innerHTML = `${icon("check")}Copied`;
    } catch {
      toast("Copy failed: clipboard access was blocked", { error: true });
    }
  });
  if (s.modality === "image") {
    try {
      const url = await fetchRaw(s.doc_id);
      if (token !== previewToken) return;
      const fig = $("#preview-image");
      fig.innerHTML = "";
      const img = new Image();
      img.alt = s.title || "Source image";
      img.src = url;
      fig.append(img);
    } catch (err) {
      const fig = $("#preview-image");
      if (fig) fig.innerHTML = `<span class="field-help">Image unavailable: ${esc(err.message)}</span>`;
    }
  }
  if (!window.matchMedia("(min-width: 1181px)").matches) $("#preview-close").focus();
}

async function openRaw(docId) {
  try {
    const url = await fetchRaw(docId);
    window.open(url, "_blank", "noopener");
  } catch (err) {
    toast(`Could not open the file: ${err.message}`, { error: true });
  }
}

// ----------------------------------------------------------------- library
function renderDropHint() {
  const s = state.status;
  $("#drop-kb").textContent = state.kb || "a knowledge base";
  if (s?.upload_extensions) {
    $("#file-input").setAttribute("accept", s.upload_extensions.join(","));
    $("#drop-sub").textContent = `Documents, code, tables, images and transcripts · up to ${s.max_upload_mb} MB per file.`;
  }
}

function renderLibrary() {
  renderDropHint();
  const disabled = !state.kb;
  $("#dropzone").hidden = disabled;
  if (disabled) {
    $("#doc-count").textContent = "";
    $("#doc-table").innerHTML = `<div class="table-empty"><strong>No knowledge base selected</strong>Create one to start adding files.
      <div class="empty-actions"><button class="btn btn-primary" type="button" data-action="new-kb">${icon("plus")}New knowledge base</button></div></div>`;
  } else renderDocs();
}

async function loadDocs() {
  if (!state.kb) return;
  const name = state.kb;
  if (state.docsKb !== name) {
    state.docs = null;
    renderDocs();
  }
  try {
    const docs = await api(`${kbPath(name)}/documents`);
    if (name !== state.kb) return;
    state.docs = docs;
    state.docsKb = name;
    state.docsError = null;
  } catch (err) {
    state.docsError = err.message;
  }
  if (state.view === "library") renderDocs();
}

function renderDocs() {
  const wrap = $("#doc-table");
  if (state.docsError && !state.docs) {
    wrap.innerHTML = `<div class="table-empty"><strong>Could not load documents</strong>${esc(state.docsError)}
      <div class="empty-actions"><button class="btn btn-secondary" type="button" data-action="reload-docs">${icon("refresh")}Try again</button></div></div>`;
    return;
  }
  if (!state.docs || state.docsKb !== state.kb) {
    $("#doc-count").textContent = "";
    wrap.innerHTML = `<table class="doc-table"><tbody>${'<tr><td><div class="skeleton"></div></td></tr>'.repeat(4)}</tbody></table>`;
    return;
  }
  const q = $("#doc-search").value.trim().toLowerCase();
  const docs = q
    ? state.docs.filter((d) => `${d.name} ${d.path} ${d.title} ${d.modality}`.toLowerCase().includes(q))
    : state.docs;
  $("#doc-count").textContent = q ? `${docs.length} of ${state.docs.length}` : String(state.docs.length);
  if (!state.docs.length) {
    wrap.innerHTML = `<div class="table-empty"><strong>No documents yet</strong>Drop files above, or ingest a folder with <code>omnirag ingest PATH --kb ${esc(state.kb)}</code>.</div>`;
    return;
  }
  if (!docs.length) {
    wrap.innerHTML = `<div class="table-empty"><strong>No matches</strong>Nothing matches “${esc(q)}”.</div>`;
    return;
  }
  wrap.innerHTML = `<table class="doc-table">
    <thead><tr><th>Name</th><th>Type</th><th class="num">Chunks</th><th class="num">Size</th><th>Ingested</th><th><span class="sr-only">Actions</span></th></tr></thead>
    <tbody>${docs
      .map(
        (d) => `<tr>
        <td class="c-name"><div class="doc-name"><strong title="${esc(d.source)}">${esc(d.name)}${d.missing ? '<span class="doc-flag">missing</span>' : ""}</strong>${d.path !== d.name ? `<span>${esc(d.path)}</span>` : d.title && d.title !== d.name ? `<span>${esc(d.title)}</span>` : ""}</div></td>
        <td class="hide-sm"><span class="badge"><span class="mdot" data-m="${esc(d.modality)}"></span>${esc(d.modality)}</span></td>
        <td class="num hide-sm">${d.chunks}</td>
        <td class="num hide-sm">${formatBytes(d.size_bytes)}</td>
        <td class="hide-sm"><span class="doc-time" title="${esc(exactTime(d.updated_at))}">${esc(relativeTime(d.updated_at))}</span></td>
        <td class="c-meta"><span class="mdot" data-m="${esc(d.modality)}"></span>${esc(d.modality)} · ${plural(d.chunks, "chunk")} · ${formatBytes(d.size_bytes)}</td>
        <td class="c-actions"><div class="doc-actions">
          <button class="icon-btn" type="button" data-reingest="${esc(d.doc_id)}" aria-label="Re-ingest ${esc(d.name)}" title="Re-ingest"${d.missing ? " disabled" : ""}>${icon("refresh")}</button>
          <button class="icon-btn danger" type="button" data-delete-doc="${esc(d.doc_id)}" aria-label="Delete ${esc(d.name)}" title="Delete">${icon("trash")}</button>
        </div></td>
      </tr>`,
      )
      .join("")}</tbody></table>`;
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
    renderDocs();
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
  const backend = $('#llm-backend input:checked')?.value ?? "";
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
    llm: $('#llm-backend input:checked')?.value ?? "",
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
  $("#scrim").hidden = true;
  $("#open-sidebar").setAttribute("aria-expanded", "false");
}

// ------------------------------------------------------------------ events
function bindEvents() {
  window.addEventListener("hashchange", () => showView(viewFromHash()));

  document.addEventListener("click", (e) => {
    const t = e.target.closest("button, a");
    if (!t) return;
    const d = t.dataset;
    if (d.kb) {
      switchKb(d.kb);
      closeSidebar();
    } else if (d.deleteKb) deleteKb(d.deleteKb);
    else if (d.openChat) {
      openChat(d.openChat);
      closeSidebar();
    } else if (d.deleteChat) deleteChat(d.deleteChat);
    else if (d.cite && d.msg !== undefined && !t.disabled) openSource(+d.msg, +d.cite);
    else if (d.copy !== undefined) copyAnswer(+d.copy, t);
    else if (d.filter !== undefined) toggleFilter(d.filter);
    else if (d.ask) ask(d.ask);
    else if (d.openRaw) openRaw(d.openRaw);
    else if (d.deleteDoc) deleteDoc(d.deleteDoc);
    else if (d.reingest) reingestDoc(d.reingest, t);
    else if (d.action === "new-kb") openKbDialog();
    else if (d.action === "reload-docs") loadDocs();
    else if (d.close !== undefined) t.closest("dialog")?.close("cancel");
    else if (t.id === "new-chat-top" || t.id === "new-chat-side") {
      newChat();
      closeSidebar();
    } else if (t.classList.contains("nav-link")) closeSidebar();
  });

  $("#new-kb").addEventListener("click", openKbDialog);
  $("#kb-form").addEventListener("submit", createKb);
  $("#delete-kb-settings").addEventListener("click", () => state.kb && deleteKb(state.kb));
  $("#preview-close").addEventListener("click", closePreview);
  $("#open-sidebar").addEventListener("click", openSidebar);
  $("#close-sidebar").addEventListener("click", closeSidebar);
  $("#scrim").addEventListener("click", closeSidebar);
  $("#status-pill").addEventListener("click", () => (location.hash = "#/settings"));
  $("#status-refresh").addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    state.status = null;
    renderStatusGrid();
    await loadStatus();
    e.currentTarget.disabled = false;
  });
  $("#theme-toggle").addEventListener("click", () => {
    const cur = store.get("omnirag.theme", "system");
    setTheme(THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length]);
  });
  $("#theme-choice").addEventListener("change", (e) => setTheme(e.target.value));
  $("#forget-key").addEventListener("click", () => {
    store.remove("omnirag.apiKey");
    renderKeyRow();
    requestApiKey();
  });
  $("#settings-form").addEventListener("submit", saveSettings);
  $("#llm-backend").addEventListener("change", updateLlmFields);

  const q = $("#question");
  const autosize = () => {
    q.style.height = "auto";
    q.style.height = `${Math.min(q.scrollHeight, 200)}px`;
    q.style.overflowY = q.scrollHeight > 200 ? "auto" : "hidden";
    updateSendEnabled();
  };
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

  document.addEventListener("keydown", (e) => {
    const typing = e.target.closest?.("input, textarea, select, [contenteditable]");
    if (e.key === "Escape" && !document.querySelector("dialog[open]")) {
      if (state.controller && !typing) stopStreaming();
      else if ($("#app").classList.contains("sidebar-open")) closeSidebar();
      else if (state.preview) closePreview();
    } else if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      if (state.view !== "chat") location.hash = "#/chat";
      q.focus();
    }
  });
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => applyTheme(store.get("omnirag.theme", "system")));
}

// -------------------------------------------------------------------- boot
async function boot() {
  applyTheme(store.get("omnirag.theme", "system"));
  $("#version").textContent = `v${state.version}`;
  renderFilters();
  renderKbList();
  bindEvents();
  showView(viewFromHash());
  try {
    state.health = await (await fetch("/api/health")).json();
  } catch {
    state.health = null;
  }
  if (state.health?.auth_required && !store.get("omnirag.apiKey")) await requestApiKey();
  await loadKbs();
  state.chatId = kbChats()[0]?.id ?? null;
  renderChatList();
  renderTopbar();
  renderView();
  await refreshKb();
  updateSendEnabled();
}

boot();
