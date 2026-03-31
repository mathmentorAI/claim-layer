"""
Tests for query-aware truth resolution.

Verifies that resolve_truth aggregates evidence scores (confidence × similarity),
not raw confidence alone — so semantic relevance to the query affects the outcome.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from claim_layer import ClaimLayerStore
from claim_layer.models import IngestedClaim, IngestedDocument, IngestedEntity, IngestedFact
from claim_layer.semantic.truth import noisy_or, resolve_truth
from claim_layer.semantic.weighting import weight_evidence


def _store_with_claims(tmp_path: Path, claims_facts: list[tuple]) -> ClaimLayerStore:
    """
    Build a store with the given (claim_text, confidence, entity, predicate, value) tuples.
    Returns the store and the ordered list of assigned claim DB ids (1-based, sequential).
    """
    store = ClaimLayerStore(tmp_path / "test.db")
    entities = {fact[2] for fact in claims_facts}
    ingested_entities = [IngestedEntity(f"e_{n}", n) for n in entities]
    entity_map = {n: f"e_{n}" for n in entities}

    claims = [
        IngestedClaim(f"c{i}", text, confidence=conf)
        for i, (text, conf, *_) in enumerate(claims_facts, start=1)
    ]
    facts = [
        IngestedFact(f"c{i}", entity_map[entity], predicate, value)
        for i, (_, _, entity, predicate, value) in enumerate(claims_facts, start=1)
    ]

    store.ingest_document(IngestedDocument(
        project_id="p1",
        filename="doc.txt",
        entities=ingested_entities,
        claims=claims,
        facts=facts,
    ))
    return store


# ---------------------------------------------------------------------------
# noisy_or unit tests
# ---------------------------------------------------------------------------

def test_noisy_or_empty():
    assert noisy_or([]) == 0.0


def test_noisy_or_single():
    assert noisy_or([0.8]) == pytest.approx(0.8, abs=1e-6)


def test_noisy_or_saturates():
    # three identical values → higher than any one alone
    result = noisy_or([0.8, 0.8, 0.8])
    assert result > 0.8
    assert result < 1.0


def test_noisy_or_clamps():
    # values outside [0, 1] are clamped, not rejected
    assert noisy_or([1.5]) == pytest.approx(1.0, abs=1e-6)
    assert noisy_or([-0.5]) == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Core property: lower confidence but higher relevance can win
# ---------------------------------------------------------------------------

def test_high_similarity_beats_high_confidence():
    """
    Claim A: confidence=0.9, similarity=0.1  → score=0.09
    Claim B: confidence=0.5, similarity=0.95 → score=0.475

    B is more relevant to the query. resolve_truth must select B's value.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = _store_with_claims(Path(tmp), [
            ("contract term is 30 days", 0.9, "Acme", "payment_term", "30 days"),
            ("net payment period 45",    0.5, "Acme", "payment_term", "45 days"),
        ])

        # hits: claim 1 is almost invisible to the query, claim 2 is highly relevant
        hits = [(1, 0.1), (2, 0.95)]
        grouped = [
            {"entity": "Acme", "predicate": "payment_term", "value": "30 days", "supporting_claim_ids": [1]},
            {"entity": "Acme", "predicate": "payment_term", "value": "45 days", "supporting_claim_ids": [2]},
        ]

        weighted = weight_evidence(store, grouped, hits)
        results = resolve_truth(store, weighted)

        assert len(results) == 1
        result = results[0]
        assert result["value"] == "45 days", (
            f"Expected '45 days' (lower confidence but higher relevance) to win, "
            f"got '{result['value']}'"
        )
        assert result["contradictions"] != []


def test_resolved_value_changes_with_similarity():
    """
    Same claims, same confidences. Change only which claim has higher similarity.
    The winning value must flip accordingly.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = _store_with_claims(Path(tmp), [
            ("thirty day payment", 0.7, "Acme", "payment_term", "30 days"),
            ("forty five day net", 0.7, "Acme", "payment_term", "45 days"),
        ])

        grouped = [
            {"entity": "Acme", "predicate": "payment_term", "value": "30 days", "supporting_claim_ids": [1]},
            {"entity": "Acme", "predicate": "payment_term", "value": "45 days", "supporting_claim_ids": [2]},
        ]

        # Round 1: claim 1 is more relevant
        hits_favor_30 = [(1, 0.9), (2, 0.2)]
        weighted = weight_evidence(store, grouped, hits_favor_30)
        result_30 = resolve_truth(store, weighted)[0]
        assert result_30["value"] == "30 days"

        # Round 2: claim 2 is more relevant (same confidences, flipped similarities)
        hits_favor_45 = [(1, 0.2), (2, 0.9)]
        weighted = weight_evidence(store, grouped, hits_favor_45)
        result_45 = resolve_truth(store, weighted)[0]
        assert result_45["value"] == "45 days"


# ---------------------------------------------------------------------------
# Contradiction handling still works after the score-aggregation change
# ---------------------------------------------------------------------------

def test_contradiction_surfaced_with_score_aggregation():
    """
    Two distinct values for the same (entity, predicate).
    Both contradictions and alternative_evidence must be populated.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = _store_with_claims(Path(tmp), [
            ("payment net 30", 0.8, "Acme", "payment_term", "30 days"),
            ("payment net 45", 0.6, "Acme", "payment_term", "45 days"),
        ])

        hits = [(1, 0.8), (2, 0.8)]
        grouped = [
            {"entity": "Acme", "predicate": "payment_term", "value": "30 days", "supporting_claim_ids": [1]},
            {"entity": "Acme", "predicate": "payment_term", "value": "45 days", "supporting_claim_ids": [2]},
        ]

        weighted = weight_evidence(store, grouped, hits)
        results = resolve_truth(store, weighted)

        assert len(results) == 1
        r = results[0]
        assert r["contradictions"] != [], "contradictions must be non-empty"
        assert len(r["contradictions"]) == 1
        assert r["contradictions"][0]["value"] == "45 days"
        assert len(r["alternative_evidence"]) == 1
        assert r["alternative_evidence"][0]["value"] == "45 days"


def test_no_contradiction_when_single_value():
    """One value per predicate → no contradiction, full confidence, empty alternatives."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _store_with_claims(Path(tmp), [
            ("governing law New York", 0.9, "Acme", "governing_law", "New York"),
        ])

        hits = [(1, 0.85)]
        grouped = [{"entity": "Acme", "predicate": "governing_law", "value": "New York", "supporting_claim_ids": [1]}]

        weighted = weight_evidence(store, grouped, hits)
        results = resolve_truth(store, weighted)

        assert len(results) == 1
        r = results[0]
        assert r["contradictions"] == []
        assert r["alternative_evidence"] == []
        # no penalty applied: score = 0.9 × 0.85 = 0.765; noisy_or([0.765]) = 0.765
        assert r["confidence"] == pytest.approx(noisy_or([0.9 * 0.85]), abs=1e-5)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_zero_similarity_produces_zero_score():
    """Claims with zero similarity contribute nothing to aggregated confidence."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _store_with_claims(Path(tmp), [
            ("irrelevant claim high conf", 0.99, "Acme", "payment_term", "30 days"),
        ])

        hits = [(1, 0.0)]  # similarity = 0 → score = 0
        grouped = [{"entity": "Acme", "predicate": "payment_term", "value": "30 days", "supporting_claim_ids": [1]}]

        weighted = weight_evidence(store, grouped, hits)
        results = resolve_truth(store, weighted)

        assert results[0]["confidence"] == 0.0


def test_empty_weighted_facts():
    with tempfile.TemporaryDirectory() as tmp:
        store = ClaimLayerStore(Path(tmp) / "empty.db")
        assert resolve_truth(store, []) == []


def test_output_ordering_is_stable():
    """Output is sorted by (entity, predicate) ascending regardless of insertion order."""
    with tempfile.TemporaryDirectory() as tmp:
        store = _store_with_claims(Path(tmp), [
            ("z claim", 0.8, "Zebra", "zzz", "val"),
            ("a claim", 0.8, "Alpha", "aaa", "val"),
        ])

        hits = [(1, 0.8), (2, 0.8)]
        grouped = [
            {"entity": "Zebra", "predicate": "zzz", "value": "val", "supporting_claim_ids": [1]},
            {"entity": "Alpha", "predicate": "aaa", "value": "val", "supporting_claim_ids": [2]},
        ]

        weighted = weight_evidence(store, grouped, hits)
        results = resolve_truth(store, weighted)

        assert results[0]["entity"] == "Alpha"
        assert results[1]["entity"] == "Zebra"
