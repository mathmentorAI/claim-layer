"""
Unified inference engine — canonical resolution flow for typed evidence.

This module consolidates the three previously divergent resolution paths
(core.claim_layer weighted clusters, claim_layer.semantic noisy-OR, and the
API evidence engine bands) into one auditable pipeline:

  1. Temporal validity  — claims outside their [valid_from, valid_until]
     window at evaluation time cannot support a resolution.
  2. Grouping           — claims cluster by normalized value; equivalent
     surface forms ("30 days" / "thirty days") merge into one candidate.
  3. Source dedup       — repeated claims from the same document count once
     per value group (anti-inflation guarantee, mirrors claim-layer G4).
  4. Weighted election  — group support = noisy-OR over
     (confidence × inference_weight); the structurally strongest group wins.
  5. Weighted penalty   — contradictions reduce confidence proportionally to
     the losing groups' weighted support, NOT a flat 1/n. A junk heuristic
     claim can no longer halve the confidence of a well-supported fact.
  6. Final confidence   — noisy-OR of the winner's raw confidences × penalty.

resolve_claims_detailed() returns the full trace (per-claim weights, group
supports, both penalty formulas) so every number in the output is derivable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from core.interfaces import (
    Claim,
    InferenceProfile,
    INFERENCE_WEIGHTS,
    Reason,
    Result,
)
from core.source_precedence import get_origin_rank
from core.epistemic_judge import EpistemicJudge

try:  # optional — reuse packaged normalizer when the claim-layer lib is installed
    from claim_layer.semantic.normalization import normalize_value as _normalize_value
except Exception:  # pragma: no cover - environment-dependent
    try:
        # Same vendored-source fallback as core.claim_layer_adapter, so value
        # grouping is identical regardless of module import order.
        import sys
        from pathlib import Path

        _SRC = Path(__file__).parent.parent / "claim-layer" / "src"
        if str(_SRC) not in sys.path:
            sys.path.insert(0, str(_SRC))
        from claim_layer.semantic.normalization import normalize_value as _normalize_value
    except Exception:
        def _normalize_value(value):  # type: ignore[misc]
            return value


def _noisy_or(confidences: List[float]) -> float:
    """Monotonic, evidence-bound support fusion (same formula as claim-layer)."""
    result = 1.0
    for c in confidences:
        result *= 1.0 - max(0.0, min(1.0, c))
    return round(1.0 - result, 6)


def _weight_for(claim: Claim, profile: Optional[InferenceProfile]) -> float:
    if profile is not None:
        return profile.resolve_weight(claim.inference_type)
    return INFERENCE_WEIGHTS.get(claim.inference_type, 0.5)


def _parse_instant(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def allen_interval_precedes(older: Claim, newer: Claim) -> bool:
    """
    Allen's Interval Algebra (Precedes / Meets):
    Returns True if `older` has a closed upper bound `u1` and `newer` has a lower bound `f2`
    such that `u1 <= f2` (disjoint temporal intervals I_1 ∩ I_2 = ∅), and their values differ.
    Disjoint historical intervals form a piecewise timeline, NOT a simultaneous contradiction.
    """
    u1 = _parse_instant(getattr(older, "valid_until", None))
    f2 = _parse_instant(getattr(newer, "valid_from", None))
    if u1 is None or f2 is None:
        return False
    if u1 > f2:
        return False
    return str(getattr(older, "value", "")) != str(getattr(newer, "value", ""))


_MONTH_MAP = {
    "enero": 1, "january": 1, "jan": 1,
    "febrero": 2, "february": 2, "feb": 2,
    "marzo": 3, "march": 3, "mar": 3,
    "abril": 4, "april": 4, "apr": 4,
    "mayo": 5, "may": 5,
    "junio": 6, "june": 6, "jun": 6,
    "julio": 7, "july": 7, "jul": 7,
    "agosto": 8, "august": 8, "aug": 8,
    "septiembre": 9, "september": 9, "sep": 9,
    "octubre": 10, "october": 10, "oct": 10,
    "noviembre": 11, "november": 11, "nov": 11,
    "diciembre": 12, "december": 12, "dec": 12,
}


def extract_temporal_as_of(query: str) -> Optional[datetime]:
    """
    Extract an explicit Point-in-Time (`as_of`) evaluation timestamp from a natural-language
    query (e.g. 'en fecha 2023-06-15', 'as of 2023-06-15', 'en marzo de 2024', 'en el año 2023').
    Returns None if the query does not specify a historical/point-in-time anchor.
    """
    if not query:
        return None
    import re
    low = query.lower()

    # 1. Explicit ISO date YYYY-MM-DD
    m_iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", low)
    if m_iso:
        return _parse_instant(m_iso.group(1))

    # 2. Month + Year (e.g. "en marzo de 2024", "in march 2024")
    m_my = re.search(
        r"\b(?:en|in|de|of|durante|during)\s+([a-záéíóú]+)\s+(?:de\s+|del\s+|of\s+)?(20\d{2}|19\d{2})\b",
        low,
    )
    if m_my and m_my.group(1) in _MONTH_MAP:
        month = _MONTH_MAP[m_my.group(1)]
        year = int(m_my.group(2))
        return datetime(year, month, 15, tzinfo=timezone.utc)

    # 3. Explicit year anchor ("en el año 2023", "en 2023", "in 2023", "during 2023")
    m_yr = re.search(r"\b(?:en(?:\s+el\s+a[ñn]o)?|in|during|durante(?:\s+el\s+a[ñn]o)?)\s+(20\d{2}|19\d{2})\b", low)
    if m_yr:
        year = int(m_yr.group(1))
        return datetime(year, 6, 15, tzinfo=timezone.utc)

    return None


def _is_active(claim: Claim, now: datetime) -> Tuple[bool, Optional[str]]:
    """Return (active, reason) for a claim's validity window at *now*."""
    start = _parse_instant(claim.valid_from)
    end = _parse_instant(claim.valid_until)
    if start is not None and now < start:
        return False, "not_yet_valid"
    if end is not None and now > end:
        return False, "expired"
    return True, None


def _canonical(value: Any) -> Any:
    if isinstance(value, str):
        return _normalize_value(value)
    return value


_MULTIVALUED_PREDICATES = frozenset({
    "sede", "sedes", "oficina", "oficinas", "office", "offices", "location", "locations",
    "office_location", "branch", "sucursal", "sucursales", "filial", "filiales",
    "subsidiary", "subsidiaries", "delito", "delitos", "cargo_historico",
    "symptom", "symptoms", "sintoma", "sintomas", "idioma", "idiomas", "skill", "skills",
})

_CATCHALL_PREDICATES = frozenset({
    "general", "statement", "unknown", "other", "misc", "fact", "claim",
})


def is_functional_predicate(predicate: Optional[str]) -> Optional[bool]:
    """
    Implements Section 4.1 of the revised paper (Oct 2026):
    - Returns False for multivalued predicates (e.g. office locations, subsidiaries).
    - Returns None for catch-all predicates ('general', 'statement') which lack
      sufficiently precise semantics to establish contradiction from value inequality alone.
    - Returns True for functional predicates (at most one value per entity, scope, and interval).
    """
    if not predicate:
        return None
    norm_p = str(predicate).strip().lower()
    if norm_p in _CATCHALL_PREDICATES:
        return None
    if norm_p in _MULTIVALUED_PREDICATES:
        return False
    return True


def compare_claims_three_valued(u_i: Claim, u_j: Claim) -> str:
    """
    Implements Section 4.2 & Proposition 2 of the revised paper (Oct 2026):
        Cmp_Theta(u_i, u_j) -> 'compatible' | 'incompatible' | 'unknown'

    An incompatibility decision requires all of:
      1. The same resolved subject and predicate.
      2. Comparable attribution and modality.
      3. Overlapping applicable temporal and domain scope.
      4. A functional predicate under which normalized values differ.
    Missing temporal scope where it could change the comparison, catch-all predicates,
    or incomparable attribution (allegation vs finding) yield 'unknown'.
    Disjoint temporal intervals or multivalued predicates yield 'compatible'.
    """
    ent_i = str(getattr(u_i, "canonical_entity", None) or u_i.entity or "").strip().lower()
    ent_j = str(getattr(u_j, "canonical_entity", None) or u_j.entity or "").strip().lower()
    if not ent_i or not ent_j or ent_i != ent_j:
        return "compatible"

    pred_i = str(getattr(u_i, "canonical_predicate", None) or u_i.predicate or "").strip().lower()
    pred_j = str(getattr(u_j, "canonical_predicate", None) or u_j.predicate or "").strip().lower()
    if not pred_i or not pred_j or pred_i != pred_j:
        return "compatible"

    func_status = is_functional_predicate(pred_i)
    if func_status is None:
        # Catch-all predicate ('general', 'statement') cannot establish incompatibility from value inequality
        return "unknown"
    if func_status is False:
        # Multivalued predicate (e.g., two offices under 'location') -> compatible
        return "compatible"

    val_i = _canonical(getattr(u_i, "canonical_value", None) or u_i.value)
    val_j = _canonical(getattr(u_j, "canonical_value", None) or u_j.value)
    if val_i == val_j:
        return "compatible"

    # Attribution check: allegation vs authoritative finding requires attribution-aware interpretation
    from core.epistemic_judge import UNVERIFIED_SPEAKER_ROLES
    role_i = (getattr(u_i, "speaker_role", None) or "").strip().upper()
    role_j = (getattr(u_j, "speaker_role", None) or "").strip().upper()
    if (role_i in UNVERIFIED_SPEAKER_ROLES) != (role_j in UNVERIFIED_SPEAKER_ROLES):
        return "unknown"

    # Disjoint validity periods or explicit state supersession describe change, not conflict
    from core.aggregation_engine import is_state_supersession
    if (
        allen_interval_precedes(u_i, u_j)
        or allen_interval_precedes(u_j, u_i)
        or is_state_supersession(u_i, u_j)
        or is_state_supersession(u_j, u_i)
    ):
        return "compatible"

    # Missing effective date on one side while the other has a bounded interval
    has_time_i = bool(u_i.valid_from or u_i.valid_until)
    has_time_j = bool(u_j.valid_from or u_j.valid_until)
    if has_time_i != has_time_j:
        return "unknown"

    return "incompatible"


def compute_bounded_conflict_index(sg: float, og: float) -> float:
    """
    Implements Section 5.3 & Proposition 3 of the revised paper (Oct 2026):
        Q_g = S_g^2 / (S_g + O_g)  if S_g + O_g > 0 else 0.0
    Satisfies 0 <= Q_g <= S_g <= 1, non-increasing in O_g and non-decreasing in S_g.
    """
    sg_c = max(0.0, min(1.0, float(sg)))
    og_c = max(0.0, min(1.0, float(og)))
    denom = sg_c + og_c
    if denom <= 0.0:
        return 0.0
    return round((sg_c * sg_c) / denom, 6)


def _dependence_key(claim: Claim) -> str:
    """Return dependence group identifier d in D_g (explicit `dependence_group` or document origin)."""
    dep = getattr(claim, "dependence_group", None)
    if dep and str(dep).strip():
        return str(dep).strip()
    if claim.source and claim.source.document_id:
        return str(claim.source.document_id)
    return f"__none__{claim.id}"


def resolve_claims_detailed(
    claims: List[Claim],
    *,
    inference_profile: Optional[InferenceProfile] = None,
    now: Optional[datetime] = None,
    penalty_strategy: str = "dynamic_normalized",
    noise_threshold: float = 0.0,
    verified_premise_ids: Optional[Set[str]] = None,
    require_declared_premises: bool = False,
) -> Dict[str, Any]:
    """Resolve claims and return {"result": Result, "trace": {...}}."""
    if not claims:
        return {
            "result": Result(None, 0.0, [], [], reason=Reason.NO_CLAIMS),
            "trace": {"groups": [], "inactive_claims": []},
        }

    eval_time = now or datetime.now(timezone.utc)

    # Step 1 — temporal validity
    active: List[Claim] = []
    inactive: List[Dict[str, Any]] = []
    for claim in claims:
        ok, why = _is_active(claim, eval_time)
        if ok:
            active.append(claim)
        else:
            inactive.append({
                "claim_id": claim.id,
                "value": claim.value,
                "reason": why,
                "valid_from": claim.valid_from,
                "valid_until": claim.valid_until,
            })

    if not active:
        return {
            "result": Result(None, 0.0, [], [], reason=Reason.STALE_EVIDENCE),
            "trace": {"groups": [], "inactive_claims": inactive,
                      "evaluated_at": eval_time.isoformat()},
        }

    # Step 1b — Decoupled Epistemic Audit (neutralize adversarial self-labeling & verify premises)
    judge = EpistemicJudge()
    active, audit_trace = judge.audit_and_sanitize_claims(
        active,
        verified_premise_ids=verified_premise_ids,
        require_declared_premises=require_declared_premises,
    )

    # Step 1c — Temporal State Supersession & Allen's Interval Algebra (Precedes/Meets):
    # Move superseded states and strictly disjoint historical intervals to inactive so they
    # do not penalize the current active state as a false simultaneous contradiction.
    from core.aggregation_engine import is_state_supersession

    non_superseded: List[Claim] = []
    for cand in active:
        if any(is_state_supersession(cand, other) for other in active if other is not cand):
            inactive.append({
                "claim_id": cand.id,
                "value": cand.value,
                "reason": "superseded_state",
                "valid_from": cand.valid_from,
                "valid_until": cand.valid_until,
            })
        elif any(allen_interval_precedes(cand, other) for other in active if other is not cand):
            inactive.append({
                "claim_id": cand.id,
                "value": cand.value,
                "reason": "allen_precedes_disjoint_interval",
                "valid_from": cand.valid_from,
                "valid_until": cand.valid_until,
            })
        else:
            non_superseded.append(cand)
    if non_superseded:
        active = non_superseded

    # Step 1d — Non-Monotonic Truth Maintenance (JTMS — Pollock's Undercutting Defeaters):
    # If a derived claim explicitly depends on a premise that was deactivated (expired,
    # not_yet_valid, superseded_state, or disjoint historical interval), retract the
    # orphan conclusion in cascade.
    retracted_ids: Set[str] = {
        str(item["claim_id"]) for item in inactive if item.get("claim_id")
    }
    if retracted_ids:
        changed = True
        while changed:
            changed = False
            remaining_active: List[Claim] = []
            for cand in active:
                cand_premises = getattr(cand, "premises", []) or []
                failed_premises = [p for p in cand_premises if str(p) in retracted_ids]
                if failed_premises:
                    inactive.append({
                        "claim_id": cand.id,
                        "value": cand.value,
                        "reason": "undercut_by_inactive_premise",
                        "undercut_by": failed_premises,
                        "valid_from": cand.valid_from,
                        "valid_until": cand.valid_until,
                    })
                    if cand.id:
                        retracted_ids.add(str(cand.id))
                    changed = True
                else:
                    remaining_active.append(cand)
            active = remaining_active

        if not active:
            return {
                "result": Result(None, 0.0, [], [], reason=Reason.STALE_EVIDENCE),
                "trace": {
                    "groups": [],
                    "inactive_claims": inactive,
                    "evaluated_at": eval_time.isoformat(),
                },
            }

    # Invalid proofs cannot contribute support or opposition, even when callers
    # use the resolver without the optional post-resolution grounding gate.
    invalid_proofs = {
        item["claim_id"] for item in audit_trace
        if item.get("derivation_status") == "unverified"
    }
    rejected_derivations = [
        c for c in active
        if (c.premises or c.derivation_rule) and c.id in invalid_proofs
    ]
    active = [c for c in active if c not in rejected_derivations]
    if not active:
        return {
            "result": Result(None, 0.0, [], [], reason=Reason.BLOCKED_INFERENCE),
            "trace": {"groups": [], "inactive_claims": inactive, "epistemic_audit": audit_trace},
        }

    # Step 2 — group by canonical value
    groups: Dict[Any, List[Claim]] = {}
    for claim in active:
        groups.setdefault(_canonical(claim.value), []).append(claim)

    # Steps 3 & 4 — per-group dependence-group dedup (b_{g,d} = max_{u_i in g cap d} a_i) + noisy-OR S_g + origin tier
    group_traces: List[Dict[str, Any]] = []
    for canonical_value, members in groups.items():
        # dedup by dependence group (or source document): keep the highest weighted score per group d
        by_doc: Dict[str, Claim] = {}
        for claim in members:
            doc = _dependence_key(claim)
            current = by_doc.get(doc)
            score = claim.confidence * _weight_for(claim, inference_profile)
            if current is None or score > current.confidence * _weight_for(current, inference_profile):
                by_doc[doc] = claim

        selected = sorted(by_doc.values(), key=lambda c: c.id)
        weighted_scores = [
            round(c.confidence * _weight_for(c, inference_profile), 6) for c in selected
        ]
        origin_rank = max(get_origin_rank(c) for c in members)
        group_traces.append({
            "canonical_value": canonical_value,
            "origin_rank": origin_rank,
            "claims": members,
            "selected": selected,
            "dependence_groups": sorted(list(by_doc.keys())),
            "evidence": [
                {
                    "claim_id": c.id,
                    "inference_type": c.inference_type,
                    "confidence": c.confidence,
                    "weight": _weight_for(c, inference_profile),
                    "weighted_score": s,
                }
                for c, s in zip(selected, weighted_scores)
            ],
            "weighted_support": _noisy_or(weighted_scores),
            "raw_confidence": _noisy_or([c.confidence for c in selected]),
        })

    # deterministic election: origin precedence first, then weighted support desc, value asc as tiebreaker
    group_traces.sort(
        key=lambda g: (-g["origin_rank"], -g["weighted_support"], str(g["canonical_value"]))
    )
    winner = group_traces[0]
    losers = group_traces[1:]

    # Step 5 — only proven incompatibilities contribute opposing support.
    # Preserve compatible and unknown alternatives separately for callers.
    winner_origin_rank = winner["origin_rank"]
    winner_rep_claim = max(winner["selected"], key=lambda c: c.confidence)
    opp_by_dep: Dict[str, float] = {}
    unresolved_comparisons: List[Dict[str, Any]] = []
    compatible_values: List[Dict[str, Any]] = []
    contradictions: List[Claim] = []
    effective_losers_support: List[float] = []
    raw_opposing_support: List[float] = []
    for g in losers:
        attenuation = min(1.0, g["origin_rank"] / winner_origin_rank) if winner_origin_rank > 0 else 1.0
        group_opposition: Dict[str, float] = {}
        for c in g["claims"]:
            cmp_state = compare_claims_three_valued(winner_rep_claim, c)
            if cmp_state != "incompatible":
                entry = {
                    "claim_id": c.id, "value": c.value, "comparison": cmp_state,
                    "confidence": c.confidence,
                    "source": {"document_id": c.source.document_id,
                               "page": c.source.page, "paragraph_id": c.source.paragraph_id},
                }
                (compatible_values if cmp_state == "compatible" else unresolved_comparisons).append(entry)
                continue
            contradictions.append(c)
            dep_d = _dependence_key(c)
            c_score = round(c.confidence * _weight_for(c, inference_profile), 6)
            group_opposition[dep_d] = max(group_opposition.get(dep_d, 0.0), c_score)
        support = _noisy_or(list(group_opposition.values()))
        if not group_opposition or support < noise_threshold:
            continue
        raw_opposing_support.append(support)
        effective_losers_support.append(support * attenuation)
        for dep_d, c_score in group_opposition.items():
            opp_by_dep[dep_d] = max(opp_by_dep.get(dep_d, 0.0), c_score * attenuation)

    total_support = winner["weighted_support"] + sum(raw_opposing_support)
    legacy_penalty = 1.0 / (1 + len(raw_opposing_support))

    sg_index = winner["weighted_support"]
    og_index = _noisy_or(list(opp_by_dep.values())) if opp_by_dep else 0.0
    qg_index = compute_bounded_conflict_index(sg_index, og_index)

    if not effective_losers_support or total_support <= 0:
        penalty = 1.0
        competing_support = 0.0
    elif penalty_strategy == "paper_qg":
        competing_support = og_index
        effective_total = sg_index + og_index
        penalty = (sg_index / effective_total) if effective_total > 0 else 1.0
    elif penalty_strategy == "legacy_linear":
        penalty = winner["weighted_support"] / total_support
        competing_support = total_support - winner["weighted_support"]
    elif len(effective_losers_support) == 1 and noise_threshold == 0.0:
        # Canonical binary dispute: preserves exact contract for 2-group disputes
        competing_support = effective_losers_support[0] if effective_losers_support else 0.0
        effective_total = winner["weighted_support"] + competing_support
        penalty = (winner["weighted_support"] / effective_total) if effective_total > 0 else 1.0
    elif penalty_strategy == "dynamic_normalized":
        # Multi-group dispute (N > 2):
        # Treat competing alternatives probabilistically (bounded by 1.0 via noisy-OR)
        # to avoid linear accumulation dilution from long-tail extraction noise.
        competing_support = _noisy_or(effective_losers_support)
        effective_total = winner["weighted_support"] + competing_support
        penalty = (winner["weighted_support"] / effective_total) if effective_total > 0 else 1.0
    else:
        competing_support = sum(effective_losers_support)
        effective_total = winner["weighted_support"] + competing_support
        penalty = (winner["weighted_support"] / effective_total) if effective_total > 0 else 1.0

    # Step 6 — final confidence, Jøsang Subjective Logic Opinion & Cryptographic Merkle Certificate
    if penalty_strategy == "paper_qg":
        confidence = qg_index
    else:
        confidence = round(winner["raw_confidence"] * penalty, 6)

    # representative surface form: highest-confidence selected claim in winner
    representative = winner_rep_claim.value

    reason = Reason.CONTRADICTION if contradictions else Reason.RESOLVED

    from core.epistemic_certificate import (
        compute_subjective_opinion,
        generate_epistemic_certificate,
    )

    subj_opinion = compute_subjective_opinion(
        winner["weighted_support"], competing_support
    )
    supporting_claims = list(winner["claims"])
    cert = generate_epistemic_certificate(
        value=representative,
        confidence=confidence,
        reason=reason,
        supporting_claims=supporting_claims,
        contradictions=contradictions,
        subjective_opinion=subj_opinion,
    )

    result = Result(
        value=representative,
        confidence=confidence,
        contradictions=contradictions,
        supporting_claims=supporting_claims,
        reason=reason,
        subjective_opinion=subj_opinion,
        epistemic_certificate=cert,
        metadata={
            "Sg": sg_index,
            "Og": og_index,
            "Qg": qg_index,
            "dependence_groups": winner.get("dependence_groups", []),
            "opposing_dependence_groups": sorted(list(opp_by_dep.keys())),
            "unresolved_comparisons": unresolved_comparisons,
            "compatible_values": compatible_values,
        },
    )

    origin_precedence_applied = any(
        g.get("origin_rank", 100) < winner.get("origin_rank", 100) for g in losers
    )

    trace = {
        "evaluated_at": eval_time.isoformat(),
        "inactive_claims": inactive,
        "num_value_groups": len(group_traces),
        "penalty": round(penalty, 6),
        "competing_support": round(competing_support, 6),
        "Sg": sg_index,
        "Og": og_index,
        "Qg": qg_index,
        "unresolved_comparisons": unresolved_comparisons,
        "compatible_values": compatible_values,
        "penalty_strategy": penalty_strategy,
        "dynamic_range_healthy": bool(confidence >= 0.15) if active else False,
        "legacy_penalty_1_over_n": round(legacy_penalty, 6),
        "origin_precedence_applied": origin_precedence_applied,
        "epistemic_audit": audit_trace,
        "subjective_opinion": subj_opinion.to_dict(),
        "epistemic_certificate": cert,
        "winner": {
            "canonical_value": winner["canonical_value"],
            "origin_rank": winner["origin_rank"],
            "weighted_support": winner["weighted_support"],
            "raw_confidence": winner["raw_confidence"],
            "dependence_groups": winner.get("dependence_groups", []),
            "evidence": winner["evidence"],
        },
        "losing_groups": [
            {
                "canonical_value": g["canonical_value"],
                "origin_rank": g["origin_rank"],
                "weighted_support": g["weighted_support"],
                "dependence_groups": g.get("dependence_groups", []),
                "evidence": g["evidence"],
            }
            for g in losers
        ],
        "final_confidence_formula": (
            "Q_g = S_g^2 / (S_g + O_g)"
            if penalty_strategy == "paper_qg"
            else (
                "noisy_or(winner_raw_confidences) × (winner_support / (winner_support + noisy_or(losing_supports)))"
                if (penalty_strategy == "dynamic_normalized" and len(group_traces) > 2)
                else "noisy_or(winner_raw_confidences) × (winner_support / total_support)"
            )
        ),
    }
    return {"result": result, "trace": trace}


def resolve_claims(
    claims: List[Claim],
    *,
    inference_profile: Optional[InferenceProfile] = None,
    now: Optional[datetime] = None,
    penalty_strategy: str = "dynamic_normalized",
    noise_threshold: float = 0.0,
    verified_premise_ids: Optional[Set[str]] = None,
    require_declared_premises: bool = False,
) -> Result:
    """Convenience wrapper returning only the Result."""
    return resolve_claims_detailed(
        claims,
        inference_profile=inference_profile,
        now=now,
        penalty_strategy=penalty_strategy,
        noise_threshold=noise_threshold,
        verified_premise_ids=verified_premise_ids,
        require_declared_premises=require_declared_premises,
    )["result"]
