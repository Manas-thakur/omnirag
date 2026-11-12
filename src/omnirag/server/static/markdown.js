// Small, safe Markdown renderer for answers.
//
// Safety model: every piece of source text is HTML-escaped before any markup
// is added, raw HTML is never passed through, and links are only emitted for
// http(s)/mailto URLs. The output therefore contains only the tags created
// here. Supported: paragraphs, headings, fenced code, inline code, bold,
// italic, links, block quotes, ordered/unordered lists, simple tables,
// horizontal rules and [n] citation chips.

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
}

function safeUrl(raw) {
  const url = raw.trim();
  return /^(https?:\/\/|mailto:)/i.test(url) ? url : null;
}

// Inline markup on a single (unescaped) line of text.
function inline(text, cite) {
  const slots = [];
  const keep = (html) => `\u0000${slots.push(html) - 1}\u0000`;
  let s = String(text);
  // Code spans first: their contents are literal.
  s = s.replace(/`([^`\n]+)`/g, (_, code) => keep(`<code>${escapeHtml(code)}</code>`));
  // Links [label](url) - label may contain other inline markup.
  s = s.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (m, label, href) => {
    const url = safeUrl(href);
    if (!url) return m;
    return keep(
      `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${inline(label, null)}</a>`,
    );
  });
  // Citations: [1], [2, 3], [1][2]
  if (cite) {
    s = s.replace(/\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]/g, (_, nums) =>
      keep(nums.split(",").map((n) => cite(Number(n.trim()))).join("")),
    );
  }
  s = escapeHtml(s);
  s = s
    .replace(/\*\*(?=\S)([^*]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/__(?=\S)([^_]+?)__/g, "<strong>$1</strong>")
    .replace(/(^|[^\w*])\*(?=\S)([^*\n]+?)\*(?!\w)/g, "$1<em>$2</em>")
    .replace(/(^|[^\w])_(?=\S)([^_\n]+?)_(?!\w)/g, "$1<em>$2</em>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => slots[Number(i)]);
}

const isTableSep = (line) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);
const splitRow = (line) =>
  line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

/**
 * Render Markdown to HTML.
 * @param {string} text
 * @param {{cite?: (n: number) => string}} [opts] cite renders a citation chip.
 */
export function renderMarkdown(text, opts = {}) {
  const cite = opts.cite || null;
  const lines = String(text ?? "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0;
  let para = [];

  const flush = () => {
    if (para.length) out.push(`<p>${para.map((l) => inline(l, cite)).join("<br>")}</p>`);
    para = [];
  };

  while (i < lines.length) {
    const line = lines[i];

    const fence = line.match(/^\s*(```|~~~)\s*([\w+#.-]*)\s*$/);
    if (fence) {
      flush();
      const body = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i++]);
      i += 1; // closing fence (or end of a still-streaming block)
      const lang = fence[2] ? ` data-lang="${escapeHtml(fence[2])}"` : "";
      out.push(`<pre class="md-code"${lang}><code>${escapeHtml(body.join("\n"))}</code></pre>`);
      continue;
    }

    if (!line.trim()) {
      flush();
      i += 1;
      continue;
    }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/);
    if (heading) {
      flush();
      const level = Math.min(6, heading[1].length + 2); // answers never need h1/h2
      out.push(`<h${level}>${inline(heading[2], cite)}</h${level}>`);
      i += 1;
      continue;
    }

    if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) {
      flush();
      out.push("<hr>");
      i += 1;
      continue;
    }

    if (/^\s*>/.test(line)) {
      flush();
      const body = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push(`<blockquote>${renderMarkdown(body.join("\n"), opts)}</blockquote>`);
      continue;
    }

    if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      flush();
      const head = splitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(splitRow(lines[i++]));
      out.push(
        `<div class="md-table"><table><thead><tr>${head.map((h) => `<th>${inline(h, cite)}</th>`).join("")}</tr></thead>` +
          `<tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${inline(c, cite)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`,
      );
      continue;
    }

    const item = line.match(/^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$/);
    if (item) {
      flush();
      const ordered = /\d/.test(item[2]);
      const tag = ordered ? "ol" : "ul";
      const start = ordered ? parseInt(item[2], 10) : 1;
      const items = [];
      while (i < lines.length) {
        const m = lines[i].match(/^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$/);
        if (m && /\d/.test(m[2]) === ordered) {
          items.push(m[3]);
          i += 1;
        } else if (lines[i].trim() && /^\s{2,}\S/.test(lines[i]) && items.length) {
          items[items.length - 1] += "\n" + lines[i].trim(); // continuation line
          i += 1;
        } else break;
      }
      const startAttr = ordered && start !== 1 ? ` start="${start}"` : "";
      out.push(
        `<${tag}${startAttr}>${items.map((t) => `<li>${t.split("\n").map((l) => inline(l, cite)).join("<br>")}</li>`).join("")}</${tag}>`,
      );
      continue;
    }

    para.push(line.trim());
    i += 1;
  }
  flush();
  return out.join("\n");
}
