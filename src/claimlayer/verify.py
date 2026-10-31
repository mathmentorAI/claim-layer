"""Main deterministic computable verification entry point: verify()."""

from __future__ import annotations

from typing import Any, Iterable

from claimlayer.ledger import Ledger
from claimlayer.models import Assertion, ConflictDiff, Issue, Policy, Verdict, VerdictStatus
from claimlayer.receipt import build_receipt
from claimlayer.verifiers.conflict import evaluate_conflicts_and_thresholds
from claimlayer.verifiers.coverage import verify_coverage
from claimlayer.verifiers.precedence import verify_precedence_and_validity
from claimlayer.verifiers.quote_quantity import verify_quote_and_quantities


def _coerce_assertions(raw: Iterable[Assertion | dict[str, Any]]) -> tuple[Assertion, ...]:
    normalized: list[Assertion] = []
    for idx, item in enumerate(raw, start=1):
        assertion = item if isinstance(item, Assertion) else Assertion(**item)
        normalized.append(assertion.with_default_id(idx))
    return tuple(normalized)


def _coerce_policy(raw: Policy | dict[str, Any] | None) -> Policy:
    if raw is None:
        return Policy()
    if isinstance(raw, Policy):
        return raw
    payload = dict(raw)
    if "numeric_bounds" in payload and isinstance(payload["numeric_bounds"], dict):
        payload["numeric_bounds"] = {
            k: (v[0], v[1]) for k, v in payload["numeric_bounds"].items()
        }
    return Policy(**payload)


def verify(
    assertions: Iterable[Assertion | dict[str, Any]],
    ledger: Ledger,
    policy: Policy | dict[str, Any] | None = None,
    *,
    as_of: str | None = None,
    agent_id: str = "agent",
) -> Verdict:
    """Deterministically verify an agent's proposed assertions against a Ledger and Policy.

    Routing semantics (designed to eliminate the 80% human supervision bottleneck):
      - ``PASS``:     All assertions grounded, active, non-conflicting, and within policy.
                      ``allowed_to_proceed=True``, ``requires_human=False``.
      - ``RETRY``:    At least one deterministic agent error (missing quote, wrong figure/unit,
                      expired/superseded source, missing required predicate). Bounced directly
                      to the agent for self-correction without waking a human.
      - ``ESCALATE``: Zero sloppy agent errors, but a genuine peer-source conflict or policy
                      cap requires surgical 15-second human triage.
    """
    pol = _coerce_policy(policy)
    typed_assertions = _coerce_assertions(assertions)

    all_issues: list[Issue] = []
    all_conflicts: list[ConflictDiff] = []
    assertion_scores: dict[str, float] = {}

    # 1. Coverage & completeness gate
    all_issues.extend(verify_coverage(typed_assertions, pol))

    # 2. Per-assertion deterministic checks
    for assertion in typed_assertions:
        source = ledger.get_source(assertion.source_id)

        # 2a. Quote & quantity/unit/date grounding
        grounding_issues = verify_quote_and_quantities(assertion, source, pol)
        if grounding_issues:
            all_issues.extend(grounding_issues)
            assertion_scores[assertion.id] = 0.0
            continue

        assert source is not None

        # 2b. Authority tier, temporal validity, and supersession
        prec_issues = verify_precedence_and_validity(
            assertion, source, ledger, pol, as_of=as_of
        )
        if prec_issues:
            all_issues.extend(prec_issues)
            assertion_scores[assertion.id] = 0.0
            continue

        # 2c. Peer conflicts, Noisy-OR support, and numeric bounds
        score, conf_issues, diffs = evaluate_conflicts_and_thresholds(
            assertion, source, typed_assertions, ledger, pol, as_of=as_of
        )
        assertion_scores[assertion.id] = score
        all_issues.extend(conf_issues)
        all_conflicts.extend(diffs)

    # 3. Determine operational verdict status (RETRY takes precedence over ESCALATE so humans
    #    are never interrupted by proposals that still contain fixable grounding mistakes).
    has_retry = any(i.disposition == "RETRY" for i in all_issues)
    has_escalate = any(i.disposition == "ESCALATE" for i in all_issues)

    if has_retry:
        status: VerdictStatus = "RETRY"
        confidence = 0.0
    elif has_escalate:
        status = "ESCALATE"
        confidence = min(assertion_scores.values()) if assertion_scores else 0.0
    else:
        status = "PASS"
        confidence = min(assertion_scores.values()) if assertion_scores else 0.0

    receipt = build_receipt(
        assertions=typed_assertions,
        sources=ledger.list_sources(),
        policy=pol,
        status=status,
        confidence=confidence,
        issue_codes=[i.code for i in all_issues],
        as_of=as_of,
    )

    verdict_id = f"vrd-{receipt.signature[:12]}"

    return Verdict(
        verdict_id=verdict_id,
        status=status,
        allowed_to_proceed=(status == "PASS"),
        requires_human=(status == "ESCALATE"),
        confidence=round(confidence, 6),
        issues=tuple(all_issues),
        conflicts=tuple(all_conflicts),
        assertion_scores=assertion_scores,
        receipt=receipt,
        assertions=typed_assertions,
        agent_id=agent_id,
        policy_id=pol.policy_id,
        as_of=as_of,
    )
