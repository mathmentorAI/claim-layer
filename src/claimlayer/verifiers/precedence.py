"""Deterministic authority hierarchy, supersession, and temporal validity checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from claimlayer.models import Assertion, Issue, Policy, Source, normalize_key
from claimlayer.verifiers.quote_quantity import canonicalize_value

if TYPE_CHECKING:
    from claimlayer.ledger import Ledger


def is_source_active(source: Source, as_of: str | None) -> tuple[bool, str]:
    """Check whether *source* is temporally valid at *as_of* (ISO YYYY-MM-DD)."""
    if source.metadata.get("expired") is True:
        return False, f"Source '{source.id}' is explicitly marked expired."

    if not as_of:
        return True, ""

    if source.valid_from and as_of < source.valid_from:
        return (
            False,
            f"Source '{source.id}' is not yet effective as of {as_of} (valid_from={source.valid_from}).",
        )
    if source.valid_until and as_of > source.valid_until:
        return (
            False,
            f"Source '{source.id}' expired before {as_of} (valid_until={source.valid_until}).",
        )
    return True, ""


def verify_precedence_and_validity(
    assertion: Assertion,
    source: Source,
    ledger: Ledger,
    policy: Policy,
    as_of: str | None = None,
) -> list[Issue]:
    """Verify source authority rank, temporal validity, and supersession/override rules."""
    issues: list[Issue] = []

    # If a human already resolved this exact (subject, predicate), defer to conflict.py
    if ledger.get_resolution(assertion.subject, assertion.predicate) is not None:
        return issues

    # 1. Temporal validity gate
    if policy.block_expired:
        active, reason = is_source_active(source, as_of)
        if not active:
            issues.append(
                Issue(
                    code="SOURCE_EXPIRED",
                    disposition="RETRY",
                    assertion_id=assertion.id,
                    subject=assertion.subject,
                    predicate=assertion.predicate,
                    message=reason,
                    remediation=f"Replace '{source.id}' with a currently active source document.",
                )
            )
            return issues

    # 2. Minimum authority tier gate
    if source.rank < policy.min_tier_rank:
        issues.append(
            Issue(
                code="INSUFFICIENT_AUTHORITY_TIER",
                disposition="RETRY",
                assertion_id=assertion.id,
                subject=assertion.subject,
                predicate=assertion.predicate,
                message=(
                    f"Source '{source.id}' has tier '{source.tier}' (rank={source.rank}), "
                    f"below required min_tier_rank={policy.min_tier_rank}."
                ),
                remediation=(
                    f"Ground '{assertion.predicate}' in a source with authority rank >= {policy.min_tier_rank}."
                ),
            )
        )
        return issues

    if not policy.block_superseded:
        return issues

    subj_key = normalize_key(assertion.subject)
    pred_key = normalize_key(assertion.predicate)
    proposed_canon = canonicalize_value(assertion.value, assertion.unit)

    # 3. Explicit document supersession check (Source.supersedes)
    for candidate_src in ledger.list_sources():
        if candidate_src.id == source.id:
            continue
        active_cand, _ = is_source_active(candidate_src, as_of)
        if not active_cand:
            continue
        if source.id in candidate_src.supersedes:
            cand_facts = ledger.get_facts_by_source(candidate_src.id)
            if not cand_facts:
                # Full-document replacement (no partial fact table provided)
                issues.append(
                    Issue(
                        code="SOURCE_SUPERSEDED",
                        disposition="RETRY",
                        assertion_id=assertion.id,
                        subject=assertion.subject,
                        predicate=assertion.predicate,
                        message=f"Source '{source.id}' has been superseded by '{candidate_src.id}'.",
                        remediation=f"Re-verify '{assertion.predicate}' against superseding source '{candidate_src.id}'.",
                    )
                )
                return issues

            # Partial amendment: only block if the superseding source touches (subject, predicate) with a new value
            for cf in cand_facts:
                if (
                    normalize_key(cf.subject) == subj_key
                    and normalize_key(cf.predicate) == pred_key
                    and canonicalize_value(cf.value, cf.unit) != proposed_canon
                ):
                    issues.append(
                        Issue(
                            code="SOURCE_SUPERSEDED",
                            disposition="RETRY",
                            assertion_id=assertion.id,
                            subject=assertion.subject,
                            predicate=assertion.predicate,
                            message=(
                                f"Clause '{assertion.predicate}' for '{assertion.subject}' in '{source.id}' "
                                f"was amended by '{candidate_src.id}' to '{cf.value}'."
                            ),
                            remediation=(
                                f"Update '{assertion.predicate}' to '{cf.value}' citing '{candidate_src.id}'."
                            ),
                        )
                    )
                    return issues

    # 4. Higher authority tier override check across active ledger facts
    for fact in ledger.get_facts(assertion.subject, assertion.predicate):
        fact_src = ledger.get_source(fact.source_id)
        if fact_src is None or fact_src.id == source.id:
            continue
        active_fact_src, _ = is_source_active(fact_src, as_of)
        if not active_fact_src:
            continue
        if fact_src.rank > source.rank:
            fact_canon = canonicalize_value(fact.value, fact.unit)
            if fact_canon != proposed_canon:
                issues.append(
                    Issue(
                        code="HIGHER_TIER_OVERRIDE",
                        disposition="RETRY",
                        assertion_id=assertion.id,
                        subject=assertion.subject,
                        predicate=assertion.predicate,
                        message=(
                            f"Higher-authority source '{fact_src.id}' (tier='{fact_src.tier}', rank={fact_src.rank}) "
                            f"states {assertion.subject}.{assertion.predicate} = '{fact.value}', overriding "
                            f"'{source.id}' (tier='{source.tier}', rank={source.rank})."
                        ),
                        remediation=(
                            f"Replace value '{assertion.value}' with governing value '{fact.value}' from '{fact_src.id}'."
                        ),
                    )
                )
                return issues

    return issues
