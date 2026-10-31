"""Cryptographic SHA-256 Merkle receipts for offline verification of agent verdicts."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from claimlayer.models import Assertion, Policy, Source, Verdict, VerificationReceipt

RECEIPT_SCHEME = "CLAIMLAYER-MERKLE-SHA256-v3"


def _sha256_json(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_assertion_leaf_hash(assertion: Assertion) -> str:
    return _sha256_json(
        {
            "id": assertion.id,
            "subject": assertion.subject,
            "predicate": assertion.predicate,
            "value": assertion.value,
            "unit": assertion.unit,
            "source_id": assertion.source_id,
            "quote": assertion.quote,
            "confidence": round(float(assertion.confidence), 6),
        }
    )


def compute_merkle_root(leaf_hashes: list[str] | tuple[str, ...]) -> str:
    if not leaf_hashes:
        return hashlib.sha256(b"CLAIMLAYER_EMPTY_PROPOSAL").hexdigest()
    level = sorted(leaf_hashes)
    while len(level) > 1:
        next_level: list[str] = []
        for idx in range(0, len(level), 2):
            left = level[idx]
            right = level[idx + 1] if idx + 1 < len(level) else left
            combined = hashlib.sha256(f"{left}:{right}".encode("utf-8")).hexdigest()
            next_level.append(combined)
        level = next_level
    return level[0]


def compute_sources_digest(sources: list[Source]) -> str:
    items = [
        {
            "id": s.id,
            "sha256": s.sha256,
            "rank": s.rank,
            "valid_from": s.valid_from,
            "valid_until": s.valid_until,
            "supersedes": list(s.supersedes),
        }
        for s in sorted(sources, key=lambda item: item.id)
    ]
    return _sha256_json(items)


def compute_policy_digest(policy: Policy) -> str:
    return _sha256_json(policy.to_dict())


def build_receipt(
    *,
    assertions: tuple[Assertion, ...],
    sources: list[Source],
    policy: Policy,
    status: str,
    confidence: float,
    issue_codes: list[str],
    as_of: str | None,
) -> VerificationReceipt:
    leaf_hashes = tuple(compute_assertion_leaf_hash(a) for a in assertions)
    merkle_root = compute_merkle_root(leaf_hashes)
    sources_digest = compute_sources_digest(sources)
    policy_digest = compute_policy_digest(policy)

    signature = _sha256_json(
        {
            "scheme": RECEIPT_SCHEME,
            "merkle_root": merkle_root,
            "sources_digest": sources_digest,
            "policy_digest": policy_digest,
            "status": status,
            "confidence": round(float(confidence), 6),
            "issue_codes": sorted(issue_codes),
            "as_of": as_of,
        }
    )

    return VerificationReceipt(
        scheme=RECEIPT_SCHEME,
        merkle_root=merkle_root,
        policy_digest=policy_digest,
        sources_digest=sources_digest,
        signature=signature,
        leaf_hashes=leaf_hashes,
    )


def verify_receipt(verdict: Verdict | dict[str, Any]) -> bool:
    """Verify offline that a Verdict's Merkle root and signature have not been tampered with."""
    data = verdict.to_dict() if isinstance(verdict, Verdict) else dict(verdict)
    receipt = data.get("receipt") or {}
    if receipt.get("scheme") != RECEIPT_SCHEME:
        return False

    raw_assertions = data.get("assertions") or []
    recomputed_leaves = tuple(
        compute_assertion_leaf_hash(
            a if isinstance(a, Assertion) else Assertion(**a)
        )
        for a in raw_assertions
    )
    if list(recomputed_leaves) != list(receipt.get("leaf_hashes") or []):
        return False

    recomputed_root = compute_merkle_root(recomputed_leaves)
    if recomputed_root != receipt.get("merkle_root"):
        return False

    issue_codes = [str(item.get("code", "")) for item in (data.get("issues") or [])]
    expected_sig = _sha256_json(
        {
            "scheme": RECEIPT_SCHEME,
            "merkle_root": recomputed_root,
            "sources_digest": receipt.get("sources_digest", ""),
            "policy_digest": receipt.get("policy_digest", ""),
            "status": data.get("status", ""),
            "confidence": round(float(data.get("confidence", 0.0)), 6),
            "issue_codes": sorted(issue_codes),
            "as_of": data.get("as_of"),
        }
    )
    return expected_sig == receipt.get("signature")
