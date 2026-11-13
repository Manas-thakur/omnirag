# Design references

The web app's layout and interaction patterns were taken from three products that are good at
one thing each. Only patterns were borrowed: no logos, colours, fonts, icons or other assets.
OmniRAG uses its own neutral palette with a single blue accent, Inter for the interface,
Source Serif 4 for answer text and a hand-drawn icon set.

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
| Reading typography | Answer body in a serif text face at about 17px with a 1.7 line height, in a column capped at 68 characters | Answers are read, not skimmed like UI; a measured column and a text face make longer answers comfortable |
| Citation pills with names | `[1][2]` renders as one pill "authentication.md +1"; hover or keyboard focus shows a card with the excerpt, location and an "Open source" button; click opens the full source panel | A file name says more than a number, while the accessible name and the copied text keep the `[n]` references |
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

- No build step: plain HTML, CSS and ES modules; no CDN scripts. Web fonts load from Google
  Fonts and fall back to system faces offline.
- Accessibility: visible focus rings, WCAG AA contrast for text in both themes, the WAI-ARIA tabs
  pattern for answer tabs, a combobox/listbox palette, `aria-live` announcements when an answer
  is ready or the scope changes.
- Small screens: at 375px the source strip scrolls sideways, the source panel and previews become
  bottom sheets and the sidebar becomes an off-canvas menu.
