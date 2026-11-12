"""Small, dependency-free text utilities shared by BM25, the hashing embedder,
the query parser and the extractive answerer."""

from __future__ import annotations

import re

STOPWORDS: frozenset[str] = frozenset(
    """
    a about above after again against all am an and any are as at be because been
    before being below between both but by can could did do does doing down during
    each few for from further had has have having he her here hers herself him
    himself his how i if in into is it its itself just me more most my myself no nor
    not now of off on once only or other our ours ourselves out over own same she
    should so some such than that the their theirs them themselves then there these
    they this those through to too under until up very was we were what when where
    which while who whom why will with would you your yours yourself yourselves
    show tell explain describe give find please let us get also within use used
    using done like one two may might must shall
    """.split()
)

_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[`])")


# Bump when tokenisation or stemming changes: hashing-embedder vectors depend on
# it, so knowledge bases built with an older version are re-embedded on open.
TEXT_VERSION = 2

_STEP2 = (
    ("ational", "ate"),
    ("tional", "tion"),
    ("enci", "ence"),
    ("anci", "ance"),
    ("izer", "ize"),
    ("abli", "able"),
    ("alli", "al"),
    ("entli", "ent"),
    ("eli", "e"),
    ("ousli", "ous"),
    ("ization", "ize"),
    ("ation", "ate"),
    ("ator", "ate"),
    ("alism", "al"),
    ("iveness", "ive"),
    ("fulness", "ful"),
    ("ousness", "ous"),
    ("aliti", "al"),
    ("iviti", "ive"),
    ("biliti", "ble"),
)
_STEP3 = (
    ("icate", "ic"),
    ("ative", ""),
    ("alize", "al"),
    ("iciti", "ic"),
    ("ical", "ic"),
    ("ful", ""),
    ("ness", ""),
)
_STEP4 = (
    "ement",
    "ance",
    "ence",
    "able",
    "ible",
    "ment",
    "ant",
    "ent",
    "ism",
    "ate",
    "iti",
    "ous",
    "ive",
    "ize",
    "al",
    "er",
    "ic",
    "ou",
)
# Words whose trailing "s" is not a plural marker.
_KEEP_S = ("ss", "us", "is", "os")


def _consonant(word: str, i: int) -> bool:
    ch = word[i]
    if ch in "aeiou":
        return False
    if ch == "y":
        return i == 0 or not _consonant(word, i - 1)
    return True


def _measure(word: str) -> int:
    """Porter's *m*: the number of vowel-consonant sequences in ``word``."""
    m = 0
    prev_vowel = False
    for i in range(len(word)):
        vowel = not _consonant(word, i)
        if prev_vowel and not vowel:
            m += 1
        prev_vowel = vowel
    return m


def _has_vowel(word: str) -> bool:
    return any(not _consonant(word, i) for i in range(len(word)))


def _double_consonant(word: str) -> bool:
    return len(word) >= 2 and word[-1] == word[-2] and _consonant(word, len(word) - 1)


def _cvc(word: str) -> bool:
    """consonant-vowel-consonant ending, where the last consonant is not w, x or y."""
    if len(word) < 3:
        return False
    return (
        _consonant(word, len(word) - 3)
        and not _consonant(word, len(word) - 2)
        and _consonant(word, len(word) - 1)
        and word[-1] not in "wxy"
    )


def stem(token: str) -> str:
    """A light Porter-style stemmer.

    It follows the classic Porter steps (plurals, ``-ed``/``-ing``, ``-y``,
    derivational suffixes such as ``-ation``/``-ness``/``-ment``, final ``-e``)
    so related forms meet: ``expires``, ``expired``, ``expiry`` and
    ``expiration`` all become ``expir``. It stays conservative where Porter is
    known to misfire on technical text: tokens of three characters or fewer and
    tokens containing digits are left alone, and words ending in ``-us``,
    ``-is`` and ``-os`` (``status``, ``analysis``) keep their final ``s``.
    """
    if len(token) <= 3 or not token.isalpha() or not token.isascii():
        return token
    w = token

    # Step 1a: plurals.
    if w.endswith("sses") or w.endswith("ies"):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith(_KEEP_S):
        w = w[:-1]

    # Step 1b: -eed, -ed, -ing.
    if w.endswith("eed"):
        if _measure(w[:-3]) > 0:
            w = w[:-1]
    else:
        for suffix in ("ed", "ing"):
            if w.endswith(suffix) and _has_vowel(w[: -len(suffix)]):
                w = w[: -len(suffix)]
                if w.endswith(("at", "bl", "iz")):
                    w += "e"
                elif _double_consonant(w) and w[-1] not in "lsz":
                    w = w[:-1]
                elif _measure(w) == 1 and _cvc(w):
                    w += "e"
                break

    # Step 1c: terminal y -> i when the stem has a vowel (happy -> happi).
    if w.endswith("y") and len(w) > 2 and _has_vowel(w[:-1]):
        w = w[:-1] + "i"

    # Steps 2 and 3: map derivational suffixes onto simpler ones.
    for table in (_STEP2, _STEP3):
        for suffix, repl in table:
            if w.endswith(suffix):
                base = w[: -len(suffix)]
                if _measure(base) > 0:
                    w = base + repl
                break

    # Step 4: drop residual suffixes on longer stems.
    for suffix in _STEP4:
        if w.endswith(suffix):
            base = w[: -len(suffix)]
            if _measure(base) > 1:
                w = base
            break
    else:
        if w.endswith("ion") and _measure(w[:-3]) > 1 and w[:-3].endswith(("s", "t")):
            w = w[:-3]

    # Step 5: final -e and -ll.
    if w.endswith("e"):
        base = w[:-1]
        m = _measure(base)
        if m > 1 or (m == 1 and not _cvc(base)):
            w = base
    if w.endswith("ll") and _measure(w) > 1:
        w = w[:-1]

    # Light extension: a trailing i left over from -y (expiry -> expiri) is
    # dropped on longer stems so it meets expires/expired (-> expir).
    if w.endswith("i") and _measure(w[:-1]) > 1:
        w = w[:-1]
    return w or token


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens. CamelCase and snake_case identifiers are split
    into their parts (and the joined identifier is kept as well)."""
    out: list[str] = []
    for word in _WORD_RE.findall(text):
        parts = _CAMEL_RE.findall(word)
        if len(parts) > 1:
            out.extend(p.lower() for p in parts)
        out.append(word.lower())
    return out


def terms(text: str, *, keep_stopwords: bool = False) -> list[str]:
    """Normalised index/search terms: tokenized, stopwords removed, stemmed."""
    result = []
    for tok in tokenize(text):
        if not keep_stopwords and tok in STOPWORDS:
            continue
        if len(tok) == 1 and not tok.isdigit():
            continue
        result.append(stem(tok))
    return result


def split_sentences(text: str) -> list[str]:
    """Split text into sentences/lines suitable for extractive answering."""
    sentences: list[str] = []
    for block in re.split(r"\n\s*\n|\n(?=\s*[-*+]\s)|\n(?=#+\s)", text):
        block = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if not block:
            continue
        sentences.extend(s.strip() for s in _SENTENCE_RE.split(block) if s.strip())
    return sentences


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + "..."
