import hashlib
import json
from claim_layer.semantic.truth import _dedup_evidence
from core.interfaces import KnowledgeStateVersion, KnowledgeStateStatus, Reason, Claim, SourceRef

def compute_state_signature(claims: list[Claim], policy_version: str, human_overrides: dict) -> str:
    """Reference implementation enforcing knowledge state determinism over claim sets."""
    payload = {
        "claims": sorted([c.id for c in claims]),
        "normalized_values": sorted([str(c.value).lower().strip() for c in claims]),
        "policy": policy_version,
        "overrides": human_overrides
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

def compute_state_status(validated_timestamp: int, new_evidence_timestamp: int, matched_semantic_space: bool) -> KnowledgeStateStatus:
    """Reference logic for state putrefaction boundary."""
    if matched_semantic_space and new_evidence_timestamp > validated_timestamp:
        return KnowledgeStateStatus.STALE
    return KnowledgeStateStatus.VALIDATED


def test_normalization_policy_changes_state_version():
    """Verify that a change in normalization policy implies a new knowledge state version."""
    claims = [Claim(id="1", entity="A", predicate="B", value="30d", source=SourceRef("doc1", 1, "p1"), confidence=0.9)]
    
    sig_v1 = compute_state_signature(claims, policy_version="v1.0", human_overrides={})
    sig_v2 = compute_state_signature(claims, policy_version="v2.0", human_overrides={})
    
    assert sig_v1 != sig_v2, "Policy changes must force a new knowledge state version"

def test_claim_set_and_policy_stable_signature():
    """Verify identical claim sets under the same policy yield identical state_signatures."""
    claims_a = [Claim(id="1", entity="A", predicate="B", value="30d", source=SourceRef("doc1", 1, "p1"), confidence=0.9)]
    claims_b = [Claim(id="1", entity="A", predicate="B", value="30d", source=SourceRef("doc1", 1, "p1"), confidence=0.9)]
    
    sig_a = compute_state_signature(claims_a, policy_version="v1.0", human_overrides={})
    sig_b = compute_state_signature(claims_b, policy_version="v1.0", human_overrides={})
    
    assert sig_a == sig_b, "Identical inputs must yield stable deterministic signatures"

def test_source_unit_deduplication_limits_support():
    """Verify duplicate evidence in the same source unit does not multiply support."""
    # Mocking two identical facts extracted from the same exact source unit (doc1)
    evidence = [
        {"claim_id": "c1", "source": "doc1", "score": 0.9, "selected": False, "reason": None},
        {"claim_id": "c2", "source": "doc1", "score": 0.9, "selected": False, "reason": None} # Duplicate extraction
    ]
    
    deduped = _dedup_evidence(evidence)
    
    # Exactly ONE should be selected
    selected = [e for e in deduped if e["selected"]]
    rejected = [e for e in deduped if not e["selected"]]
    
    assert len(selected) == 1, "Support must not inflate linearly from the same source unit"
    assert rejected[0]["reason"] == "duplicate"

def test_new_evidence_stale_state():
    """Verify new evidence in the same (entity, predicate) space sets the state to STALE if not reconciled."""
    
    # Validated yesterday
    status = compute_state_status(validated_timestamp=100, new_evidence_timestamp=150, matched_semantic_space=True)
    assert status == KnowledgeStateStatus.STALE
    
    # New evidence, but unrelated semantic space (different entity/predicate)
    status_unrelated = compute_state_status(validated_timestamp=100, new_evidence_timestamp=150, matched_semantic_space=False)
    assert status_unrelated == KnowledgeStateStatus.VALIDATED, "Irrelevant noise must not STALE the knowledge state"
