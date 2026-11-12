"""Regenerate ``corpus/diagrams/deployment-topology.png`` (stdlib only).

Draws a tiny two-region topology sketch and embeds ``Title``/``Description``
PNG text chunks, which OmniRAG's image ingestor reads without any extra
dependencies. The richer caption lives in the sidecar ``.png.txt`` file.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

W, H = 160, 90
BG = (247, 247, 245)
REGION = (31, 111, 235)
POD = (46, 125, 50)
DB = (239, 108, 0)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def draw() -> list[list[tuple[int, int, int]]]:
    px = [[BG for _ in range(W)] for _ in range(H)]

    def rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int], fill: bool) -> None:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if fill or y in (y0, y1) or x in (x0, x1):
                    px[y][x] = color

    for ox in (6, 84):  # two regions
        rect(ox, 6, ox + 70, 83, REGION, False)
        for i in range(3):  # three API replicas
            rect(ox + 8 + i * 20, 16, ox + 22 + i * 20, 30, POD, True)
        rect(ox + 22, 56, ox + 48, 74, DB, True)  # database
    for x in (35, 113):
        for y in range(31, 56):
            px[y][x] = (90, 90, 90)
    for x in range(55, 110):  # replication link
        px[65][x] = (90, 90, 90)
    return px


def build_png() -> bytes:
    raw = b"".join(b"\x00" + bytes(c for p in row for c in p) for row in draw())
    text = [
        (b"Title", b"Deployment topology"),
        (
            b"Description",
            b"Two regions (us-east, eu-west), three API replicas each, primary database with a read replica",
        ),
    ]
    out = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    for key, value in text:
        out += _chunk(b"tEXt", key + b"\x00" + value)
    out += _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")
    return out


if __name__ == "__main__":
    target = Path(__file__).parent / "corpus" / "diagrams" / "deployment-topology.png"
    target.write_bytes(build_png())
    print(f"wrote {target} ({target.stat().st_size} bytes)")
