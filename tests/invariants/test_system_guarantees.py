# Guarantees v0.3 — see docs/guarantees.md
#
# CRITICAL: These tests encode the system guarantees defined in docs/guarantees.md
# and described in docs/architecture.md — "System Guarantees" section.
#
# Do NOT modify these tests without following the Change Policy in docs/guarantees.md:
#   1. Identify which guarantee(s) are affected (G1–G6)
#   2. Update docs/guarantees.md with the new guarantee description
#   3. Update docs/architecture.md if needed
#   4. Update or replace the failing test(s) to enforce the new guarantee
#   5. Bump the version in docs/guarantees.md
#
# Components covered — any change to these must re-validate all tests here:
#   - resolve_truth()      (src/claim_layer/semantic/truth.py)
#   - weight_evidence()    (src/claim_layer/semantic/weighting.py)
#   - noisy_or()           (src/claim_layer/semantic/truth.py)
#   - VectorIndex.search() (src/claim_layer/semantic/index.py)
#
# If a planned improvement (evidence deduplication, clustering, confidence modeling,
# semantic normalization) causes any of these tests to fail, that improvement has
# changed a system guarantee — not just an implementation detail.
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from claim_layer import ClaimLayerStore
from claim_layer.models import IngestedClaim, IngestedDocument, IngestedEntity, IngestedFact
from claim_layer.semantic.normalization import normalize_value
from claim_layer.semantic.truth import noisy_or, resolve_truth
from claim_layer.semantic.weighting import weight_evidence


def _make_store(tmp_path: Path, rows: list[tuple]) -> ClaimLayerStore:
    """Build a store from (text, confidence, entity, predicate, value) tuples."""
    store = ClaimLayerStore(tmp_path / "test.db")
    entities = {r[2] for r in rows}
    store.ingest_document(IngestedDocument(
        project_id="p1",
        filename="doc.txt",
        entities=[IngestedEntity(f"e_{n}", n) for n in entities],
        claims=[IngestedClaim(f"c{i}", text, confidence=conf)
                for i, (text, conf, *_) in enumerate(rows, 1)],
        facts=[IngestedFact(f"c{i}", f"e_{entity}", predicate, value)
               for i, (_, _, entity, predicate, value) in enumerate(rows, 1)],
    ))
    return store


# ---------------------------------------------------------------------------
# G1 — Deterministic output for identical inputs
# ---------------------------------------------------------------------------

# CRITICAL: do not modify without changing system guarantees (see docs/guarantees.md § G1)
def test_guarantee_determinism():
    """
    Identical inputs must always produce identical outputs.
    Covers: resolve_truth output order, evidence sort order, tiebreaker.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp), [
            ("claim a", 0.7, "Acme", "payment_term", "30 days"),
            ("claim b", 0.7, "Acme", "payment_term", "45 days"),
        ])
        grouped = [
            {"entity": "Acme", "predicate": "payment_term", "value": "30 days", "supporting_claim_ids": [1]},
            {"entity": "Acme", "predicate": "payment_term", "value": "45 days", "supporting_claim_ids": [2]},
        ]
        hits = [(1, 0.8), (2, 0.5)]

        results_a = resolve_truth(store, weight_evidence(store, grouped, hits))
        results_b = resolve_truth(store, weight_evidence(store, grouped, hits))
        assert results_a == results_b


# ---------------------------------------------------------------------------
# G2 — All returned values are supported by explicit evidence
# ---------------------------------------------------------------------------

# CRITICAL: do not modify without changing system guarantees (see docs/guarantees.md § G2)
def test_guarantee_evidence_backed_values():
    """
    Every resolved result must carry at least one supporting_evidence entry
    with a real claim_id that exists in the DB.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp), [
            ("net 30 payment",  0.8, "Acme", "payment_term",  "30 days"),
            ("new york law",    0.9, "Acme", "governing_law", "New York"),
        ])
        grouped = [
            {"entity": "Acme", "predicate": "payment_term",  "value": "30 days",  "supporting_claim_ids": [1]},
            {"entity": "Acme", "predicate": "governing_law", "value": "New York", "supporting_claim_ids": [2]},
        ]
        hits = [(1, 0.9), (2, 0.85)]

        results = resolve_truth(store, weight_evidence(store, grouped, hits))
        db_claim_ids = {r["id"] for r in store.get_claims(project_id="p1")}

        for r in results:
            assert r["supporting_evidence"], f"No evidence for {r['predicate']}"
            for ev in r["supporting_evidence"]:
                assert ev["claim_id"] in db_claim_ids, (
                    f"claim_id {ev['claim_id']} not found in DB"
                )


# ---------------------------------------------------------------------------
# G3 — Contradictions are always surfaced, never hidden
# ---------------------------------------------------------------------------

# CRITICAL: do not modify without changing system guarantees (see docs/guarantees.md § G3)
def test_guarantee_contradictions_always_surfaced():
    """
    When multiple distinct values exist for the same (entity, predicate),
    the losing values must appear in `contradictions` and `alternative_evidence`.
    The system must never silently collapse competing values.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp), [
            ("30 day clause", 0.9, "Acme", "payment_term", "30 days"),
            ("45 day clause", 0.8, "Acme", "payment_term", "45 days"),
            ("60 day clause", 0.5, "Acme", "payment_term", "60 days"),
        ])
        grouped = [
            {"entity": "Acme", "predicate": "payment_term", "value": "30 days", "supporting_claim_ids": [1]},
            {"entity": "Acme", "predicate": "payment_term", "value": "45 days", "supporting_claim_ids": [2]},
            {"entity": "Acme", "predicate": "payment_term", "value": "60 days", "supporting_claim_ids": [3]},
        ]
        hits = [(1, 0.9), (2, 0.9), (3, 0.9)]

        results = resolve_truth(store, weight_evidence(store, grouped, hits))
        assert len(results) == 1
        r = results[0]

        competing_values = {c["value"] for c in r["contradictions"]}
        alternative_values = {a["value"] for a in r["alternative_evidence"]}
        all_values = {"30 days", "45 days", "60 days"}

        # all values except the winner must appear in both contradiction lists
        assert competing_values == all_values - {r["value"]}
        assert alternative_values == all_values - {r["value"]}


# ---------------------------------------------------------------------------
# G4 — Confidence is derived from aggregated NON-REDUNDANT evidence (no model guessing)
# ---------------------------------------------------------------------------

# CRITICAL: do not modify without changing system guarantees (see docs/guarantees.md § G4)
def test_guarantee_confidence_is_derivable():
    """
    The output confidence must equal noisy_or(selected_scores) × penalty,
    where selected_scores excludes deduplicated (same-source) evidence.
    No black-box transformation. Duplicate evidence must NOT increase confidence.

    Scenario A — no duplicates: confidence is derivable from all evidence.
    Scenario B — duplicates present: confidence must equal single-source value,
                 not the inflated multi-count version.
    """
    # Scenario A: two claims from different documents (no deduplication)
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp), [
            ("payment 30", 0.8, "Acme", "payment_term", "30 days"),
            ("payment 45", 0.6, "Acme", "payment_term", "45 days"),
        ])
        hits = [(1, 0.9), (2, 0.7)]
        grouped = [
            {"entity": "Acme", "predicate": "payment_term", "value": "30 days", "supporting_claim_ids": [1]},
            {"entity": "Acme", "predicate": "payment_term", "value": "45 days", "supporting_claim_ids": [2]},
        ]
        weighted = weight_evidence(store, grouped, hits)
        results = resolve_truth(store, weighted)

        score_30 = 0.8 * 0.9
        expected_30 = round(noisy_or([score_30]) * (1 / 2), 6)
        r = next(r for r in results if r["value"] == "30 days")
        assert r["confidence"] == pytest.approx(expected_30, abs=1e-6)

    # Scenario B: two claims from the SAME document supporting the same value
    # Both are ingested into the same document → same document_id → same source
    # Only the higher-score one must be selected; confidence must NOT increase
    with tempfile.TemporaryDirectory() as tmp:
        store = ClaimLayerStore(Path(tmp) / "test.db")
        # One document, two claims both asserting "30 days"
        store.ingest_document(IngestedDocument(
            project_id="p1",
            filename="contract.txt",
            entities=[IngestedEntity("e_Acme", "Acme")],
            claims=[
                IngestedClaim("c1", "payment is 30 days",        confidence=0.8),
                IngestedClaim("c2", "net 30 payment terms",      confidence=0.7),
                IngestedClaim("c3", "governing law is New York", confidence=0.9),
            ],
            facts=[
                IngestedFact("c1", "e_Acme", "payment_term",  "30 days"),
                IngestedFact("c2", "e_Acme", "payment_term",  "30 days"),   # duplicate value, same doc
                IngestedFact("c3", "e_Acme", "governing_law", "New York"),
            ],
        ))

        # Claim IDs: c1=1, c2=2, c3=3 (sequential ingestion)
        hits = [(1, 0.9), (2, 0.8), (3, 0.85)]
        grouped = [
            {"entity": "Acme", "predicate": "payment_term",  "value": "30 days",  "supporting_claim_ids": [1, 2]},
            {"entity": "Acme", "predicate": "governing_law", "value": "New York", "supporting_claim_ids": [3]},
        ]
        weighted = weight_evidence(store, grouped, hits)
        results = resolve_truth(store, weighted)

        pay = next(r for r in results if r["predicate"] == "payment_term")

        # Both claims are from the same document → same source → deduplication applies
        # Only the higher-score claim (c1: 0.8×0.9=0.72) must be selected
        # Confidence must equal noisy_or([0.72]) — NOT noisy_or([0.72, 0.56])
        best_score = 0.8 * 0.9   # c1 wins (score=0.72 > c2 score=0.56)
        expected_no_dup = round(noisy_or([best_score]), 6)
        inflated        = round(noisy_or([0.8 * 0.9, 0.7 * 0.8]), 6)

        assert pay["confidence"] == pytest.approx(expected_no_dup, abs=1e-6), (
            "Duplicate evidence from the same source must not inflate confidence"
        )
        assert pay["confidence"] < inflated, (
            "Confidence with deduplication must be lower than without"
        )

        # Full evidence trace must still be present — both items returned
        ev_ids = {ev["claim_id"] for ev in pay["supporting_evidence"]}
        assert 1 in ev_ids and 2 in ev_ids, "Both evidence items must appear in the trace"

        # Exactly one item selected, one discarded
        selected   = [ev for ev in pay["supporting_evidence"] if ev["selected"]]
        discarded  = [ev for ev in pay["supporting_evidence"] if not ev["selected"]]
        assert len(selected)  == 1
        assert len(discarded) == 1
        assert discarded[0]["reason"] == "duplicate"

    # Scenario C: same value, two DIFFERENT documents → dedup must NOT apply
    # Independent attestation from separate sources must accumulate confidence.
    with tempfile.TemporaryDirectory() as tmp:
        store = ClaimLayerStore(Path(tmp) / "test.db")
        store.ingest_document(IngestedDocument(
            project_id="p1", filename="doc_a.txt",
            entities=[IngestedEntity("e_Acme", "Acme")],
            claims=[IngestedClaim("c1", "payment is 30 days", confidence=0.6)],
            facts=[IngestedFact("c1", "e_Acme", "payment_term", "30 days")],
        ))
        store.ingest_document(IngestedDocument(
            project_id="p1", filename="doc_b.txt",
            entities=[IngestedEntity("e_Acme", "Acme")],
            claims=[IngestedClaim("c2", "net 30 payment", confidence=0.7)],
            facts=[IngestedFact("c2", "e_Acme", "payment_term", "30 days")],
        ))

        # claim 1 → doc 1, claim 2 → doc 2 — different sources
        hits = [(1, 0.9), (2, 0.9)]
        grouped = [{"entity": "Acme", "predicate": "payment_term", "value": "30 days",
                    "supporting_claim_ids": [1, 2]}]
        weighted = weight_evidence(store, grouped, hits)
        results = resolve_truth(store, weighted)

        pay = results[0]
        both_selected = [ev for ev in pay["supporting_evidence"] if ev["selected"]]
        assert len(both_selected) == 2, (
            "Evidence from different documents must both be selected — independent attestation"
        )

        # noisy_or over two independent scores must exceed either one alone
        score_1 = 0.6 * 0.9
        score_2 = 0.7 * 0.9
        expected_combined = round(noisy_or([score_1, score_2]), 6)
        single_best       = round(noisy_or([score_2]), 6)
        assert pay["confidence"] == pytest.approx(expected_combined, abs=1e-6)
        assert pay["confidence"] > single_best, (
            "Two independent attestations must produce higher confidence than one"
        )


# Scenario D: "30 days" and "thirty days" normalize to the same canonical value
# → they must NOT appear as contradictions; confidence must accumulate.
# CRITICAL: do not modify without changing system guarantees (see docs/guarantees.md § G3 / G4)
def test_guarantee_normalization_collapses_equivalent_values():
    """
    Values that normalize to the same canonical_value must be resolved as a
    single group — no contradiction surfaced, confidence accumulated from both.

    "30 days" and "thirty days" both normalize to canonical_value=30.
    They must produce one result with no contradictions.
    """
    assert normalize_value("30 days") == normalize_value("thirty days"), (
        "Precondition: both values must normalize to the same canonical form"
    )
    with tempfile.TemporaryDirectory() as tmp:
        store = ClaimLayerStore(Path(tmp) / "test.db")
        store.ingest_document(IngestedDocument(
            project_id="p1", filename="doc_a.txt",
            entities=[IngestedEntity("e_Acme", "Acme")],
            claims=[IngestedClaim("c1", "payment is 30 days", confidence=0.7)],
            facts=[IngestedFact("c1", "e_Acme", "payment_term", "30 days")],
        ))
        store.ingest_document(IngestedDocument(
            project_id="p1", filename="doc_b.txt",
            entities=[IngestedEntity("e_Acme", "Acme")],
            claims=[IngestedClaim("c2", "payment is thirty days", confidence=0.6)],
            facts=[IngestedFact("c2", "e_Acme", "payment_term", "thirty days")],
        ))

        hits = [(1, 0.9), (2, 0.9)]
        grouped = [
            {"entity": "Acme", "predicate": "payment_term", "value": "30 days",
             "supporting_claim_ids": [1]},
            {"entity": "Acme", "predicate": "payment_term", "value": "thirty days",
             "supporting_claim_ids": [2]},
        ]
        weighted = weight_evidence(store, grouped, hits)
        results = resolve_truth(store, weighted)

        assert len(results) == 1, "Equivalent values must collapse to a single result"
        r = results[0]
        assert r["contradictions"] == [], (
            "No contradictions when values share a canonical form"
        )
        assert r["canonical_value"] == 30

        # Both claims are from different documents → both selected → confidence accumulates
        selected = [ev for ev in r["supporting_evidence"] if ev["selected"]]
        assert len(selected) == 2, (
            "Both independent attestations must be selected after canonical merge"
        )
        score_1 = 0.7 * 0.9
        score_2 = 0.6 * 0.9
        expected = round(noisy_or([score_1, score_2]), 6)
        assert r["confidence"] == pytest.approx(expected, abs=1e-6)


# Scenario E: "around 30 days" does NOT normalize → stays as a separate value,
# producing a contradiction against "30 days".
# CRITICAL: do not modify without changing system guarantees (see docs/guarantees.md § G3)
def test_guarantee_normalization_fallback_preserves_ambiguous_values():
    """
    Values that cannot be deterministically normalized must remain as-is.
    "around 30 days" is ambiguous → normalize_value returns it unchanged →
    it must NOT be merged with "30 days" → contradiction must be surfaced.
    """
    ambiguous = "around 30 days"
    assert normalize_value(ambiguous) == ambiguous, (
        "Precondition: ambiguous value must not be normalized"
    )
    with tempfile.TemporaryDirectory() as tmp:
        store = ClaimLayerStore(Path(tmp) / "test.db")
        store.ingest_document(IngestedDocument(
            project_id="p1", filename="doc_a.txt",
            entities=[IngestedEntity("e_Acme", "Acme")],
            claims=[IngestedClaim("c1", "payment is 30 days", confidence=0.8)],
            facts=[IngestedFact("c1", "e_Acme", "payment_term", "30 days")],
        ))
        store.ingest_document(IngestedDocument(
            project_id="p1", filename="doc_b.txt",
            entities=[IngestedEntity("e_Acme", "Acme")],
            claims=[IngestedClaim("c2", "around 30 days payment", confidence=0.5)],
            facts=[IngestedFact("c2", "e_Acme", "payment_term", ambiguous)],
        ))

        hits = [(1, 0.9), (2, 0.9)]
        grouped = [
            {"entity": "Acme", "predicate": "payment_term", "value": "30 days",
             "supporting_claim_ids": [1]},
            {"entity": "Acme", "predicate": "payment_term", "value": ambiguous,
             "supporting_claim_ids": [2]},
        ]
        weighted = weight_evidence(store, grouped, hits)
        results = resolve_truth(store, weighted)

        assert len(results) == 1
        r = results[0]
        assert len(r["contradictions"]) == 1, (
            "Ambiguous value must remain separate and appear as a contradiction"
        )
        contradiction_values = {c["value"] for c in r["contradictions"]}
        assert ambiguous in contradiction_values


# ---------------------------------------------------------------------------
# G5 — Query-aware truth (similarity affects resolution)
# ---------------------------------------------------------------------------

# CRITICAL: do not modify without changing system guarantees (see docs/guarantees.md § G5)
def test_guarantee_query_aware_truth():
    """
    A lower-confidence claim with higher query relevance must beat
    a higher-confidence claim that is irrelevant to the query.
    Changing similarity must change the resolved value.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store(Path(tmp), [
            ("high conf irrelevant", 0.95, "Acme", "payment_term", "30 days"),
            ("low conf relevant",    0.40, "Acme", "payment_term", "45 days"),
        ])
        grouped = [
            {"entity": "Acme", "predicate": "payment_term", "value": "30 days", "supporting_claim_ids": [1]},
            {"entity": "Acme", "predicate": "payment_term", "value": "45 days", "supporting_claim_ids": [2]},
        ]

        # claim 1 irrelevant (score = 0.95 × 0.05 = 0.0475)
        # claim 2 highly relevant (score = 0.40 × 0.99 = 0.396)
        hits = [(1, 0.05), (2, 0.99)]
        weighted = weight_evidence(store, grouped, hits)
        result = resolve_truth(store, weighted)[0]
        assert result["value"] == "45 days", (
            "Query-relevant claim must win over high-confidence irrelevant claim"
        )


# ---------------------------------------------------------------------------
# G6 — No generative step in truth resolution (no hallucination in output values)
# ---------------------------------------------------------------------------

# CRITICAL: do not modify without changing system guarantees (see docs/guarantees.md § G6)
def test_guarantee_no_hallucination():
    """
    All values in the output (winning and alternatives) must be values
    that were explicitly ingested. The system must not produce any value
    absent from the source facts.
    """
    with tempfile.TemporaryDirectory() as tmp:
        ingested_values = {"30 days", "45 days"}
        store = _make_store(Path(tmp), [
            ("payment 30", 0.8, "Acme", "payment_term", "30 days"),
            ("payment 45", 0.6, "Acme", "payment_term", "45 days"),
        ])
        grouped = [
            {"entity": "Acme", "predicate": "payment_term", "value": v, "supporting_claim_ids": [i]}
            for i, v in enumerate(ingested_values, 1)
        ]
        hits = [(1, 0.8), (2, 0.8)]

        results = resolve_truth(store, weight_evidence(store, grouped, hits))
        for r in results:
            assert r["value"] in ingested_values
            for c in r["contradictions"]:
                assert c["value"] in ingested_values
