"""Core data structures for ClaimLayer v3 computable verification."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Disposition = Literal["RETRY", "ESCALATE"]
VerdictStatus = Literal["PASS", "RETRY", "ESCALATE"]

TIER_RANKS: dict[str, int] = {
    "authoritative": 100,
    "primary": 100,
    "governing": 100,
    "amendment": 100,
    "standard": 50,
    "secondary": 50,
    "annex": 50,
    "markup": 50,
    "draft": 20,
    "informational": 20,
    "external": 20,
    "untrusted": 10,
}


def resolve_tier_rank(tier: str, explicit_rank: int | None = None) -> int:
    """Resolve an authority rank integer from a named tier or explicit rank."""
    if explicit_rank is not None:
        return int(explicit_rank)
    key = (tier or "standard").strip().lower()
    return TIER_RANKS.get(key, 50)


def normalize_key(raw: str) -> str:
    """Canonicalize subject or predicate identifiers deterministically."""
    cleaned = re.sub(r"[^a-z0-9áéíóúñü]+", "_", (raw or "").strip().lower())
    return cleaned.strip("_")


@dataclass(frozen=True)
class Source:
    """An evidence document or state record registered in the verification ledger."""

    id: str
    text: str
    tier: str = "standard"
    authority_rank: int | None = None
    title: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    supersedes: tuple[str, ...] | list[str] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.supersedes, list):
            object.__setattr__(self, "supersedes", tuple(self.supersedes))

    @property
    def rank(self) -> int:
        return resolve_tier_rank(self.tier, self.authority_rank)

    @property
    def sha256(self) -> str:
        return hashlib.sha256((self.text or "").encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "tier": self.tier,
            "authority_rank": self.rank,
            "title": self.title,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "supersedes": list(self.supersedes),
            "sha256": self.sha256,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class FactRecord:
    """A known structured fact tied to a source in the ledger."""

    subject: str
    predicate: str
    value: str
    source_id: str
    quote: str = ""
    unit: str | None = None
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Assertion:
    """A structured claim or proposed decision parameter emitted by an AI agent."""

    subject: str
    predicate: str
    value: str
    source_id: str
    quote: str
    id: str = ""
    unit: str | None = None
    confidence: float = 1.0

    def with_default_id(self, index: int) -> Assertion:
        if self.id:
            return self
        return Assertion(
            id=f"a{index}",
            subject=self.subject,
            predicate=self.predicate,
            value=self.value,
            source_id=self.source_id,
            quote=self.quote,
            unit=self.unit,
            confidence=self.confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Policy:
    """Deterministic verification gates and invariants."""

    policy_id: str = "default"
    require_exact_quote: bool = True
    require_quantity_match: bool = True
    min_tier_rank: int = 20
    block_superseded: bool = True
    block_expired: bool = True
    min_support: float = 0.70
    conflict_escalation_threshold: float = 0.20
    required_predicates: tuple[str, ...] | list[str] = field(default_factory=tuple)
    required_source_ids: tuple[str, ...] | list[str] = field(default_factory=tuple)
    numeric_bounds: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.required_predicates, list):
            object.__setattr__(self, "required_predicates", tuple(self.required_predicates))
        if isinstance(self.required_source_ids, list):
            object.__setattr__(self, "required_source_ids", tuple(self.required_source_ids))

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "require_exact_quote": self.require_exact_quote,
            "require_quantity_match": self.require_quantity_match,
            "min_tier_rank": self.min_tier_rank,
            "block_superseded": self.block_superseded,
            "block_expired": self.block_expired,
            "min_support": self.min_support,
            "conflict_escalation_threshold": self.conflict_escalation_threshold,
            "required_predicates": list(self.required_predicates),
            "required_source_ids": list(self.required_source_ids),
            "numeric_bounds": {
                k: [v[0], v[1]] for k, v in sorted(self.numeric_bounds.items())
            },
        }


@dataclass(frozen=True)
class ConflictDiff:
    """Minimal side-by-side discrepancy payload for 15-second human triage."""

    assertion_id: str
    subject: str
    predicate: str
    proposed_value: str
    proposed_source_id: str
    proposed_quote: str
    proposed_tier: str
    competing_value: str
    competing_source_id: str
    competing_quote: str
    competing_tier: str
    proposed_support: float
    competing_support: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Issue:
    """A deterministic verification finding routed either to the agent (RETRY) or human (ESCALATE)."""

    code: str
    disposition: Disposition
    message: str
    remediation: str
    assertion_id: str | None = None
    subject: str | None = None
    predicate: str | None = None
    conflict_diff: ConflictDiff | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.conflict_diff is not None:
            payload["conflict_diff"] = self.conflict_diff.to_dict()
        return payload


@dataclass(frozen=True)
class VerificationReceipt:
    """Zero-trust cryptographic Merkle proof over verified assertions, sources, and policy."""

    scheme: str
    merkle_root: str
    policy_digest: str
    sources_digest: str
    signature: str
    leaf_hashes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheme": self.scheme,
            "merkle_root": self.merkle_root,
            "policy_digest": self.policy_digest,
            "sources_digest": self.sources_digest,
            "signature": self.signature,
            "leaf_hashes": list(self.leaf_hashes),
        }


@dataclass(frozen=True)
class ResolutionRecord:
    """A human reviewer decision resolving an escalated conflict or exception."""

    subject: str
    predicate: str
    selected_value: str
    resolver: str
    note: str = ""
    verdict_id: str | None = None
    resolved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Verdict:
    """Outcome of ClaimLayer computable verification."""

    verdict_id: str
    status: VerdictStatus
    allowed_to_proceed: bool
    requires_human: bool
    confidence: float
    issues: tuple[Issue, ...]
    conflicts: tuple[ConflictDiff, ...]
    assertion_scores: dict[str, float]
    receipt: VerificationReceipt
    assertions: tuple[Assertion, ...] = field(default_factory=tuple)
    agent_id: str = "agent"
    policy_id: str = "default"
    as_of: str | None = None

    def verify_receipt(self) -> bool:
        from claimlayer.receipt import verify_receipt

        return verify_receipt(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict_id": self.verdict_id,
            "status": self.status,
            "allowed_to_proceed": self.allowed_to_proceed,
            "requires_human": self.requires_human,
            "confidence": round(self.confidence, 6),
            "agent_id": self.agent_id,
            "policy_id": self.policy_id,
            "as_of": self.as_of,
            "issues": [issue.to_dict() for issue in self.issues],
            "conflicts": [conflict.to_dict() for conflict in self.conflicts],
            "assertion_scores": {
                k: round(v, 6) for k, v in sorted(self.assertion_scores.items())
            },
            "assertions": [a.to_dict() for a in self.assertions],
            "receipt": self.receipt.to_dict(),
        }
