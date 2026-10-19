from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claim_layer.store import ClaimLayerStore
from typing import Literal


def _dedup_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Evidence must be deduplicated at the source-unit level before support aggregation.

    Repeated extractions of the same normalized claim from the same source unit
    must not increase support more than once.

    Groups items by source unit. Within each group the item with the highest score
    is selected for aggregation; the rest are marked selected=False with
    reason="duplicate". All items are returned so the full evidence trace is
    preserved in the output.
    """
    by_source: dict[Any, list[dict[str, Any]]] = {}
    for ev in evidence:
        by_source.setdefault(ev.get("source"), []).append(ev)

    result: list[dict[str, Any]] = []
    for group in by_source.values():
        # highest score wins; claim_id asc as deterministic tiebreaker
        ranked = sorted(group, key=lambda e: (-e["score"], e["claim_id"]))
        for i, ev in enumerate(ranked):
            result.append({**ev, "selected": i == 0, "reason": None if i == 0 else "duplicate"})

    # stable order: selected first, then by claim_id
    result.sort(key=lambda e: (not e["selected"], e["claim_id"]))
    return result


def _build_explanation(
    evidence: list[dict[str, Any]],
    penalty: float,
    num_values: int,
) -> dict[str, Any]:
    """Build a human-readable confidence explanation from deduped evidence.

    Does not perform any computation — reads values already calculated by
    resolve_truth so the explanation is guaranteed to match the actual output.
    """
    total = len(evidence)
    selected_items = [ev for ev in evidence if ev["selected"]]
    selected = len(selected_items)
    duplicates = total - selected

    if duplicates == 0:
        summary = (
            f"{selected} piece{'s' if selected != 1 else ''} of evidence "
            f"support{'s' if selected == 1 else ''} this value"
        )
    else:
        summary = (
            f"{selected} independent piece{'s' if selected != 1 else ''} of evidence "
            f"support{'s' if selected == 1 else ''} this value "
            f"({total} total, {duplicates} duplicate{'s' if duplicates != 1 else ''} removed)"
        )

    penalty_reason = (
        f"{num_values} competing values detected — confidence scaled by this "
        f"value's share of total support (weighted penalty, not flat 1/n)"
        if num_values > 1
        else "no competing values"
    )

    return {
        "selected_evidence_count": selected,
        "total_evidence_count": total,
        "selected_evidence": [
            {"claim_id": ev["claim_id"], "score": ev["score"]}
            for ev in selected_items
        ],
        "aggregation_method": "aggregate_support(strategy='noisy_or')",
        "penalty": penalty,
        "penalty_reason": penalty_reason,
        "final_confidence_formula": "aggregate_support(scores) × (value_support / total_support)",
        "summary": summary,
    }


AggregationStrategy = Literal["noisy_or", "sum_norm", "max", "custom"]


def noisy_or(confidences: list[float]) -> float:
    """Backward-compatible alias for noisy-or support aggregation."""
    return aggregate_support(confidences, strategy="noisy_or")

def aggregate_support(confidences: list[float], strategy: AggregationStrategy = "noisy_or") -> float:
    """
    Computes confidence as a monotonic aggregation over observable supporting evidence.

    Properties:
    - Monotonic: adding evidence never decreases confidence
    - Non-linear: diminishing returns allowed
    - Evidence-bound: no inference beyond observed support
    """
    if strategy == "noisy_or":
        result = 1.0
        for c in confidences:
            result *= 1.0 - max(0.0, min(1.0, c))
        return round(1.0 - result, 6)
    
    # Fallback/default placeholder
    return 0.0


def resolve_truth(
    store: ClaimLayerStore,
    weighted_facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not weighted_facts:
        return []

    # Step 1 — compute raw aggregate support per group, bucket by (entity, predicate)
    # Evidence is pre-fetched by weight_evidence; no DB query needed here.
    #
    # Groups with the same canonical_value are merged into a single candidate.
    # This collapses e.g. "30 days" and "thirty days" into the same resolution
    # group so they do not appear as contradictions.
    by_predicate: dict[tuple[str, str], dict[Any, dict[str, Any]]] = {}
    for group in weighted_facts:
        entity = group.get("entity") or ""
        predicate = group.get("predicate") or ""
        value = group.get("value") or ""
        canonical_value = group.get("canonical_value", value)
        evidence: list[dict[str, Any]] = group.get("evidence") or []

        # Deduplicate before aggregation — preserves all items with selected/reason flags
        deduped = _dedup_evidence(evidence)
        selected_scores = [ev["score"] for ev in deduped if ev["selected"]]
        raw_confidence = aggregate_support(selected_scores) if selected_scores else 0.0

        key = (entity, predicate)
        if key not in by_predicate:
            by_predicate[key] = {}

        # Sum of selected scores for this surface form — used to elect the
        # representative value after all groups are merged.
        selected_sum = sum(ev["score"] for ev in deduped if ev["selected"])

        if canonical_value not in by_predicate[key]:
            by_predicate[key][canonical_value] = {
                "canonical_value": canonical_value,
                "raw_confidence": raw_confidence,
                "evidence": deduped,
                # surface_forms: raw value string → cumulative selected score
                # Used to elect the best representative after merging.
                "surface_forms": {value: selected_sum},
            }
        else:
            # Merge into existing canonical group — accumulate evidence and
            # re-compute aggregated support over the combined selected scores.
            existing = by_predicate[key][canonical_value]
            merged_evidence = _dedup_evidence(existing["evidence"] + deduped)
            merged_selected = [ev["score"] for ev in merged_evidence if ev["selected"]]

            surface_forms = dict(existing["surface_forms"])
            surface_forms[value] = surface_forms.get(value, 0.0) + selected_sum

            by_predicate[key][canonical_value] = {
                "canonical_value": canonical_value,
                "raw_confidence": aggregate_support(merged_selected) if merged_selected else 0.0,
                "evidence": merged_evidence,
                "surface_forms": surface_forms,
            }

    # Step 2 — contradiction handling, best value selection, extended output
    results: list[dict[str, Any]] = []
    for (entity, predicate), canonical_groups in by_predicate.items():
        candidates = list(canonical_groups.values())
        num_values = len(candidates)
        # The store lacks scope metadata; the public facade refines this with
        # the full claims. Predicate cardinality alone can already rule out
        # false contradictions for multivalued and catch-all predicates.
        from core.inference_engine import is_functional_predicate
        functional = is_functional_predicate(predicate)
        has_contradictions = num_values > 1 and functional is True

        # Weighted contradiction penalty (unified inference-engine semantics):
        # each candidate keeps a share of its confidence proportional to its
        # own support relative to all competing values — NOT the legacy flat
        # 1/num_values. A weakly supported dissenter barely dents a
        # well-supported fact; an even split still halves confidence.
        total_support = sum(c["raw_confidence"] for c in candidates)

        scored = []
        for c in candidates:
            if has_contradictions and total_support > 0:
                if num_values == 2:
                    penalty = c["raw_confidence"] / total_support
                else:
                    competing = [other["raw_confidence"] for other in candidates if other is not c]
                    competing_support = aggregate_support(competing, strategy="noisy_or")
                    effective_total = c["raw_confidence"] + competing_support
                    penalty = c["raw_confidence"] / effective_total if effective_total > 0 else 1.0
            else:
                penalty = 1.0
            # Elect representative surface form: highest cumulative selected score.
            # Tiebreaker: value string ASC (deterministic, ingestion-order-independent).
            representative = sorted(
                c["surface_forms"],
                key=lambda v: (-c["surface_forms"][v], v),
            )[0]
            scored.append(
                {
                    "value": representative,
                    "canonical_value": c["canonical_value"],
                    "confidence": round(c["raw_confidence"] * penalty, 6),
                    "penalty": round(penalty, 6),
                    "evidence": c["evidence"],
                }
            )
        # deterministic: confidence desc, value asc as tiebreaker
        scored.sort(key=lambda c: (-c["confidence"], c["value"]))

        best = scored[0]
        others = scored[1:]

        results.append(
            {
                "entity": entity,
                "predicate": predicate,
                "value": best["value"],
                "canonical_value": best["canonical_value"],
                "confidence": best["confidence"],
                "confidence_explanation": _build_explanation(
                    best["evidence"], best["penalty"], num_values if has_contradictions else 1
                ),
                "contradictions": [
                    {
                        "value": alt["value"],
                        "canonical_value": alt["canonical_value"],
                        "confidence": alt["confidence"],
                    }
                    for alt in others if has_contradictions
                ],
                "compatible_values": [dict(alt) for alt in others if functional is False],
                "unresolved_comparisons": [dict(alt, comparison="unknown") for alt in others if functional is None],
                "supporting_evidence": best["evidence"],
                "alternative_evidence": [
                    {
                        "value": alt["value"],
                        "canonical_value": alt["canonical_value"],
                        "evidence": alt["evidence"],
                    }
                    for alt in others
                ],
            }
        )

    # stable output order: entity asc, predicate asc
    results.sort(key=lambda r: (r["entity"], r["predicate"]))
    return results
