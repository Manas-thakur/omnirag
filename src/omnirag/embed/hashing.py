"""Dependency-free, deterministic default embedder.

Uses the *hashing trick*: every feature (word unigram, word bigram and
character 4-grams inside longer words) is hashed with CRC32 into one of
``dimension`` buckets with a pseudo-random sign. Term frequencies are
sub-linearly scaled (``1 + log tf``) and the vector is L2-normalised, so the dot
product is the cosine similarity.

It is not a neural model, but it is fast, works offline, needs no downloads,
and gives stable results across machines and Python versions, which makes it
ideal as a default and for tests. The character n-grams give some robustness
to morphology ("authenticate" vs "authentication").
"""

from __future__ import annotations

import math
import zlib
from collections import Counter
from functools import lru_cache
from itertools import pairwise

import numpy as np

from omnirag.embed.base import Embedder, l2_normalize
from omnirag.textutil import terms

UNIGRAM_WEIGHT = 1.0
BIGRAM_WEIGHT = 0.6
CHARGRAM_WEIGHT = 0.25
CHARGRAM_N = 4


@lru_cache(maxsize=200_000)
def _bucket(feature: str, dimension: int) -> tuple[int, float]:
    h = zlib.crc32(feature.encode("utf-8"))
    sign = 1.0 if (zlib.crc32(b"#" + feature.encode("utf-8")) & 1) else -1.0
    return h % dimension, sign


def features(text: str) -> Counter[str]:
    toks = terms(text)
    feats: Counter[str] = Counter()
    for tok in toks:
        feats["w:" + tok] += 1
    for a, b in pairwise(toks):
        feats["b:" + a + " " + b] += 1
    for tok in toks:
        if len(tok) >= 6:
            padded = f"<{tok}>"
            for i in range(len(padded) - CHARGRAM_N + 1):
                feats["c:" + padded[i : i + CHARGRAM_N]] += 1
    return feats


class HashingEmbedder(Embedder):
    def __init__(self, dimension: int = 2048) -> None:
        if dimension < 16:
            raise ValueError("dimension must be >= 16")
        self._dimension = dimension
        self.name = f"hashing:{dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vector(self, text: str) -> np.ndarray:
        vec = np.zeros(self._dimension, dtype=np.float32)
        for feat, count in features(text).items():
            kind = feat[0]
            weight = (
                UNIGRAM_WEIGHT if kind == "w" else BIGRAM_WEIGHT if kind == "b" else CHARGRAM_WEIGHT
            )
            idx, sign = _bucket(feat, self._dimension)
            vec[idx] += sign * weight * (1.0 + math.log(count))
        return vec

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        return l2_normalize(np.stack([self._vector(t) for t in texts]))
