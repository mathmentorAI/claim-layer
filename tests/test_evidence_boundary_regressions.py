"""Counterexamples from the v2.0 audit, including the public ingestion/query path."""
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from claimlayer import ClaimLayer, clear_canonical_overrides
from core.epistemic_judge import EpistemicJudge
from core.inference_engine import resolve_claims_detailed
from core.interfaces import Claim, Reason, SourceRef


def claim(cid="leaf", predicate="location", value="Madrid", **kwargs):
    return Claim(cid, "ACME", predicate, value, SourceRef(cid + ".txt", 1, "p1"), .9, **kwargs)


@pytest.mark.parametrize("rule", [None, "identity", "unknown-rule"])
def test_unrelated_premise_cannot_authorize_transfer(rule):
    leaf = claim()
    conclusion = claim("transfer", "bank_transfer_authorized", True,
                       premises=[leaf.id], derivation_rule=rule)
    audit = EpistemicJudge().audit_claim(
        conclusion, verified_premise_ids={leaf.id}, premise_lookup={leaf.id: leaf})
    assert audit.derivation_status == "unverified"
    assert audit.is_overridden


@pytest.mark.parametrize("context", [{}, {"verified_premise_ids": {"leaf"}},
                                    {"premise_lookup": {"leaf": claim()}}])
def test_derivation_requires_ids_and_premise_records(context):
    conclusion = claim("copy", premises=["leaf"], derivation_rule="identity")
    assert EpistemicJudge().audit_claim(conclusion, **context).derivation_status == "unverified"


def test_identity_rule_checks_every_ancestor_and_cycles():
    leaf = claim()
    middle = claim("middle", premises=[leaf.id], derivation_rule="identity")
    end = claim("end", premises=[middle.id], derivation_rule="identity")
    lookup = {c.id: c for c in [leaf, middle, end]}
    judge = EpistemicJudge()
    assert judge.audit_claim(end, set(lookup), premise_lookup=lookup).derivation_status == "rule_derived"
    # A verified ID must not hide an invalid implication deeper in the graph.
    middle.value = "Barcelona"
    assert judge.audit_claim(end, set(lookup), premise_lookup=lookup).derivation_status == "unverified"
    middle.value = "Madrid"
    leaf.premises = [end.id]
    audit = judge.audit_claim(end, set(lookup), premise_lookup=lookup)
    assert audit.derivation_status == "unverified"
    assert "Cyclic" in audit.override_reason


@pytest.mark.parametrize("change", [
    {"valid_until": "2030-01-01"}, {"unit": "USD"},
    {"speaker_role": "COURT_FINDING"}, {"entity": "AnotherCompany"},
])
def test_identity_rule_cannot_change_scope_or_attribution(change):
    leaf = claim()
    conclusion = replace(leaf, id="copy", premises=[leaf.id], derivation_rule="identity", **change)
    assert EpistemicJudge().audit_claim(
        conclusion, {leaf.id}, premise_lookup={leaf.id: leaf}
    ).derivation_status == "unverified"


def test_custom_rule_must_be_installed_by_application_and_fail_closed():
    leaf = claim(predicate="status", value="active")
    conclusion = claim("derived", "capacity", "eligible", premises=[leaf.id], derivation_rule="eligibility")
    context = {"verified_premise_ids": {leaf.id}, "premise_lookup": {leaf.id: leaf}}
    assert EpistemicJudge().audit_claim(conclusion, **context).is_overridden

    def eligibility(c, ps):
        return (len(ps) == 1 and ps[0].entity == c.entity
                and ps[0].predicate == "status" and ps[0].value == "active"
                and c.predicate == "capacity" and c.value == "eligible")

    judge = EpistemicJudge({"eligibility": eligibility})
    assert judge.audit_claim(conclusion, **context).derivation_status == "rule_derived"
    assert judge.audit_claim(replace(conclusion, value="unrelated"), **context).is_overridden

    def broken_checker(c, ps):
        raise ValueError("bad proof")

    assert EpistemicJudge({"eligibility": broken_checker}).audit_claim(conclusion, **context).is_overridden


def test_core_resolver_does_not_emit_unverified_derivation():
    result = resolve_claims_detailed([claim("fake", premises=["absent"])])["result"]
    assert result.value is None
    assert result.reason == Reason.BLOCKED_INFERENCE


@pytest.mark.parametrize("strategy", ["paper_qg", "dynamic_normalized", "legacy_linear"])
@pytest.mark.parametrize("predicate,field", [("location", "compatible_values"), ("general", "unresolved_comparisons")])
def test_nonconflicting_alternatives_never_penalize_support(strategy, predicate, field):
    a, b = claim("a", predicate, "Madrid"), replace(claim("b", predicate, "Barcelona"), confidence=.8)
    output = resolve_claims_detailed([a, b], penalty_strategy=strategy)
    assert output["trace"]["Og"] == 0.0
    assert output["trace"]["competing_support"] == 0.0
    assert output["result"].confidence == .9
    assert output["result"].contradictions == []
    assert output["result"].metadata[field][0]["value"] == "Barcelona"
    assert output["result"].verify_certificate()


def test_missing_scope_remains_unknown_but_real_conflict_still_penalizes():
    a = claim("a", "deadline", "30 days", valid_from="2020-01-01")
    b = replace(claim("b", "deadline", "60 days"), confidence=.8)
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    unknown = resolve_claims_detailed([a, b], now=now, penalty_strategy="paper_qg")
    assert unknown["trace"]["Og"] == 0
    assert unknown["result"].contradictions == []
    assert unknown["trace"]["unresolved_comparisons"]
    b.valid_from = a.valid_from
    conflict = resolve_claims_detailed([a, b], now=now, penalty_strategy="paper_qg")
    assert conflict["trace"]["Og"] == .8
    assert conflict["result"].contradictions == [b]
    assert conflict["result"].confidence == pytest.approx(.9 ** 2 / 1.7, abs=1e-6)


def test_public_ingestion_blocks_unchecked_proof_and_accepts_identity():
    clear_canonical_overrides()
    cl = ClaimLayer()
    cl.ingest([claim()])
    result = cl.ingest([claim("fake", "bank_transfer_authorized", "yes", premises=["leaf"], quote="The transfer is authorized.")])
    assert result["claims_rejected"] == 1
    assert all(c.id != "fake" for c in cl.core_claims)
    assert "derivation rule" in cl.rejected_claims[0]["reason"]
    response = cl.ask("What is the bank_transfer_authorized of ACME?")
    assert response["abstain"] is True
    assert response["results"] == []
    result = cl.ingest([claim("copy", premises=["leaf"], derivation_rule="identity")])
    assert result["claims_rejected"] == 0
    assert any(c.id == "copy" and c.derivation_rule == "identity" for c in cl.core_claims)


@pytest.mark.parametrize("predicate,field", [("location", "compatible_values"), ("general", "unresolved_comparisons")])
def test_public_query_keeps_alternatives_without_false_conflict(predicate, field):
    clear_canonical_overrides()
    cl = ClaimLayer()
    cl.ingest([claim("a", predicate, "Madrid"), claim("b", predicate, "Barcelona")], consolidate=False)
    response = cl.ask(f"What is the {predicate} of ACME?")
    result = response["results"][0]
    assert result["contradictions"] == []
    assert {result["value"], *[x["value"] for x in result[field]]} == {"Madrid", "Barcelona"}
    assert cl.verify_response_integrity(response)


def test_consolidation_cannot_hide_a_derivation_obligation():
    clear_canonical_overrides()
    cl = ClaimLayer()
    # Identical proposition and source coordinates used to merge before audit.
    leaf = claim()
    fake = replace(leaf, id="fake", premises=["absent"], derivation_rule="identity")
    result = cl.ingest([leaf, fake])
    assert result["claims_rejected"] == 1
    assert [c.id for c in cl.core_claims] == [leaf.id]


def test_public_multivalued_lower_tier_is_not_retracted():
    clear_canonical_overrides()
    cl = ClaimLayer()
    cl.ingest([claim("a"), claim("b", value="Barcelona", origin_tier="annex")], consolidate=False)
    response = cl.ask("What is the location of ACME?")
    result = response["results"][0]
    assert result["value"] == "Madrid"
    assert result["contradictions"] == []
    assert result["compatible_values"][0]["value"] == "Barcelona"


def test_public_missing_scope_is_unknown_not_opposing():
    clear_canonical_overrides()
    cl = ClaimLayer()
    cl.ingest([claim("a", "deadline", "30 days", valid_from="2020-01-01"),
               claim("b", "deadline", "60 days")], consolidate=False)
    result = cl.ask("What is the deadline of ACME?")["results"][0]
    assert result["contradictions"] == []
    assert result["unresolved_comparisons"]
    assert result["subjective_opinion"]["disbelief"] == 0.0
