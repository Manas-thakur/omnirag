---
title: Modalities
description: How documents, code, tables, images and audio are turned into searchable text.
---

OmniRAG maps every modality into one shared search space by using **text as the bridge**: an
image is described by its caption, alt text and metadata; a recording by its transcript; a table
by its schema, statistics and rows; code by its signatures and docstrings. Everything becomes
text chunks in one index, searched with one query.

Files are routed by extension. Files with unknown extensions such as `.log`, `.toml` or `.yaml`
are sniffed: if they look like text they are ingested as text, and scripts with a shebang line
are recognised as code.

## Text

**Extensions:** `.md` `.markdown` `.mdx` `.txt` `.rst` `.html` `.htm` `.pdf`

- Markdown is split on headings and every chunk carries its heading breadcrumb
  (`Authentication > Refreshing tokens`), which also becomes its *section* in citations.
- HTML is converted to structured text with its headings.
- PDFs are chunked per page with the `pdf` extra (`pypdf`). Scanned PDFs without a text layer
  are not OCR'd.

## Code

**Languages (26 extensions):** Python (`.py` `.pyi`), JavaScript (`.js` `.mjs` `.cjs` `.jsx`),
TypeScript (`.ts` `.tsx`), Java, Go, Rust, C (`.c` `.h`), C++ (`.cpp` `.cc` `.hpp`), C#, Ruby,
PHP, Kotlin, Swift, Scala, shell (`.sh` `.bash`), SQL, Lua and R.

- **Python** is parsed with the standard library's `ast` into a module chunk plus one chunk per
  function and class (and per method for large classes), each with its signature, docstring and
  exact line range.
- **JavaScript and TypeScript** declarations (functions, classes, exported constants) are found
  with patterns and chunked the same way.
- **Other languages** are split into overlapping line windows.

Code citations show the symbol and lines, for example `TokenBucket · L9–42`, and the source
preview renders the code with its real line numbers.

## Tables

**Extensions:** `.csv` `.tsv` `.json` `.jsonl` `.ndjson`

Each table gets a **summary chunk** (columns, inferred types, min / max / mean / median for
numbers, frequent values for text) and **row chunks** rendered as `column=value` pairs, so exact
values are searchable and citations name the row range.

## Images

**Extensions:** `.png` `.jpg` `.jpeg` `.webp` `.gif` `.bmp` `.tif` `.tiff` `.svg`

An image is described from the first sources available, in this order:

1. a caption from an Ollama vision model, if `OMNIRAG_VLM_MODEL` is set (for example `llava`);
2. a sidecar caption file next to it: `img.png.txt`, `img.caption.txt` or `img.txt`;
3. alt text in Markdown or HTML documents that reference the image;
4. SVG `<title>`, `<desc>` and `<text>` elements, PNG text chunks and EXIF metadata
   (EXIF and dimensions need the `images` extra);
5. the file name.

The web app shows image sources as thumbnails and collects them in each answer's **Media** tab.

## Audio and transcripts

**Transcripts:** `.vtt` `.srt` · **Audio:** `.mp3` `.wav` `.flac` `.ogg` `.m4a` `.aac` `.opus`

Transcripts keep cue timestamps and speaker names, so citations point at a time range such as
`00:05–01:26`. For an audio file, OmniRAG uses a sidecar transcript next to it if there is one,
otherwise it transcribes locally with `faster-whisper` when the `audio` extra is installed
(model size from `OMNIRAG_WHISPER_MODEL`, default `base`).

## Upload limits

The web app and `POST /api/kbs/{name}/upload` accept exactly the extensions above, up to
`OMNIRAG_MAX_UPLOAD_MB` (default 50 MB) per file. `GET /api/status` returns both the list and
the limit.
