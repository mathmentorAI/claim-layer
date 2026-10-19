from typing import Any, List, Optional, Protocol, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
import uuid
from datetime import datetime, timezone


class Reason:
    """
    Canonical reason strings for Result.reason.

    Classification:
      TERMINAL — safe to expose to the user / API consumer.
      INTERNAL — system-level signal, not meaningful outside resolution logic.
      ALL      — union of both; used for validity guards in tests.
    """
    RESOLVED           = "resolved"
    CONTRADICTION      = "contradiction"
    NO_CLAIMS          = "no_claims"
    NO_EVIDENCE_FOUND  = "no_evidence_found"
    NO_PREDICATE_MATCH = "no_predicate_match"
    BLOCKED_INFERENCE  = "blocked_inference"  # all evidence is of unreliable inference type
    STALE_EVIDENCE     = "stale_evidence"     # evidence exists but every claim's validity window has lapsed

    # Visible to callers — describes a complete query cycle outcome.
    TERMINAL = {RESOLVED, CONTRADICTION, NO_EVIDENCE_FOUND, NO_PREDICATE_MATCH, BLOCKED_INFERENCE, STALE_EVIDENCE}

    # Internal resolution signal — resolve() received an empty list.
    # Should not be surfaced directly in API responses.
    INTERNAL = {NO_CLAIMS}

    ALL = TERMINAL.union(INTERNAL)

    _USER_MESSAGES: dict = {
        RESOLVED:           "Result resolved successfully.",
        CONTRADICTION:      "Conflicting information detected.",
        NO_EVIDENCE_FOUND:  "No evidence found for this query.",
        NO_PREDICATE_MATCH: "We couldn't understand the question.",
        BLOCKED_INFERENCE:  "Grounding blocked: evidence is based solely on unreliable reasoning.",
        STALE_EVIDENCE:     "Evidence found, but it is no longer valid at evaluation time.",
    }

    _DEV_MESSAGES: dict = {
        RESOLVED:           "Resolution succeeded — single dominant value cluster.",
        CONTRADICTION:      "Multiple conflicting values found — confidence penalised.",
        NO_EVIDENCE_FOUND:  "Predicate recognised but no claims in store for this entity.",
        NO_PREDICATE_MATCH: "QueryLayer returned no candidates — check predicate rules.",
        NO_CLAIMS:          "resolve() called with empty claims list — check pipeline.",
        BLOCKED_INFERENCE:  "Gated — all claims carry a blocked inference type (heuristic/abductive/narrative).",
        STALE_EVIDENCE:     "All claims for this query fell outside their validity window at evaluation time.",
    }

    @staticmethod
    def is_terminal(reason: str) -> bool:
        return reason in Reason.TERMINAL

    @staticmethod
    def is_internal(reason: str) -> bool:
        return reason in Reason.INTERNAL

    @staticmethod
    def user_message(reason: str) -> str:
        """
        Return a human-readable message for a TERMINAL reason.
        Raises ValueError for internal or unknown reasons — they must never reach the user.
        """
        if reason not in Reason.TERMINAL:
            raise ValueError(
                f"Reason {reason!r} is not user-facing. "
                f"Check Reason.is_terminal() before calling user_message()."
            )
        return Reason._USER_MESSAGES[reason]

    @staticmethod
    def _build_base(reason: str, context: Optional[dict]) -> str:
        """
        Build a strongly-typed base message from context signals.

        Reads from context (all optional):
          value          — resolved or winning value
          confidence     — float from Result; preferred over formula
          n_supporting   — supporting claim count (used in formula fallback)
          n_contradictions — contradiction count (used in formula fallback)
          unit           — value unit label (e.g. 'days')
          evidence_ids   — list of claim IDs backing the result

        Confidence resolution order:
          1. context["confidence"]  — exact value from Result
          2. n_supporting / (n_supporting + n_contradictions + 1)  — formula fallback
          3. omitted
        """
        ctx = context or {}
        value = ctx.get("value")

        if reason not in (Reason.RESOLVED, Reason.CONTRADICTION) or value is None:
            return Reason._DEV_MESSAGES.get(reason, f"Unregistered reason: {reason!r}")

        # --- confidence ---
        confidence: Optional[float] = ctx.get("confidence")
        if confidence is None:
            n_sup = ctx.get("n_supporting")
            n_con = ctx.get("n_contradictions", 0)
            if n_sup is not None:
                confidence = n_sup / (n_sup + n_con + 1)
        conf_str = f", confidence={confidence:.2f}" if confidence is not None else ""

        # --- unit ---
        unit = ctx.get("unit")
        unit_str = f", unit={unit!r}" if unit else ""

        # --- evidence_ids ---
        evidence_ids = ctx.get("evidence_ids")
        evidence_str = f", evidence_ids={evidence_ids!r}" if evidence_ids else ""

        if reason == Reason.RESOLVED:
            return f"Resolved(value={value!r}{unit_str}{conf_str}{evidence_str})"
        return f"Contradiction(winning_value={value!r}{unit_str}{conf_str}{evidence_str})"

    @staticmethod
    def developer_message(
        reason: str,
        context: Optional[dict] = None,
        trace_id: Optional[str] = None,
        trace_type: Optional[str] = None,
        stage: Optional[str] = None,
        duration_ms: Optional[float] = None,
    ) -> str:
        """
        Return a technical log message for any reason.
        Safe to call for both TERMINAL and INTERNAL reasons.

        Fixed field order: trace → stage → reason → duration_ms → context.

        Args:
            reason      Always included — enables grep-based metrics.
            trace_id    Groups all lines for one request. Combined with trace_type
                        as "type:id" (e.g. "query:20260401_001").
            stage       Pipeline phase: "parsing" | "retrieval" | "resolution".
            duration_ms Wall-clock time for this stage in milliseconds.
                        Pass int or float; rendered without trailing zeros.
            context     Per-call key-value pairs. Recommended standard keys:
                          n_candidates, n_claims, n_supporting, n_contradictions.

        Example:
            Reason.developer_message(
                result.reason,
                trace_id="20260401_001", trace_type="query",
                stage="retrieval",
                duration_ms=12,
                context={"query": text, "entity": entity,
                         "n_candidates": 2, "n_claims": 5},
            )
            # → "... [trace='query:20260401_001' | stage='retrieval' | reason='no_evidence_found' | duration_ms=12 | query=... | entity=... | n_candidates=2 | n_claims=5]"
        """
        base = Reason._build_base(reason, context)

        fields: dict = {}
        if trace_id:
            fields["trace"] = f"{trace_type}:{trace_id}" if trace_type else trace_id
        if stage:
            fields["stage"] = stage
        fields["reason"] = reason
        if duration_ms is not None:
            # Render as int when whole, float otherwise: 12 not 12.0, 1.5 not 1.5000
            fields["duration_ms"] = int(duration_ms) if duration_ms == int(duration_ms) else duration_ms
        if context:
            fields.update(context)

        fields_str = " | ".join(f"{k}={v!r}" for k, v in fields.items())
        return f"{base} [{fields_str}]"


# ---------------------------------------------------------------------------
# Inference type registry
# ---------------------------------------------------------------------------

# Structural weight per inference type (0.0 = blocked, 1.0 = highest reliability).
# Used by the decision engine to weight evidence and resolve conflicts:
#   weighted_score = confidence × INFERENCE_WEIGHTS[inference_type]
# A deductive claim with confidence 0.9 outweighs a narrative claim with confidence 1.0.
INFERENCE_WEIGHTS: dict = {
    # Tier 1 — High reliability (accept)
    "arithmetic":    1.00,
    "logical":       1.00,
    "deductive":     1.00,
    "syntactic":     1.00,
    "reductio":      1.00,
    "semantic":      0.90,
    "fixed_point":   0.90,
    "spatial":       0.90,
    "bayesian":      0.85,
    "evolutionary":  0.80,
    # Tier 2 — Medium reliability (use with caution)
    "common_sense":  0.65,
    "temporal":      0.60,
    "inductive":     0.55,
    "causal":        0.55,
    "elimination":   0.55,
    "occam":         0.55,
    "abductive_inv": 0.55,
    "dialectical":   0.55,
    "multi_hop":     0.50,
    "default":       0.50,
    "authority":     0.50,
    "transductive":  0.50,
    "probabilistic": 0.40,
    "analogical":    0.35,
    "pragmatic":     0.35,
    "intentionality": 0.25,
    "attribution":   0.20,
    # Tier 3 — Low reliability (block)
    "heuristic":     0.10,
    "abductive":     0.10,
    "counterfactual": 0.05,
    "narrative":     0.00,
}

# Inference types that BLOCK decision emission when they are the sole evidence basis.
# If every claim for a query carries one of these types, the engine returns
# Reason.BLOCKED_INFERENCE instead of a resolution.
BLOCKED_INFERENCE_TYPES: frozenset = frozenset({
    "heuristic",
    "abductive",
    "counterfactual",
    "narrative",
})


@dataclass
class SourceRef:
    document_id: str
    page: int
    paragraph_id: str
    origin_tier: str = "primary_document"


@dataclass
class InferenceProfile:
    """
    Per-protocol inference weight overrides.

    Allows each team's protocol to define which inference types are reliable
    and which are blocked, overriding the global INFERENCE_WEIGHTS defaults.

    weights: partial dict of {inference_type: weight} — only overridden types
             need to be listed. Types not present fall back to INFERENCE_WEIGHTS.
    blocked_types: set of inference types that block decision emission when
                   they are the sole evidence basis. Overrides BLOCKED_INFERENCE_TYPES.
    """
    weights: dict = field(default_factory=dict)
    blocked_types: List[str] = field(default_factory=list)

    def resolve_weight(self, inference_type: str) -> float:
        """Return weight for inference_type, falling back to global defaults."""
        if inference_type in self.weights:
            return float(self.weights[inference_type])
        return INFERENCE_WEIGHTS.get(inference_type, 0.5)

    def is_blocked(self, inference_type: str) -> bool:
        """Return True if this inference type is blocked by this profile."""
        if self.blocked_types:
            return inference_type in self.blocked_types
        return inference_type in BLOCKED_INFERENCE_TYPES


@dataclass
class ExtractionConfig:
    """
    Explicit, versioned configuration for probabilistic claim extraction.
    Must be attached to the claim set to ensure the KnowledgeState signature is reproducible.
    """
    provider: str
    model: str
    mode: str          # "cloud", "local", "hybrid"
    policy: str        # "conservative", "balanced", "aggressive"
    version: Union[str, int] # e.g. "v1.0" or 1
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    profile: str = "custom"
    focus: List[str] = field(default_factory=list)
    interpreter: Optional[str] = None
    inference_profile: Optional[InferenceProfile] = None  # per-protocol weight overrides
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Claim:
    id: str
    entity: Optional[str]
    predicate: str
    value: Any
    source: SourceRef
    confidence: float
    inference_type: str = "deductive"  # see INFERENCE_WEIGHTS for valid values and weights
    # Temporal validity window (ISO-8601 strings). None = always valid.
    # A claim outside its window at evaluation time cannot support a resolution.
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    premises: List[str] = field(default_factory=list)
    origin_tier: str = "primary_document"
    quote: Optional[str] = None
    instances: List[Any] = field(default_factory=list)
    canonical_value: Optional[Any] = None
    canonical_entity: Optional[str] = None
    canonical_predicate: Optional[str] = None
    concept_fingerprint: Optional[str] = None
    unit: Optional[str] = None
    speaker_role: Optional[str] = None
    dependence_group: Optional[str] = None
    # Identifies a checker installed by the application, never executable input.
    derivation_rule: Optional[str] = None


@dataclass
class Query:
    entity: str
    predicate: str


@dataclass
class Result:
    value: Optional[Any]
    confidence: float
    contradictions: List[Claim]
    supporting_claims: List[Claim]
    reason: Optional[str] = None
    _answer: Optional[str] = field(default=None, repr=False, compare=False)
    subjective_opinion: Optional[Any] = field(default=None, repr=False, compare=False)
    epistemic_certificate: Optional[dict] = field(default=None, repr=False, compare=False)
    metadata: dict = field(default_factory=dict, repr=False, compare=False)

    def verify_certificate(self) -> bool:
        """Verify cryptographic Merkle integrity of this Result's evidence and value."""
        if not self.epistemic_certificate:
            return False
        from core.epistemic_certificate import verify_epistemic_certificate
        return verify_epistemic_certificate(
            self.epistemic_certificate,
            value=self.value,
            confidence=self.confidence,
            reason=self.reason,
            supporting_claims=self.supporting_claims,
            contradictions=self.contradictions,
            subjective_opinion=self.subjective_opinion,
        )

    @property
    def citations(self) -> List[dict]:
        """
        Structured verifiable citations for every supporting claim.
        Ensures 100% citation coverage across answers.
        """
        citations_list = []
        seen = set()
        for c in self.supporting_claims:
            doc = c.source.document_id if c.source else "doc"
            page = c.source.page if c.source else 1
            para = c.source.paragraph_id if c.source else ""
            quote = getattr(c, "quote", "") or str(c.value)
            key = (doc, page, para, quote)
            if key not in seen:
                seen.add(key)
                citations_list.append({
                    "document_id": doc,
                    "page": page,
                    "paragraph_id": para,
                    "quote": quote,
                    "claim_id": getattr(c, "id", None),
                })
        return citations_list

    def formatted_citations(self) -> str:
        """Render a readable citation footer string with document, page, and paragraph."""
        if not self.citations:
            return ""
        refs = []
        for c in self.citations:
            doc = c.get("document_id", "doc")
            page = c.get("page", 1)
            para = c.get("paragraph_id")
            quote = (c.get("quote") or "")[:120]
            para_info = f", Párrafo: {para}" if para else ""
            refs.append(f"[{doc}:p{page}] [Pág. {page}{para_info}] \"{quote}\"")
        return " | ".join(refs)

    @property
    def answer(self) -> Optional[str]:
        """
        Human-readable plain text answer with integrated citation references.
        Allows evaluators to parse either structured Result.citations or plain-text regexes.
        """
        if self._answer is not None:
            return self._answer
        if self.value is None:
            return None
        text_val = str(self.value)
        cites = self.formatted_citations()
        if cites:
            return f"{text_val}\n\n[Citas: {cites}]"
        return text_val

    @answer.setter
    def answer(self, val: Optional[str]) -> None:
        self._answer = val


class ClaimLayer:
    def ingest(self, claims: List[Claim]) -> None:
        raise NotImplementedError

    def query(self, query: Query) -> List[Claim]:
        raise NotImplementedError

    def get_by_entity(self, entity: str) -> List[Claim]:
        raise NotImplementedError

    def resolve(self, claims: List[Claim]) -> Result:
        raise NotImplementedError


class ValueNormalizationLayer(Protocol):
    """
    Normalizes raw values into equivalence classes for aggregation.

    Guarantees:
    - semantically equivalent values map to the same normalized representation
    - normalization is deterministic given the same input and normalization policy
    - normalization is auditable and versionable
    - A change in normalization policy produces a new knowledge state version.
    """
    def normalize(self, entity: str, predicate: str, value: str) -> str: ...


class KnowledgeStateStatus(str, Enum):
    """
    A knowledge state becomes STALE when new evidence affecting the same
    (entity, predicate) space has been introduced after the latest validated
    or human-verified state projection, and has not yet been reconciled.
    """
    VALIDATED = "validated"
    CONFLICT = "conflict"
    HUMAN_VERIFIED = "human_verified"
    STALE = "stale"



@dataclass
class KnowledgeStateVersion:
    """
    The knowledge state is versioned.

    A knowledge state version must be uniquely identified by a stable, reproducible
    state signature derived from:
    - the claim set
    - normalized values
    - normalization policy version
    - extraction_config version (NEW)
    - human overrides
    """
    id: str
    timestamp: str
    state_signature: str
    claim_set_id: str
    normalization_policy_version: str
    extraction_config_version: str
    derived_state: dict
    human_overrides: dict


# ---------------------------------------------------------------------------
# Decision Assurance Models (NEW VISION ALIGNMENT)
# ---------------------------------------------------------------------------

class DecisionStatus(str, Enum):
    ACTIONABLE = "actionable"
    NOT_ACTIONABLE = "not_actionable"
    REVIEW_REQUIRED = "review_required"
    VALIDATED = "validated"


@dataclass
class AuditReadyDecisionRecord:
    """
    The core product object of Deltoryx.
    An immutable, audit-ready record of an AI-assisted decision.
    """
    decision_id: str
    decision_type: str
    decision_outcome: Any
    status: DecisionStatus
    created_at: str

    # Assurance Metrics
    audit_readiness: str      # "PASS" | "FAIL" | "WARN"
    legal_defensibility: str  # "HIGH" | "MEDIUM" | "LOW"
    policy_alignment: bool
    evidence_completeness: float # 0.0 to 1.0
    decision_confidence: float   # 0.0 to 1.0
    audit_confidence: float      # 0.0 to 1.0

    # Evidence Trace
    evidence_summary: dict # {claims_total, claims_supported, claims_weak, claims_contradicted, sources_total}
    missing_inputs: List[str]
    contradictions: List[dict]
    rules_applied: List[str]

    # Cryptographic Proof
    decision_graph_hash: str
    evidence_snapshot_hash: str
    replayable: bool = True
