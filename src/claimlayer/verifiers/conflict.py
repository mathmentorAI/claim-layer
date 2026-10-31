"""Deterministic peer-conflict resolution, Noisy-OR support, and threshold gates."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from claimlayer.models import Assertion, ConflictDiff, Issue, Policy, Source, normalize_key
from claimlayer.verifiers.precedence import is_source_active
from claimlayer.verifiers.quote_quantity import canonicalize_value, extract_quantities

if TYPE_CHECKING:
    from claimlayer.ledger import Ledger


def noisy_or(scores: Iterable[float]) -> float:
    """Aggregate independent evidence probabilities via Noisy-OR."""
    prod_complement = 1.0
    has_any = False
    for s in scores:
        clamped = max(0.0, min(1.0, float(s)))
        prod_complement *= 1.0 - clamped
        has_any = True
    return round(1.0 - prod_complement, 6) if has_any else 0.0


def evaluate_conflicts_and_thresholds(
    assertion: Assertion,
    source: Source,
    all_assertions: tuple[Assertion, ...],
    ledger: Ledger,
    policy: Policy,
    as_of: str | None = None,
) -> tuple[float, list[Issue], list[ConflictDiff]]:
    """Compute deduplicated Noisy-OR support and detect peer conflicts or policy bounds."""
    issues: list[Issue] = []
    conflicts: list[ConflictDiff] = []

    subj_key = normalize_key(assertion.subject)
    pred_key = normalize_key(assertion.predicate)
    proposed_canon = canonicalize_value(assertion.value, assertion.unit)

    # 1. Human resolution check (overrides automated conflict ambiguity)
    resolution = ledger.get_resolution(assertion.subject, assertion.predicate)
    if resolution is not None:
        resolved_canon = canonicalize_value(resolution.selected_value)
        if proposed_canon != resolved_canon:
            issues.append(
                Issue(
                    code="CONTRADICTS_HUMAN_RESOLUTION",
                    disposition="RETRY",
                    assertion_id=assertion.id,
                    subject=assertion.subject,
                    predicate=assertion.predicate,
                    message=(
                        f"Human reviewer '{resolution.resolver}' resolved {assertion.subject}.{assertion.predicate} "
                        f"to '{resolution.selected_value}', but agent proposed '{assertion.value}'."
                    ),
                    remediation=(
                        f"Adopt human-approved value '{resolution.selected_value}' for '{assertion.predicate}'."
                    ),
                )
            )
            return 0.0, issues, conflicts
        net_confidence = 1.0
    else:
        # 2. Gather peer-tier evidence (rank == source.rank) deduplicated by source_id
        # Lower-tier drafts do NOT penalize higher-tier governing sources.
        by_canon_source: dict[str, dict[str, tuple[float, str, str, str]]] = {}
        # canon_val -> source_id -> (confidence, raw_value, quote, tier)

        def _record_candidate(
            canon_val: str,
            src_id: str,
            conf: float,
            raw_val: str,
            quote_txt: str,
            tier_name: str,
        ) -> None:
            bucket = by_canon_source.setdefault(canon_val, {})
            prev = bucket.get(src_id)
            if prev is None or conf > prev[0]:
                bucket[src_id] = (conf, raw_val, quote_txt, tier_name)

        _record_candidate(
            proposed_canon,
            source.id,
            assertion.confidence,
            assertion.value,
            assertion.quote,
            source.tier,
        )

        # Check sibling assertions in the same proposal batch
        for other in all_assertions:
            if other.id == assertion.id:
                continue
            if normalize_key(other.subject) == subj_key and normalize_key(other.predicate) == pred_key:
                other_src = ledger.get_source(other.source_id)
                other_tier = other_src.tier if other_src else "standard"
                other_rank = other_src.rank if other_src else source.rank
                if other_rank >= source.rank:
                    _record_candidate(
                        canonicalize_value(other.value, other.unit),
                        other.source_id,
                        other.confidence,
                        other.value,
                        other.quote,
                        other_tier,
                    )

        # Check active peer-rank facts in ledger (excluding superseded sources)
        superseded_ids = ledger.superseded_source_ids(
            as_of=as_of,
            subject=assertion.subject,
            predicate=assertion.predicate,
        )
        for fact in ledger.get_facts(assertion.subject, assertion.predicate):
            if fact.source_id in superseded_ids:
                continue
            fact_src = ledger.get_source(fact.source_id)
            if fact_src is None:
                continue
            active_src, _ = is_source_active(fact_src, as_of)
            if not active_src:
                continue
            if fact_src.rank == source.rank:
                _record_candidate(
                    canonicalize_value(fact.value, fact.unit),
                    fact.source_id,
                    fact.confidence,
                    fact.value,
                    fact.quote or fact_src.text[:160],
                    fact_src.tier,
                )

        # Compute Noisy-OR per canonical value
        group_support: dict[str, float] = {
            cval: noisy_or(entry[0] for entry in src_map.values())
            for cval, src_map in by_canon_source.items()
        }

        own_support = group_support.get(proposed_canon, 0.0)
        competing_groups = {k: v for k, v in group_support.items() if k != proposed_canon}
        total_support = sum(group_support.values())
        share_penalty = (own_support / total_support) if total_support > 0 else 0.0
        net_confidence = round(own_support * share_penalty, 6)

        if competing_groups:
            top_comp_canon = max(competing_groups.items(), key=lambda kv: (kv[1], kv[0]))[0]
            top_comp_support = competing_groups[top_comp_canon]
            comp_sources = by_canon_source[top_comp_canon]
            best_comp_src_id, (_, comp_val, comp_quote, comp_tier) = max(
                comp_sources.items(), key=lambda kv: kv[1][0]
            )

            # Self-contradiction inside the same source or proposal batch with same source_id -> RETRY!
            if best_comp_src_id == source.id:
                issues.append(
                    Issue(
                        code="INTERNAL_SELF_CONTRADICTION",
                        disposition="RETRY",
                        assertion_id=assertion.id,
                        subject=assertion.subject,
                        predicate=assertion.predicate,
                        message=(
                            f"Proposal contains conflicting values ('{assertion.value}' vs '{comp_val}') "
                            f"for {assertion.subject}.{assertion.predicate} within source '{source.id}'."
                        ),
                        remediation="Reconcile internal contradiction before submitting proposal.",
                    )
                )
                return net_confidence, issues, conflicts

            if top_comp_support >= policy.conflict_escalation_threshold:
                diff = ConflictDiff(
                    assertion_id=assertion.id,
                    subject=assertion.subject,
                    predicate=assertion.predicate,
                    proposed_value=assertion.value,
                    proposed_source_id=source.id,
                    proposed_quote=assertion.quote,
                    proposed_tier=source.tier,
                    competing_value=comp_val,
                    competing_source_id=best_comp_src_id,
                    competing_quote=comp_quote,
                    competing_tier=comp_tier,
                    proposed_support=own_support,
                    competing_support=top_comp_support,
                )
                conflicts.append(diff)
                issues.append(
                    Issue(
                        code="UNRESOLVED_PEER_CONFLICT",
                        disposition="ESCALATE",
                        assertion_id=assertion.id,
                        subject=assertion.subject,
                        predicate=assertion.predicate,
                        message=(
                            f"Peer-authority conflict on {assertion.subject}.{assertion.predicate}: "
                            f"'{assertion.value}' ({source.id}) vs '{comp_val}' ({best_comp_src_id})."
                        ),
                        remediation=(
                            "Human reviewer must select governing value between equally ranked sources."
                        ),
                        conflict_diff=diff,
                    )
                )

    # 3. Numeric policy threshold gate (e.g. high-value transaction cap -> ESCALATE)
    bounds = policy.numeric_bounds.get(pred_key) or policy.numeric_bounds.get(assertion.predicate)
    if bounds is not None:
        min_bound, max_bound = bounds
        quantities = extract_quantities(assertion.value, explicit_unit=assertion.unit)
        for q in quantities:
            if min_bound is not None and q.magnitude < min_bound:
                issues.append(
                    Issue(
                        code="POLICY_THRESHOLD_EXCEEDED",
                        disposition="ESCALATE",
                        assertion_id=assertion.id,
                        subject=assertion.subject,
                        predicate=assertion.predicate,
                        message=(
                            f"{assertion.subject}.{assertion.predicate} = {q.magnitude:g} is below "
                            f"policy auto-approval floor ({min_bound:g})."
                        ),
                        remediation="Requires human sign-off for below-floor exception.",
                    )
                )
            if max_bound is not None and q.magnitude > max_bound:
                issues.append(
                    Issue(
                        code="POLICY_THRESHOLD_EXCEEDED",
                        disposition="ESCALATE",
                        assertion_id=assertion.id,
                        subject=assertion.subject,
                        predicate=assertion.predicate,
                        message=(
                            f"{assertion.subject}.{assertion.predicate} = {q.magnitude:g} exceeds "
                            f"policy auto-approval cap ({max_bound:g})."
                        ),
                        remediation="Requires human sign-off for above-cap commitment.",
                    )
                )

    # 4. Minimum net confidence gate (only if not already flagged by conflict)
    if not issues and net_confidence < policy.min_support:
        issues.append(
            Issue(
                code="LOW_EVIDENCE_SUPPORT",
                disposition="ESCALATE",
                assertion_id=assertion.id,
                subject=assertion.subject,
                predicate=assertion.predicate,
                message=(
                    f"Net evidence support ({net_confidence:.2f}) for {assertion.subject}.{assertion.predicate} "
                    f"is below policy min_support ({policy.min_support:.2f})."
                ),
                remediation="Provide corroborating independent source or escalate for human review.",
            )
        )

    return net_confidence, issues, conflicts
