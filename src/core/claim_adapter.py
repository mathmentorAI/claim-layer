from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import List, Optional

_SRC = Path(__file__).parent.parent / "claim-layer" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from claim_layer.models import (
    IngestedClaim,
    IngestedDocument,
    IngestedEntity,
    IngestedFact,
    IngestedSource,
)

from core.claim_extractor import ExtractedClaim
from core.interfaces import ExtractionConfig
from core.claim_consolidator import ClaimConsolidator

_DEBUG_INGESTION = os.environ.get("DELTORYX_DEBUG_INGESTION", "false").lower() == "true"

_GENERIC_PREDICATES = {"general", "statement", "unknown", "other", "misc", "fact", "claim"}


def compute_structural_fidelity(
    entity_or_claim: object,
    predicate: str = "",
    value: str = "",
    quote: str = "",
) -> float:
    """
    Implements Section 8.3.3 of the Evidence Intelligence paper:
    Measures structural fidelity kappa_structuring in [0.0, 1.0] of a decomposed
    (entity, predicate, value) tuple.
    Penalizes generic fallback predicates ('general', 'statement'), malformed entities
    with embedded footnote numbers, or empty/trivial values.
    """
    if hasattr(entity_or_claim, "predicate") and hasattr(entity_or_claim, "value"):
        ent = (getattr(entity_or_claim, "entity", "") or "").strip()
        pred = (getattr(entity_or_claim, "predicate", "") or "").strip().lower()
        val = str(getattr(entity_or_claim, "value", "") or "").strip()
        quote = (getattr(entity_or_claim, "quote", "") or "").strip()
    else:
        ent = (str(entity_or_claim) if entity_or_claim is not None else "").strip()
        pred = (predicate or "").strip().lower()
        val = (value or "").strip()

    if not ent or not pred or not val:
        return 0.0

    score = 1.0
    # Penalize generic predicates (Paper Section 8.3.1 & 8.6: generic predicate 'general'/'statement')
    if pred in _GENERIC_PREDICATES or ent.lower() in {"document", "none", "unknown"}:
        score = 0.65

    # Penalize entity misidentification artifacts (e.g., embedded footnote numbers "marqués 24 de Mantua")
    if re.search(r"[a-záéíóúñ]\s+\d+\s+[a-záéíóúñ]", ent, re.IGNORECASE):
        score *= 0.65

    # Penalize overly long clause-like entity names (> 60 chars)
    if len(ent) > 60:
        score *= 0.75

    # Bonus/confirmation if quote grounds the value or entity
    if quote and val.lower() not in quote.lower() and len(val) > 4:
        score *= 0.90

    return round(max(0.0, min(1.0, score)), 4)


def compute_tripartite_quality(
    claim_obj: object,
    *,
    scope_applicable: bool = True,
) -> dict:
    """
    Implements Section 5.1 of the revised Evidence Intelligence paper (Oct 2026):
        kappa_i = (kappa_i^span, kappa_i^struct, kappa_i^app)
        a_i = min{kappa_i^span, kappa_i^struct, kappa_i^app} in [0, 1]

    - kappa_span: support by the quoted span (whether a non-empty quote grounds the assertion).
    - kappa_struct: structural fidelity of entities, relations, values, polarity, and units.
    - kappa_app: source applicability and temporal/domain scope alignment.
    """
    raw_conf = round(max(0.0, min(1.0, float(getattr(claim_obj, "confidence", 1.0)))), 4)
    quote = str(getattr(claim_obj, "quote", "") or "").strip()
    val = str(getattr(claim_obj, "value", "") or "").strip()

    # 1. Span support assessment
    if quote:
        k_span = raw_conf if (not val or len(val) <= 4 or val.lower() in quote.lower()) else round(raw_conf * 0.90, 4)
    else:
        # Unquoted record has reduced span verification index unless raw_conf explicitly supplied
        k_span = raw_conf

    # 2. Structural fidelity
    k_struct = compute_structural_fidelity(claim_obj)

    # 3. Source applicability
    if not scope_applicable:
        k_app = 0.0
    else:
        origin_tier = str(getattr(claim_obj, "origin_tier", "primary_document") or "primary_document").lower()
        if "external" in origin_tier or "injected" in origin_tier:
            k_app = 0.50
        elif "annex" in origin_tier or "secondary" in origin_tier:
            k_app = 0.85
        else:
            k_app = 1.0

    composite_a_i = round(min(k_span, k_struct, k_app), 4)
    return {
        "kappa_span": k_span,
        "kappa_struct": k_struct,
        "kappa_app": k_app,
        "composite_support_index": composite_a_i,
    }


def decompose_confidence(
    extraction_confidence_or_claim: object,
    entity: str = "",
    predicate: str = "",
    value: str = "",
    quote: str = "",
):
    """
    Returns both the dual confidence decomposition:
        kappa = (kappa_extraction, kappa_structuring)
    and the revised Section 5.1 tripartite quality vector:
        kappa_i = (kappa_span, kappa_struct, kappa_app), a_i = min(kappa_span, kappa_struct, kappa_app).
    When passed a Claim/ExtractedClaim object, returns a dictionary.
    When passed positional arguments, returns (k_ext, k_struct).
    """
    if hasattr(extraction_confidence_or_claim, "predicate") and hasattr(
        extraction_confidence_or_claim, "value"
    ):
        claim_obj = extraction_confidence_or_claim
        k_ext = round(max(0.0, min(1.0, float(getattr(claim_obj, "confidence", 1.0)))), 4)
        k_struct = compute_structural_fidelity(claim_obj)
        tri = compute_tripartite_quality(claim_obj)
        return {
            "kappa_extraction": k_ext,
            "kappa_structuring": k_struct,
            "kappa_span": tri["kappa_span"],
            "kappa_struct": tri["kappa_struct"],
            "kappa_app": tri["kappa_app"],
            "composite_support_index": tri["composite_support_index"],
            "extraction": k_ext,
            "structuring": k_struct,
            "effective_confidence": round(k_ext * k_struct, 4),
        }

    k_ext = round(max(0.0, min(1.0, float(extraction_confidence_or_claim))), 4)
    k_struct = compute_structural_fidelity(entity, predicate, value, quote)
    return (k_ext, k_struct)


class ClaimAdapter:
    """
    Translates Deltoryx ExtractedClaim objects into an IngestedDocument
    ready for the claim-layer store.

    The page_number is propagated into every IngestedClaim and IngestedSource
    so that SourceRef traceability is maintained end-to-end.
    """

    def __init__(self, consolidator: Optional[ClaimConsolidator] = None) -> None:
        self.consolidator = consolidator or ClaimConsolidator()

    _BOOLEAN_VALUES = {"true", "false"}
    _CANONICAL_VERBS = (
        "provides",
        "supports",
        "uses",
        "utilizes",
        "implements",
        "ensures",
        "maintains",
        "aligns",
        "reduces",
        "maps",
        "retrieves",
        "accelerates",
        "handles",
        "modernizes",
        "transforms",
        "requires",
        "enables",
        "resides",
        "is",
        "has",
    )

    def _normalize_whitespace(self, value: str) -> str:
        return re.sub(r"\s+", " ", value.strip())

    def _normalize_phrase(self, value: str) -> str:
        normalized = self._normalize_whitespace(value).lower()
        normalized = re.sub(r"[\"'`“”‘’]", "", normalized)
        normalized = re.sub(r"[^a-z0-9\s\-\+\(\)/&]", "", normalized)
        return normalized.strip()

    def _extract_entity_from_quote(self, claim: ExtractedClaim) -> str:
        quote = self._normalize_whitespace(claim.quote)
        if not quote:
            return claim.entity

        quoted_label = re.search(
            r"""["'](?P<label>[A-Z][A-Za-z0-9&+/\-\s]{2,80})["']\s+(?:functionality|feature|assistant|dashboard|engine|system|platform)\b""",
            quote,
        )
        if quoted_label:
            return quoted_label.group("label").strip()

        titled_subject = re.match(
            r"""^["']?(?:The\s+)?(?P<label>[A-Z][A-Za-z0-9&+/\-\s]{2,80}?)["']?\s+(?:provides|supports|uses|utilizes|implements|ensures|maintains|aligns|reduces|maps|retrieves|accelerates|handles|modernizes|transforms|requires|enables|resides|is|has)\b""",
            quote,
        )
        if titled_subject:
            return titled_subject.group("label").strip()

        return claim.entity

    def _canonicalize_predicate_and_value(self, claim: ExtractedClaim) -> tuple[str, str]:
        predicate = self._normalize_whitespace(claim.predicate).rstrip(".")
        value = self._normalize_whitespace(claim.value)

        if self._normalize_phrase(value) in self._BOOLEAN_VALUES:
            lowered_predicate = predicate.lower()
            for verb in self._CANONICAL_VERBS:
                if lowered_predicate.startswith(f"{verb} "):
                    remainder = predicate[len(verb):].strip(" .")
                    if remainder:
                        return verb, remainder
                if lowered_predicate == verb:
                    return verb, value

        return predicate, value

    def _canonicalize_claim(self, claim: ExtractedClaim) -> ExtractedClaim:
        entity = self._normalize_whitespace(self._extract_entity_from_quote(claim))
        predicate, value = self._canonicalize_predicate_and_value(claim)
        canonical_val = getattr(claim, "canonical_value", None)
        canonical_ent = getattr(claim, "canonical_entity", None)
        canonical_pred = getattr(claim, "canonical_predicate", None)
        try:
            from claim_layer.semantic.normalization import (
                register_canonical_value,
                register_entity_alias,
                register_predicate_alias,
            )
            if canonical_val is not None:
                register_canonical_value(value, canonical_val)
            if canonical_ent:
                register_entity_alias(entity, canonical_ent)
                if claim.entity and claim.entity != entity:
                    register_entity_alias(claim.entity, canonical_ent)
            if canonical_pred:
                register_predicate_alias(predicate, canonical_pred)
                predicate = canonical_pred
        except Exception:
            pass
        return ExtractedClaim(
            entity=entity,
            predicate=predicate,
            value=value,
            quote=self._normalize_whitespace(claim.quote),
            page_number=claim.page_number,
            paragraph_id=claim.paragraph_id,
            confidence=claim.confidence,
            claim_type=claim.claim_type,
            knowledge_level=claim.knowledge_level,
            inference_type=claim.inference_type,
            polarity=claim.polarity,
            valid_from=claim.valid_from,
            valid_until=claim.valid_until,
            canonical_value=canonical_val,
            canonical_entity=canonical_ent,
            canonical_predicate=canonical_pred,
            concept_fingerprint=getattr(claim, "concept_fingerprint", None),
            unit=getattr(claim, "unit", None),
            speaker_role=getattr(claim, "speaker_role", None),
            instances=getattr(claim, "instances", []),
        )

    def _claims_duplicate(self, left: ExtractedClaim, right: ExtractedClaim) -> bool:
        if (
            self._normalize_phrase(left.entity) == self._normalize_phrase(right.entity)
            and self._normalize_phrase(left.predicate) == self._normalize_phrase(right.predicate)
            and self._normalize_phrase(left.value) == self._normalize_phrase(right.value)
        ):
            return True

        left_quote = self._normalize_phrase(left.quote)
        right_quote = self._normalize_phrase(right.quote)
        if left_quote and right_quote and (left_quote in right_quote or right_quote in left_quote):
            return (
                self._normalize_phrase(left.predicate) == self._normalize_phrase(right.predicate)
                and self._normalize_phrase(left.value) == self._normalize_phrase(right.value)
            )

        return False

    def _claim_score(self, claim: ExtractedClaim) -> tuple[float, int, int]:
        return (
            claim.confidence,
            len(claim.quote.strip()),
            len(claim.value.strip()),
        )

    def _canonicalize_and_dedupe_claims(self, claims: List[ExtractedClaim]) -> List[ExtractedClaim]:
        canonical_claims = [self._canonicalize_claim(claim) for claim in claims]
        consolidated = self.consolidator.consolidate(canonical_claims)
        deduped: List[ExtractedClaim] = []
        duplicate_count = 0
        for claim in consolidated:
            duplicate_index = next(
                (index for index, existing in enumerate(deduped) if self._claims_duplicate(existing, claim)),
                None,
            )
            if duplicate_index is None:
                deduped.append(claim)
                continue
            duplicate_count += 1
            if self._claim_score(claim) > self._claim_score(deduped[duplicate_index]):
                deduped[duplicate_index] = claim
        if _DEBUG_INGESTION:
            print(
                "[claim-adapter:canonicalize]",
                {
                    "input_claims": len(claims),
                    "canonical_claims": len(canonical_claims),
                    "deduped_claims": len(deduped),
                    "duplicates_collapsed": duplicate_count,
                    "sample": [
                        {
                            "entity": claim.entity,
                            "predicate": claim.predicate,
                            "value": claim.value,
                            "quote_len": len(claim.quote or ""),
                        }
                        for claim in deduped[:8]
                    ],
                },
            )
        return deduped

    def to_ingested_document(
        self,
        claims: List[ExtractedClaim],
        document_id: str,
        project_id: str = "default",
        extraction_config: ExtractionConfig = None,
    ) -> IngestedDocument:
        """
        Build a single IngestedDocument from all claims in a document.
        Each claim carries its own page_number, set by IngestionPipeline.
        """
        claims = self._canonicalize_and_dedupe_claims(claims)
        entities: List[IngestedEntity] = []
        ingested_claims: List[IngestedClaim] = []
        facts: List[IngestedFact] = []

        for idx, claim in enumerate(claims):
            page = claim.page_number
            entity_id = f"{document_id}__e__{claim.entity}"
            claim_id = f"{document_id}__p{page}__c{idx}"
            paragraph_id = claim.paragraph_id or f"p{page}"

            entities.append(
                IngestedEntity(
                    entity_id=entity_id,
                    name=claim.entity,
                )
            )
            ingested_claims.append(
                IngestedClaim(
                    claim_id=claim_id,
                    text=claim.quote,
                    confidence=claim.confidence,
                    page=page,
                    paragraph_id=paragraph_id,
                )
            )
            facts.append(
                IngestedFact(
                    claim_ref=claim_id,
                    entity_ref=entity_id,
                    fact_type=claim.predicate,
                    value=claim.value,
                    sources=[
                        IngestedSource(
                            page=page,
                            paragraph_id=paragraph_id,
                            text=claim.quote,
                        )
                    ],
                    valid_from=claim.valid_from,
                    valid_until=claim.valid_until,
                    # Persist the (gate-clamped) inference type only for claims
                    # that went through the typed path; legacy claims stay NULL
                    # and are classified lexically at read time.
                    inference_type=claim.inference_type if claim.polarity is not None else None,
                )
            )

        if _DEBUG_INGESTION:
            print(
                "[claim-adapter:payload]",
                {
                    "document_id": document_id,
                    "entities": len(entities),
                    "claims": len(ingested_claims),
                    "facts": len(facts),
                    "empty_claim_texts": sum(1 for claim in ingested_claims if not claim.text),
                    "empty_fact_values": sum(1 for fact in facts if not fact.value),
                },
            )

        return IngestedDocument(
            project_id=project_id,
            filename=document_id,
            entities=entities,
            claims=ingested_claims,
            facts=facts,
            extraction_config=extraction_config.__dict__ if extraction_config else None,
        )
