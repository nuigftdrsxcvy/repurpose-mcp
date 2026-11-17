"""Deterministic candidate ordering, shared by the brief prompt's instructions and the recall eval."""

from __future__ import annotations

from dataclasses import dataclass

from repurpose_mcp.models import ApprovedDrug, ApprovedDrugsResult, DiseaseTargetsResult


@dataclass(frozen=True)
class RankedCandidate:
    rank: int
    drug: ApprovedDrug
    best_target_symbol: str
    best_target_score: float


def rank_candidates(targets: DiseaseTargetsResult, drugs: ApprovedDrugsResult) -> list[RankedCandidate]:
    """Order drugs by the highest disease-association score among the targets they act on, then by
    how many of the disease's targets they hit, then by name. This orders by *target* evidence only;
    it says nothing about whether the drug works."""
    scores = {t.target_id: (t.overall_score, t.symbol) for t in targets.targets}
    scored = []
    for d in drugs.drugs:
        best = max((scores[t] for t in d.query_target_ids if t in scores), default=(0.0, ""))
        scored.append((best, d))
    scored.sort(key=lambda x: (-x[0][0], -len(x[1].query_target_ids), x[1].name))
    return [
        RankedCandidate(rank=i, drug=d, best_target_symbol=best[1], best_target_score=best[0])
        for i, (best, d) in enumerate(scored, start=1)
    ]
