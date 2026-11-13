# Design references

The web app's layout and interaction patterns were taken from three products that are good at
one thing each. Only patterns were borrowed: no logos, colours, fonts, icons or other assets.
OmniRAG uses its own neutral palette with a single indigo accent, Inter for the interface and
answers, JetBrains Mono for code, and the Lucide icon set.

## Component kit (0.3.0)

Since 0.3.0 the web app is built on a real component kit instead of hand-written HTML, CSS and
JavaScript:

| Layer | Choice | Why |
|-------|--------|-----|
| Build | Vite, React 19, TypeScript (strict) | Fast builds, typed API client and state, a large ecosystem of accessible primitives |
| Styling | Tailwind CSS v4 with CSS variables | Design tokens (colours, radii, fonts) in one place, light and dark themes from the same tokens |
| Components | shadcn/ui on Radix primitives | The code is copied into `web/src/components/ui/`, so it can be read and changed; Radix provides focus management, keyboard support and ARIA roles for dialogs, menus, tabs, checkboxes, hover cards, sheets and drawers |
| AI patterns | shadcn AI Elements | Ready-made, well-considered compositions for exactly this product: Chat on Message Scroller (new turns anchor near the top and keep the reader's place while answers stream), Message, Prompt Input on Input Group, Sources and Chain of Thought on Trace, Inline Citation and Context on Hover Card, Suggestion, Code Block with Shiki highlighting, Shimmer for running steps |
| Toasts, palette, drawers | sonner, cmdk, vaul (through shadcn) | Undo-able toasts, a fuzzy command palette and touch-friendly bottom sheets |
| Fonts | `@fontsource-variable` Inter and JetBrains Mono | Self-hosted Latin subsets; the page makes no third-party requests |

What was adapted rather than copied:

- **No AI SDK UI.** OmniRAG's stream is its own server-sent-event protocol (`sources`, `delta`,
  `done`, `error`), so a small typed client (`web/src/lib/api.ts`, `sse.ts`) and a store replace
  `useChat`.
- **No Markdown library.** Answers are parsed by a small renderer (`web/src/lib/markdown.ts`) that
  produces React elements, never HTML, and turns `[1][2]` into one citation group. This keeps
  model output from injecting markup and keeps the bundle small.
- **Hover cards are skipped on touch screens**, where a tap opens the source panel directly.
- The **Context** pattern shows how much source text was sent to the answerer against its token
  budget, rather than a chat model's context window.

The build is committed to `src/omnirag/server/static/` so that `pip install` needs no Node.js;
CI fails when the committed build does not match the sources.

## Perplexity (answer page)

What we looked at: the question shown as the page heading, per-answer tabs, a row of source
cards above the answer, a narrow reading column, citation pills that name the source, a sources
side panel, a follow-up box pinned to the bottom, a progress status while the answer is being
written, related questions and a home screen built around one large search box.

What OmniRAG adopted, and why:

| Pattern | In OmniRAG | Why |
|---------|------------|-----|
| Question as the heading of each answer | Every turn starts with the question in large type; the newest turn scrolls to the top so its answer fills in below it | Long threads stay scannable; each answer reads as a short document, not a chat bubble |
| Answer tabs | `Answer · Sources (n) · Media (n)`; Media appears only when images were retrieved; arrow keys move between tabs | Keeps the evidence one click away without pushing the answer down |
| Sources before the text | A horizontally scrolling strip of source cards (modality icon, file name, section / lines / rows / timestamp, image thumbnail), cited sources first, uncited ones dashed and collapsed into "+N more" | Users judge an answer by where it came from; seeing that first builds the right level of trust. Scores are left out of the cards because they are not meaningful to readers |
| Reading typography | Answer body at 16px with a 1.75 line height, in a column of about 46rem | Answers are read, not skimmed like UI; a measured column makes longer answers comfortable |
| Citation pills with names | `[1][2]` renders as one pill "authentication.md +1"; hover or keyboard focus shows a card with the excerpt, location and an "Open source" button; click opens the full source panel. When every cited source is one file, pills show the section, lines or rows instead | A file name says more than a number, while the accessible name and the copied text keep the `[n]` references |
| Progress status | Steps while streaming: Searching N chunks, Reading K sources, Writing, Done; afterwards a single line "Answered from K sources in 0.4s" that expands to timings | Retrieval is fast but generation is not; showing which stage is running explains waits and then gets out of the way |
| Related questions | A "Related" list under each answer, built offline from the headings, code symbols, table names and timestamps of the documents the answer used (`POST /api/kbs/{name}/related`) | Suggests the natural next question about material the answer did not cover, without needing a model |
| Home screen | An empty chat shows "Ask &lt;kb&gt; anything" with a large centred composer and four starter questions; after the first question the composer glides to the bottom | Makes the first step obvious and shows what the knowledge base contains |

Not adopted: web search, discovery feeds, account features and model pickers in the composer.

## NotebookLM (source grounding)

What we looked at: a sources panel where each document has a checkbox and the chat only uses the
ticked ones.

What OmniRAG adopted, and why:

- A **Sources** panel beside the chat (a bottom sheet on phones) and a checkbox column in the
  **Library** share one selection per knowledge base, kept in the browser.
- When anything is selected, questions are sent with `doc_ids` and the server restricts
  retrieval to those documents (`POST /api/query` and `/api/query/stream`). A "Scoped to 3
  sources ×" chip sits above the composer, the top bar shows "Sources 3/10", and each answer
  records the scope it was asked with.
- Why: scoping is the most direct way to stop an answer drawing on the wrong document, and making
  it visible at the point of asking prevents "why didn't it find X?" confusion.

Not adopted: generated notebook artefacts (audio overviews, study guides).

## Linear (application shell)

What we looked at: a compact sidebar with small section headers and quiet secondary text, a
keyboard-first workflow and a command palette.

What OmniRAG adopted, and why:

- **Command palette** (`Ctrl K` / `⌘ K`): new chat, focus the question box, choose sources,
  clear scope, toggle theme, keyboard shortcuts, go to Chat / Library / Settings, switch or
  create a knowledge base, open any document, reopen a conversation. Fuzzy matching, arrow keys,
  Enter.
- **Shortcuts** shown with `?`: `/` focus, `N` new chat, `S` sources, `G` then `C`/`L`/`S` to
  navigate, `Esc` to stop or close.
- **Calmer visual system**: one accent colour, hairline borders, subtle elevation only on
  floating layers (palette, citation card, drawers, toasts), a 4/8px spacing scale, 120–180ms
  transitions that are switched off under `prefers-reduced-motion`.
- Why: a knowledge tool is used repeatedly by the same people; keyboard paths and low visual
  noise pay off quickly, and the answer text should be the most prominent thing on screen.

## Constraints that shaped the result

- Installable without Node: the React build ships inside the Python package; no CDN scripts and
  no web fonts from third parties. The page's Content Security Policy allows scripts, fonts and
  connections from the same origin only.
- Accessibility: visible focus rings, WCAG AA contrast for text in both themes, Radix primitives
  for dialogs, menus, tabs, checkboxes and hover cards, a labelled `role="log"` transcript, and
  `aria-live` announcements when an answer is ready or the scope changes. Motion is switched off
  under `prefers-reduced-motion`.
- Small screens: at 375px the sidebar is a sheet, previews and the source picker are bottom
  drawers, the source strip scrolls sideways and the library table folds into one column.
