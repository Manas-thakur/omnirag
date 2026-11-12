"""Rank fusion."""

from __future__ import annotations


def reciprocal_rank_fusion(
    rankings: dict[str, list[str]],
    k: int = 60,
    weights: dict[str, float] | None = None,
) -> list[tuple[str, float, dict[str, int]]]:
    """Reciprocal Rank Fusion (Cormack et al., 2009).

    ``score(d) = sum_i w_i / (k + rank_i(d))`` with 1-based ranks.

    Returns ``[(id, fused_score, {ranking_name: rank})]`` sorted by score.
    """
    weights = weights or {}
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    for name, ids in rankings.items():
        w = weights.get(name, 1.0)
        for rank, item in enumerate(ids, start=1):
            scores[item] = scores.get(item, 0.0) + w / (k + rank)
            ranks.setdefault(item, {})[name] = rank
    order = sorted(scores, key=lambda i: (-scores[i], min(ranks[i].values()), i))
    return [(i, scores[i], ranks[i]) for i in order]
