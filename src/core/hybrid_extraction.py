"""
Hybrid extraction contract — "the LLM proposes; the engine disposes".

The adversarial battery (scripts/demo_adversarial_limits.py) showed that the
lexical layer fails predictably on double negation, conjugated negation
verbs, long-range negation, idioms, irony, reported speech and hedges. Those
failure modes need a language model at extraction time — but the LLM's
output must NOT be trusted as-is, or the system's guarantees (derivable
confidence, no hallucinated values) would silently disappear.

This module defines the boundary between the two worlds:

  1. `extraction_risk_signals(text)`   — deterministic router: detects text
     that is OUT of the lexical layer's scope and must go through typed
     (LLM) extraction. Conservative: any signal → route.
  2. `TypedExtraction`                 — the enriched contract an LLM fills:
     bare value + explicit polarity + inference type + validity window +
     verbatim quote. Polarity is a typed field, never buried in the value.
  3. `validate_typed_extraction(...)`  — deterministic acceptance checks on
     the LLM's proposal. Anything that fails is rejected loudly, never
     repaired silently.
  4. `to_claim(...)`                   — deterministic translation into a
     core Claim, so resolution (weights, dedup, penalty, grounding gate)
     stays 100% inside the auditable engine.

Deterministic guardrail on reliability: an LLM may KEEP or LOWER the
reliability implied by explicit lexical cues, never raise it. If the text
says «parece que…» (lexical: abductive, weight 0.1) and the LLM claims
"deductive" (weight 1.0), the accepted type is the lower-weight one. This
makes prompt-injection-style reliability inflation structurally impossible.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from core.inference_assignment import assign_inference_type
from core.interfaces import Claim, INFERENCE_WEIGHTS, SourceRef

POLARITY_AFFIRMED = "affirmed"
POLARITY_NEGATED = "negated"
_POLARITIES = frozenset({POLARITY_AFFIRMED, POLARITY_NEGATED})

# Deterministic convention used by to_claim() to fold polarity into the
# resolved value. Kept as a single constant so grouping stays consistent.
NEGATED_VALUE_PREFIX = "no_"

# Negation tokens must never appear inside a bare `value`: polarity travels
# in its own typed field. This catches LLMs that answer value="no firmado".
_NEGATION_TOKENS = frozenset({
    "no", "not", "never", "false", "denied", "cannot", "cant",
    "nunca", "jamás", "jamas", "sin", "tampoco", "falso", "negado", "denegado",
})

_TOKEN_RE = re.compile(r"[a-záéíóúüñ0-9]+")


# ---------------------------------------------------------------------------
# 1. Router — is this text outside the lexical layer's scope?
# ---------------------------------------------------------------------------

# Conjugation stems of negation/refusal verbs (open class — this list only
# needs to be good enough to ROUTE, the LLM does the actual reading).
_NEGATION_VERB_STEMS = (
    "nieg", "negar", "negand", "negad", "negó", "negaro",
    "deni", "denie", "deny", "refus", "rechaz", "desmient", "desminti",
)

_REPORTED_SPEECH_MARKERS = (
    "afirma", "asegura", "sostiene", "declara", "alega", "según dice",
    "claims", "states", "asserts", "alleges", "reportedly",
)

_HEDGE_MARKERS = (
    "en principio", "en teoría", "en teoria", "supuestamente", "a priori",
    "in principle", "in theory", "supposedly", "allegedly",
)


def extraction_risk_signals(text: str) -> List[str]:
    """Deterministic out-of-lexical-scope detector.

    Returns the list of risk signals found; a non-empty list means the text
    must be routed through typed (LLM) extraction instead of trusting the
    lexical polarity/classification path. Irony is intentionally absent:
    it has no reliable surface marker — it is only reachable via the LLM
    path when some other signal (or human review) routes the text there.
    """
    lowered = f" {text.lower()} "
    tokens = _TOKEN_RE.findall(lowered)
    signals: List[str] = []

    if sum(1 for tok in tokens if tok in _NEGATION_TOKENS) >= 2:
        signals.append("double_negation")

    if any(any(tok.startswith(stem) for stem in _NEGATION_VERB_STEMS) for tok in tokens):
        signals.append("negation_verb")

    if any(marker in lowered for marker in _REPORTED_SPEECH_MARKERS):
        signals.append("reported_speech")

    if any(marker in lowered for marker in _HEDGE_MARKERS):
        signals.append("hedge")

    # A negation particle far from any other content is what breaks the
    # token-window matcher: flag sentences with a negation particle AND a
    # long parenthetical/comma-delimited insertion (≥ 5 tokens between commas).
    if any(tok in _NEGATION_TOKENS for tok in tokens):
        for segment in text.split(","):
            inner = _TOKEN_RE.findall(segment.lower())
            if len(inner) >= 5 and not any(tok in _NEGATION_TOKENS for tok in inner):
                signals.append("long_range_negation")
                break

    # «sin» is structurally ambiguous for a token-window matcher: «sin
    # firmar» is real negation, «sin reservas» / «sin embargo» are
    # affirmative idioms. Always route it — over-routing costs one LLM
    # call; mis-reading it costs a wrong polarity.
    if "sin" in tokens:
        signals.append("ambiguous_sin_particle")

    return signals


# ---------------------------------------------------------------------------
# 2. The enriched contract
# ---------------------------------------------------------------------------

@dataclass
class TypedExtraction:
    """One claim as proposed by an extractor (LLM or otherwise).

    `value` is the BARE value ("firmado", "30"): polarity is expressed only
    through `polarity`. `quote` must be a verbatim substring of the source
    text — the anti-hallucination anchor checked by the validator.
    """
    entity: str
    predicate: str
    value: str
    polarity: str                    # POLARITY_AFFIRMED | POLARITY_NEGATED
    inference_type: str              # must be a key of INFERENCE_WEIGHTS
    confidence: float
    quote: str                       # verbatim substring of source text
    valid_from: Optional[str] = None   # ISO-8601 or None
    valid_until: Optional[str] = None  # ISO-8601 or None
    extraction_method: str = "llm"     # provenance label, e.g. "llm:gpt-x", "lexical"
    violations: List[str] = field(default_factory=list)  # filled by validation


class TypedExtractionError(ValueError):
    """Raised when an extraction proposal fails deterministic validation."""


def _parse_iso(raw: Optional[str]) -> Optional[datetime]:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def validate_typed_extraction(extraction: TypedExtraction, source_text: str) -> List[str]:
    """Deterministic acceptance checks. Returns violations (empty = accepted).

    Nothing here interprets language: every check is mechanical, so the
    validation itself preserves guarantee G1 (determinism) and G6 (values
    must originate from ingested text).
    """
    violations: List[str] = []

    if not extraction.entity.strip():
        violations.append("empty_entity")
    if not extraction.predicate.strip():
        violations.append("empty_predicate")
    if not extraction.value.strip():
        violations.append("empty_value")

    if extraction.polarity not in _POLARITIES:
        violations.append(f"unknown_polarity:{extraction.polarity}")

    if extraction.inference_type not in INFERENCE_WEIGHTS:
        violations.append(f"unknown_inference_type:{extraction.inference_type}")

    if not (0.0 <= extraction.confidence <= 1.0):
        violations.append("confidence_out_of_range")

    # Anti-hallucination anchor: the quote must exist verbatim in the source.
    if not extraction.quote.strip():
        violations.append("empty_quote")
    elif extraction.quote not in source_text:
        violations.append("quote_not_in_source")

    # Polarity travels in its own field — never inside the value.
    value_tokens = _TOKEN_RE.findall(extraction.value.lower())
    if any(tok in _NEGATION_TOKENS for tok in value_tokens):
        violations.append("negation_inside_value")

    start = _parse_iso(extraction.valid_from)
    end = _parse_iso(extraction.valid_until)
    if extraction.valid_from is not None and start is None:
        violations.append("invalid_valid_from")
    if extraction.valid_until is not None and end is None:
        violations.append("invalid_valid_until")
    if start is not None and end is not None and start > end:
        violations.append("validity_window_inverted")

    extraction.violations = violations
    return violations


def effective_inference_type(extraction: TypedExtraction) -> str:
    """Reliability guardrail: LLM may keep or lower, never raise.

    The lexical classifier runs over the quote; if it finds an explicit cue
    implying LOWER reliability than the LLM's proposal, the lexical type
    wins. `default` (the lexical fallback when no cue matched) expresses no
    opinion and never overrides.
    """
    lexical = assign_inference_type(
        predicate=extraction.predicate,
        value=extraction.value,
        claim_text=extraction.quote,
    )
    if lexical == "default":
        return extraction.inference_type

    lexical_weight = INFERENCE_WEIGHTS.get(lexical, 0.5)
    proposed_weight = INFERENCE_WEIGHTS.get(extraction.inference_type, 0.5)
    return lexical if lexical_weight < proposed_weight else extraction.inference_type


def to_claim(
    extraction: TypedExtraction,
    claim_id: str,
    source: SourceRef,
    source_text: str,
) -> Claim:
    """Deterministic translation into a core Claim (validates first).

    Polarity folds into the value with a fixed prefix so value-grouping in
    the unified engine stays consistent: («firmado», negated) → "no_firmado".
    """
    violations = validate_typed_extraction(extraction, source_text)
    if violations:
        raise TypedExtractionError(
            f"extraction rejected: {', '.join(violations)}"
        )

    value = extraction.value.strip()
    if extraction.polarity == POLARITY_NEGATED:
        value = f"{NEGATED_VALUE_PREFIX}{value}"

    return Claim(
        id=claim_id,
        entity=extraction.entity.strip(),
        predicate=extraction.predicate.strip(),
        value=value,
        source=source,
        confidence=extraction.confidence,
        inference_type=effective_inference_type(extraction),
        valid_from=extraction.valid_from,
        valid_until=extraction.valid_until,
    )


# ---------------------------------------------------------------------------
# Ingestion gate — applies the contract to pipeline ExtractedClaims
# ---------------------------------------------------------------------------

def gate_extracted_claim(claim, source_text: str):
    """Apply the typed contract to a pipeline ExtractedClaim.

    - polarity is None → legacy claim: returned unchanged, gate not involved.
    - polarity set     → validate against the source chunk; on violations the
      claim is REJECTED (returns None — dropped loudly upstream, never
      repaired silently). Accepted claims come back with polarity folded into
      the value and inference_type clamped by the lexical-cue guardrail.

    Accepts the ExtractedClaim duck-type (entity/predicate/value/quote/
    confidence/inference_type/polarity/valid_from/valid_until) to avoid a
    hard import cycle with core.claim_extractor.
    """
    if claim.polarity is None:
        return claim

    extraction = TypedExtraction(
        entity=claim.entity,
        predicate=claim.predicate,
        value=claim.value,
        polarity=claim.polarity,
        inference_type=claim.inference_type,
        confidence=claim.confidence,
        quote=claim.quote,
        valid_from=claim.valid_from,
        valid_until=claim.valid_until,
        extraction_method="llm",
    )
    if validate_typed_extraction(extraction, source_text):
        return None  # violations recorded on extraction.violations

    value = extraction.value.strip()
    if extraction.polarity == POLARITY_NEGATED:
        value = f"{NEGATED_VALUE_PREFIX}{value}"

    claim.value = value
    claim.inference_type = effective_inference_type(extraction)
    return claim
