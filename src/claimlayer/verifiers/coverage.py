"""Deterministic completeness and mandatory checklist coverage checks."""

from __future__ import annotations

from claimlayer.models import Assertion, Issue, Policy, normalize_key


def verify_coverage(assertions: tuple[Assertion, ...], policy: Policy) -> list[Issue]:
    """Verify that the agent addressed all required predicates and mandatory sources."""
    issues: list[Issue] = []

    if not assertions:
        issues.append(
            Issue(
                code="EMPTY_PROPOSAL",
                disposition="RETRY",
                message="Agent submitted zero assertions for verification.",
                remediation="Include at least one structured Assertion backed by a source quote.",
            )
        )
        return issues

    present_predicates = {normalize_key(a.predicate) for a in assertions}
    for req_pred in policy.required_predicates:
        if normalize_key(req_pred) not in present_predicates:
            issues.append(
                Issue(
                    code="MISSING_REQUIRED_PREDICATE",
                    disposition="RETRY",
                    predicate=req_pred,
                    message=f"Required predicate '{req_pred}' was omitted from the agent proposal.",
                    remediation=f"Extract and cite '{req_pred}' from the governing source documents.",
                )
            )

    cited_sources = {a.source_id for a in assertions}
    for req_src in policy.required_source_ids:
        if req_src not in cited_sources:
            issues.append(
                Issue(
                    code="MISSING_REQUIRED_SOURCE",
                    disposition="RETRY",
                    message=f"Mandatory source '{req_src}' was not addressed or cited in the proposal.",
                    remediation=f"Inspect mandatory source '{req_src}' and include relevant assertions.",
                )
            )

    return issues
