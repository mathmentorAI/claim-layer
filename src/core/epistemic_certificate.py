"""
Formal Epistemic Uncertainty (Jøsang's Subjective Logic) and
Cryptographic Merkle Audit Certificates for Deltoryx v2.0.

1. Jøsang Subjective Logic Opinion Tuple ω = (b, d, u, a):
   Decomposes scalar confidence into three orthogonal dimensions on the simplex b + d + u = 1:
   - b (Belief): mass of verified evidence supporting the winning resolution.
   - d (Disbelief / Conflict): mass of verified evidence supporting competing alternatives.
   - u (Epistemic Uncertainty / Vacuity): residual ignorance due to lack of strong evidence.

   This resolves the fundamental scalar ambiguity of traditional AI systems where
   confidence = 0.50 conflates "total lack of strong evidence" (b=0.50, d=0.00, u=0.50)
   with "hard frontal contradiction between two strong primary contracts" (b=0.495, d=0.495, u=0.01).

2. Verifiable Epistemic Certificates (Merkle Tree Proofs):
   Binds every resolution to a cryptographic Merkle root of its supporting and
   contradicting claims plus a deterministic signature over the resolution state,
   allowing zero-trust third-party verification that no quote, weight, or value was tampered with.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from core.interfaces import Claim


@dataclass(frozen=True)
class SubjectiveOpinion:
    belief: float
    disbelief: float
    uncertainty: float
    base_rate: float = 0.5
    projected_probability: float = 0.5
    epistemic_regime: str = "VACUOUS_IGNORANCE"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_subjective_opinion(
    winner_support: float,
    competing_support: float,
    base_rate: float = 0.5,
) -> SubjectiveOpinion:
    """
    Map weighted support of the winning group (W) and competing groups (L)
    onto Jøsang's Subjective Logic simplex b + d + u = 1.

    Using the Noisy-OR evidence union M = 1 - (1 - W)(1 - L):
      u = (1 - W)(1 - L)          [Vacuous epistemic ignorance]
      b = M * (W / (W + L))       [Confirmed belief mass]
      d = M * (L / (W + L))       [Conflict / disbelief mass]
    """
    w = max(0.0, min(1.0, float(winner_support)))
    l = max(0.0, min(1.0, float(competing_support)))
    a = max(0.0, min(1.0, float(base_rate)))

    if w <= 0.0 and l <= 0.0:
        return SubjectiveOpinion(
            belief=0.0,
            disbelief=0.0,
            uncertainty=1.0,
            base_rate=round(a, 6),
            projected_probability=round(a, 6),
            epistemic_regime="VACUOUS_IGNORANCE",
        )

    total_mass = 1.0 - (1.0 - w) * (1.0 - l)
    u = round(max(0.0, min(1.0, 1.0 - total_mass)), 6)
    b = round(total_mass * (w / (w + l)), 6)
    d = round(max(0.0, 1.0 - u - b), 6)
    proj = round(b + a * u, 6)

    if u >= 0.75:
        regime = "HIGH_UNCERTAINTY"
    elif d >= 0.20 and (b / max(b + d, 1e-9)) < 0.75:
        regime = "HIGH_CONFLICT"
    elif d > 0.0:
        regime = "CONTESTED_DOMINANT"
    elif b >= 0.70:
        regime = "HIGH_CERTAINTY"
    else:
        regime = "MODERATE_EVIDENCE"

    return SubjectiveOpinion(
        belief=b,
        disbelief=d,
        uncertainty=u,
        base_rate=round(a, 6),
        projected_probability=proj,
        epistemic_regime=regime,
    )


def compute_claim_leaf_hash(claim: Claim) -> str:
    """Compute a canonical SHA-256 leaf hash for a Claim."""
    payload = {
        "id": str(getattr(claim, "id", "") or ""),
        "entity": str(getattr(claim, "entity", "") or ""),
        "predicate": str(getattr(claim, "predicate", "") or ""),
        "value": str(getattr(claim, "value", "") if getattr(claim, "value", None) is not None else ""),
        "quote": str(getattr(claim, "quote", "") or ""),
        "origin_tier": str(getattr(claim, "origin_tier", "primary_document") or "primary_document"),
        "inference_type": str(getattr(claim, "inference_type", "deductive") or "deductive"),
        "confidence": round(float(getattr(claim, "confidence", 0.0) or 0.0), 6),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_merkle_root(leaf_hashes: List[str]) -> str:
    """Compute a canonical binary Merkle Tree root from a list of leaf hashes."""
    if not leaf_hashes:
        return hashlib.sha256(b"EMPTY_EPISTEMIC_SET").hexdigest()

    level = sorted(leaf_hashes)
    while len(level) > 1:
        next_level: List[str] = []
        for idx in range(0, len(level), 2):
            left = level[idx]
            right = level[idx + 1] if idx + 1 < len(level) else left
            combined = f"{left}:{right}".encode("utf-8")
            next_level.append(hashlib.sha256(combined).hexdigest())
        level = next_level
    return level[0]


def generate_epistemic_certificate(
    *,
    value: Any,
    confidence: float,
    reason: Optional[str],
    supporting_claims: List[Claim],
    contradictions: List[Claim],
    subjective_opinion: Optional[SubjectiveOpinion] = None,
) -> Dict[str, Any]:
    """Generate a deterministic, tamper-evident Merkle certificate for a resolution."""
    support_hashes = [compute_claim_leaf_hash(c) for c in (supporting_claims or [])]
    contra_hashes = [compute_claim_leaf_hash(c) for c in (contradictions or [])]
    all_leaves = support_hashes + contra_hashes
    merkle_root = compute_merkle_root(all_leaves)

    opinion_dict = subjective_opinion.to_dict() if subjective_opinion else {}
    envelope = {
        "merkle_root": merkle_root,
        "support_merkle_root": compute_merkle_root(support_hashes),
        "contradiction_merkle_root": compute_merkle_root(contra_hashes),
        "resolved_value": str(value) if value is not None else None,
        "confidence": round(float(confidence or 0.0), 6),
        "reason": str(reason or ""),
        "belief": opinion_dict.get("belief", 0.0),
        "disbelief": opinion_dict.get("disbelief", 0.0),
        "uncertainty": opinion_dict.get("uncertainty", 1.0),
    }
    signature = hashlib.sha256(
        json.dumps(envelope, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

    return {
        "scheme": "DELTORYX-MERKLE-SHA256-v2",
        "merkle_root": merkle_root,
        "support_merkle_root": envelope["support_merkle_root"],
        "contradiction_merkle_root": envelope["contradiction_merkle_root"],
        "leaf_count": len(all_leaves),
        "leaf_hashes": sorted(all_leaves),
        "resolved_value": envelope["resolved_value"],
        "confidence": envelope["confidence"],
        "reason": envelope["reason"],
        "certificate_signature": signature,
    }


def verify_epistemic_certificate(
    certificate: Dict[str, Any],
    *,
    value: Any,
    confidence: float,
    reason: Optional[str],
    supporting_claims: List[Claim],
    contradictions: List[Claim],
    subjective_opinion: Optional[SubjectiveOpinion] = None,
) -> bool:
    """
    Verify that a resolution and its underlying claims match the cryptographic certificate.
    Returns False if any claim quote, value, confidence, or contradiction was tampered with.
    """
    if not certificate or not isinstance(certificate, dict):
        return False
    expected = generate_epistemic_certificate(
        value=value,
        confidence=confidence,
        reason=reason,
        supporting_claims=supporting_claims,
        contradictions=contradictions,
        subjective_opinion=subjective_opinion,
    )
    return (
        certificate.get("merkle_root") == expected["merkle_root"]
        and certificate.get("certificate_signature") == expected["certificate_signature"]
    )
