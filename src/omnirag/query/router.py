"""Modality routing: turns a parsed query into a retrieval plan.

Explicit filters (``modality:code``) are *hard* constraints. Keyword hints
("show me the diagram") and intent are *soft*: they boost matching modalities
during reranking instead of excluding everything else, so a wrong guess never
hides the right answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from omnirag.query.parser import ParsedQuery, QueryIntent
from omnirag.store.models import Modality, SearchFilters

HINT_BOOST = 1.25
INTENT_BOOST = 1.15


@dataclass
class RetrievalPlan:
    filters: SearchFilters
    boosts: dict[Modality, float] = field(default_factory=dict)
    k: int = 5
    candidate_k: int = 40
    neighbors: int = 1

    def boost_for(self, modality: Modality) -> float:
        return self.boosts.get(modality, 1.0)


class ModalityRouter:
    def __init__(self, hint_boost: float = HINT_BOOST, intent_boost: float = INTENT_BOOST):
        self.hint_boost = hint_boost
        self.intent_boost = intent_boost

    def route(
        self,
        parsed: ParsedQuery,
        k: int = 5,
        extra_filters: SearchFilters | None = None,
        neighbors: int = 1,
    ) -> RetrievalPlan:
        filters = parsed.filters.merge(extra_filters)
        boosts: dict[Modality, float] = {}
        for modality in parsed.modality_hints:
            boosts[modality] = boosts.get(modality, 1.0) * self.hint_boost
        if parsed.intent == QueryIntent.CODE:
            boosts[Modality.CODE] = boosts.get(Modality.CODE, 1.0) * self.intent_boost
        if filters.modalities and len(filters.modalities) == 1:
            boosts = {}
        return RetrievalPlan(
            filters=filters,
            boosts=boosts,
            k=k,
            candidate_k=max(20, k * 8),
            neighbors=neighbors,
        )
