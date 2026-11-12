"""Structured data: CSV/TSV, JSON and JSON Lines.

Produces one *summary* chunk (schema, column types, numeric statistics,
frequent values) plus row chunks rendered as ``column=value`` text so that
individual records are searchable.
"""

from __future__ import annotations

import csv
import io
import json
import statistics
from pathlib import Path
from typing import Any

from omnirag.chunking import RawChunk
from omnirag.ingest.base import (
    IngestContext,
    IngestError,
    Ingestor,
    ParsedDocument,
    humanize_filename,
    read_text_file,
)
from omnirag.store.models import Modality

ROWS_PER_CHUNK = 20


def _coerce(value: Any) -> Any:
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return None
        low = s.lower()
        if low in {"true", "false"}:
            return low == "true"
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            return s
    return value


def _column_type(values: list[Any]) -> str:
    present = [v for v in values if v is not None]
    if not present:
        return "empty"
    if all(isinstance(v, bool) for v in present):
        return "boolean"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in present):
        return "integer"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        return "float"
    if all(isinstance(v, (dict, list)) for v in present):
        return "nested"
    return "string"


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)[:200]
    return str(v)


def load_rows(path: Path) -> list[dict[str, Any]]:
    ext = path.suffix.lower()
    text = read_text_file(path)
    if ext in {".csv", ".tsv"}:
        delimiter = "\t" if ext == ".tsv" else ","
        if ext == ".csv":
            try:
                delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
            except csv.Error:
                delimiter = ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        return [
            {str(k).strip(): _coerce(v) for k, v in row.items() if k is not None} for row in reader
        ]
    if ext in {".jsonl", ".ndjson"}:
        rows = []
        for line in text.splitlines():
            if line.strip():
                obj = json.loads(line)
                rows.append(obj if isinstance(obj, dict) else {"value": obj})
        return rows
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IngestError(f"invalid JSON: {exc}") from exc
    if isinstance(data, list):
        return [r if isinstance(r, dict) else {"value": r} for r in data]
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if len(lists) == 1:
            return list(lists[0])
        return [data]
    return [{"value": data}]


def describe_table(name: str, rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    lines = [f"Table {name}: {len(rows)} rows, {len(columns)} columns."]
    lines.append("Columns: " + ", ".join(columns) + ".")
    for col in columns:
        values = [row.get(col) for row in rows]
        ctype = _column_type(values)
        present = [v for v in values if v is not None]
        missing = len(values) - len(present)
        detail = f"- {col} ({ctype})"
        if ctype in {"integer", "float"} and present:
            nums = [float(v) for v in present]
            detail += (
                f": min {_fmt(min(nums))}, max {_fmt(max(nums))}, "
                f"mean {_fmt(statistics.fmean(nums))}"
            )
            if len(nums) > 1:
                detail += f", median {_fmt(statistics.median(nums))}"
        elif ctype in {"string", "boolean"} and present:
            counts: dict[str, int] = {}
            for v in present:
                counts[_fmt(v)] = counts.get(_fmt(v), 0) + 1
            distinct = len(counts)
            top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
            shown = ", ".join(f"{k} ({n})" if n > 1 else k for k, n in top)
            detail += f": {distinct} distinct values, e.g. {shown}"
        if missing:
            detail += f"; {missing} missing"
        lines.append(detail)
    return "\n".join(lines), columns


def render_row(index: int, row: dict[str, Any], columns: list[str]) -> str:
    cells = [f"{c}={_fmt(row[c])}" for c in columns if row.get(c) is not None]
    return f"Row {index}: " + ", ".join(cells)


class TableIngestor(Ingestor):
    modality = Modality.TABLE

    def ingest(self, path: Path, ctx: IngestContext) -> ParsedDocument:
        try:
            rows = load_rows(path)
        except (csv.Error, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise IngestError(f"could not parse table: {exc}") from exc
        rel = ctx.display_path(path)
        summary, columns = describe_table(rel, rows)
        chunks = [RawChunk(summary, {"kind": "summary", "columns": columns, "rows": len(rows)})]
        for start in range(0, len(rows), ROWS_PER_CHUNK):
            batch = rows[start : start + ROWS_PER_CHUNK]
            body = "\n".join(render_row(start + i + 1, row, columns) for i, row in enumerate(batch))
            end = start + len(batch)
            chunks.append(
                RawChunk(
                    f"Rows {start + 1}-{end} of table {rel}\n{body}",
                    {"kind": "rows", "row_start": start + 1, "row_end": end},
                )
            )
        title = humanize_filename(path).title()
        return ParsedDocument(
            path, Modality.TABLE, title, chunks, {"rows": len(rows), "columns": columns}
        )
