# Guarantee Diff Summary — automatic failure reporting for invariant tests.
#
# When an invariant test fails, this hook prints a structured summary that maps
# the failure directly to the affected guarantee ID, its contract formula, and
# the required remediation steps, reducing the cognitive overhead of diagnosing
# a guarantee violation.
#
# At session end, prints a summary of all guarantees broken in the run.

from __future__ import annotations

import pytest

# Maps test function name → (guarantee_id, short_description, doc_anchor)
_GUARANTEE_MAP: dict[str, tuple[str, str, str]] = {
    "test_guarantee_determinism": (
        "G1",
        "Deterministic output for identical inputs",
        "docs/guarantees.md#g1",
    ),
    "test_guarantee_evidence_backed_values": (
        "G2",
        "All returned values are supported by explicit evidence",
        "docs/guarantees.md#g2",
    ),
    "test_guarantee_contradictions_always_surfaced": (
        "G3",
        "Contradictions are always surfaced, never hidden",
        "docs/guarantees.md#g3",
    ),
    "test_guarantee_normalization_collapses_equivalent_values": (
        "G3",
        "Equivalent values (same canonical_value) must not appear as contradictions",
        "docs/guarantees.md#g3",
    ),
    "test_guarantee_normalization_fallback_preserves_ambiguous_values": (
        "G3",
        "Ambiguous values must not be silently merged — contradictions must be surfaced",
        "docs/guarantees.md#g3",
    ),
    "test_guarantee_confidence_is_derivable": (
        "G4",
        "Confidence is derived from aggregated evidence (no model guessing)",
        "docs/guarantees.md#g4",
    ),
    "test_guarantee_query_aware_truth": (
        "G5",
        "Query-aware truth (similarity affects resolution)",
        "docs/guarantees.md#g5",
    ),
    "test_guarantee_no_hallucination": (
        "G6",
        "No generative step in truth resolution (no hallucination in output values)",
        "docs/guarantees.md#g6",
    ),
}

# Contract formula for each guarantee — printed inline on failure
_CONTRACT: dict[str, str] = {
    "G1": "output_a == output_b  (same inputs → same outputs, no randomness)",
    "G2": "∀ ev ∈ supporting_evidence: ev.claim_id ∈ DB",
    "G3": "contradictions == all_canonical_values − {winner}  (no silent resolution)\n"
          "  where canonical_value = normalize_value(raw_value)\n"
          "        equivalent surface forms share a canonical_value → merged, not contradicted\n"
          "        ambiguous values → canonical_value == raw_value → remain distinct",
    "G4": "final_confidence = noisy_or(selected_scores) × penalty\n"
          "  where  selected_scores = scores of non-redundant evidence only\n"
          "         score           = confidence × similarity\n"
          "         dedup key       = source (document_id) within fact group\n"
          "         penalty         = 1 / N  (N = distinct values for predicate)",
    "G5": "winner changes when similarity changes  (query drives resolution)",
    "G6": "∀ value ∈ output: value ∈ ingested_values  (no generated values)",
}

_REMEDIATION = """\
  Required actions (docs/guarantees.md — Change Policy):
    1. Identify the scope of the semantic change
    2. Update docs/guarantees.md § {gid} with the new guarantee description
    3. Update docs/architecture.md if needed
    4. Update or replace this invariant test to enforce the new guarantee
    5. Bump the version in docs/guarantees.md (v0.X → v0.Y)
"""

# Session-level list of broken guarantee IDs — populated by logreport hook
_broken: list[str] = []


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when != "call" or not report.failed:
        return

    test_name = report.nodeid.split("::")[-1]
    entry = _GUARANTEE_MAP.get(test_name)
    if entry is None:
        return

    gid, description, anchor = entry
    _broken.append(gid)

    contract_lines = "\n".join(
        f"  ║    {line}" for line in _CONTRACT[gid].splitlines()
    )
    print(
        f"\n"
        f"  ╔══ GUARANTEE VIOLATION ══════════════════════════════════════╗\n"
        f"  ║  ❌ {gid} broken — {description}\n"
        f"  ║  Current contract:\n"
        f"{contract_lines}\n"
        f"  ║  See: {anchor}\n"
        f"  ╚═════════════════════════════════════════════════════════════╝\n"
        + _REMEDIATION.format(gid=gid),
        end="",
    )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _broken:
        return
    ids = ", ".join(_broken)
    print(
        f"\n  ⚠️  {len(_broken)} guarantee(s) broken: {ids}\n"
        f"  Run: PYTHONPATH=src pytest tests/invariants/ -v -s  for full details.\n"
    )
