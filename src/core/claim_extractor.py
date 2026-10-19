from __future__ import annotations

import json
import os
import re
import math
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from core.interfaces import ExtractionConfig, INFERENCE_WEIGHTS


# ---------------------------------------------------------------------------
# Core data structure
# ---------------------------------------------------------------------------

@dataclass
class ExtractedClaim:
    entity: str
    predicate: str
    value: str
    quote: str          # verbatim substring of source text the claim was drawn from
    page_number: int = 0    # set by IngestionPipeline after extraction
    paragraph_id: str = ""  # page chunk or paragraph provenance assigned upstream
    confidence: float = 1.0  # pipeline-level confidence (not requested from LLM)
    claim_type: str = "fact"  # fact | obligation | prohibition | definition | condition
    knowledge_level: str = "L1_EXPLICIT"  # L1_EXPLICIT | L2_INFERRED | L3_COMPOSED
    inference_type: str = "deductive"     # deductive | inductive | abductive | composed
    # Typed-extraction fields (core/hybrid_extraction.py). polarity=None marks
    # a legacy claim: the hybrid gate is skipped and behavior is unchanged.
    # When set ("affirmed" | "negated"), value must be BARE (no negation words)
    # and the pipeline folds polarity + clamps inference_type deterministically.
    polarity: Optional[str] = None
    valid_from: Optional[str] = None   # ISO-8601 or None
    valid_until: Optional[str] = None  # ISO-8601 or None
    instances: List[Any] = field(default_factory=list)
    canonical_value: Optional[Any] = None  # LLM-normalized scalar (int/float/ISO-8601/str) across any language
    canonical_entity: Optional[str] = None  # LLM-resolved canonical entity (coreference/alias resolution)
    canonical_predicate: Optional[str] = None  # LLM-normalized canonical predicate
    concept_fingerprint: Optional[str] = None  # LLM semantic item/period key (e.g. 'invoice:A-01:Q1' vs 'contract_total')
    unit: Optional[str] = None  # LLM-normalized unit/currency (e.g. 'EUR', 'USD', 'days')
    speaker_role: Optional[str] = None  # 'PROVEN_FACT' | 'PARTY_ALLEGATION' | 'WITNESS_CLAIM' | 'CONTRACT_CLAUSE'


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class ClaimExtractor:
    """
    Abstract extractor. Claims are extracted under provenance constraints.

    Extraction is allowed to be probabilistic (LLM-based),
    but accepted claims must always be:
    - grounded in text
    - traceable to exact source coordinates
    """
    def extract(self, text: str, extraction_config: ExtractionConfig) -> List[ExtractedClaim]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# LLM schema validation
# ---------------------------------------------------------------------------

_REQUIRED_FIELDS = {"entity", "predicate", "value", "confidence"}

_DEFAULT_LOCAL_LLM_ENDPOINT = os.environ.get("DELTORYX_LOCAL_LLM_ENDPOINT", "http://localhost:1234").rstrip("/")
_LOCAL_LLM_TIMEOUT_SECONDS = float(os.environ.get("DELTORYX_LOCAL_LLM_TIMEOUT_SECONDS", "300"))
_MAX_TEXT_CHARS = int(os.environ.get("DELTORYX_LLM_MAX_TEXT_CHARS", "6000"))
_MAX_CHUNK_CHARS = int(os.environ.get("DELTORYX_LLM_MAX_CHUNK_CHARS", "2200"))
_MAX_CONSOLIDATION_CLAIMS = int(os.environ.get("DELTORYX_LLM_MAX_CONSOLIDATION_CLAIMS", "24"))
_DEBUG_EXTRACTION = os.environ.get("DELTORYX_DEBUG_EXTRACTION", "false").lower() == "true"


class ClaimExtractionError(RuntimeError):
    """Raised when LLM-backed extraction cannot produce a valid claim payload."""


_KNOWN_API_PATHS = {"/v1/models", "/api/v1/models", "/api/tags", "/v1/chat/completions"}


def _normalize_endpoint(endpoint: str) -> str:
    base = endpoint.strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ClaimExtractionError("Extraction endpoint must be a valid http(s) URL.")
    # Strip known API sub-paths so callers always get just the base URL
    if parsed.path in _KNOWN_API_PATHS:
        return f"{parsed.scheme}://{parsed.netloc}"
    return base


_CLAIM_TYPES = "fact | obligation | prohibition | definition | condition"

# Inference types offered to the extractor (subset of INFERENCE_WEIGHTS keys
# that an extractor can meaningfully distinguish from surface language).
_INFERENCE_TYPES = (
    "deductive | semantic | arithmetic | temporal | authority | causal | "
    "probabilistic | attribution | heuristic | abductive | narrative | default"
)

_POLICY_INSTRUCTIONS = {
    "conservative": "Extract ONLY claims explicitly and unambiguously stated in the text.",
    "balanced": "Extract explicit claims and strong grounded implications. Avoid speculative or inferred claims not supported by the text.",
    "aggressive": "Extract all grounded candidate claims, including weak but text-supported implications.",
}


def _build_prompt(policy: str, text: str) -> List[Dict[str, str]]:
    bounded_text = text.strip()[:_MAX_TEXT_CHARS]
    policy_instruction = _POLICY_INSTRUCTIONS.get(policy, "Extract grounded factual claims from the text.")

    system_content = (
        "You extract structured factual claims from document text for an evidence ledger.\n\n"
        f"{policy_instruction}\n\n"
        "PRIORITIES:\n"
        "- Focus on legally or operationally relevant claims.\n"
        "- Prioritize obligations, prohibitions, conditions, and definitions.\n"
        "- Ignore layout noise (headers, footers, navigation, logos).\n\n"
        "OUTPUT REQUIREMENTS:\n"
        "- Return ONLY valid JSON.\n"
        "- No explanations, no markdown, no extra keys.\n\n"
        'SCHEMA:\n{"claims":[{"entity":string,"canonical_entity":string|null,'
        '"predicate":string,"canonical_predicate":string|null,"value":string,'
        '"canonical_value":number|string|null,"concept_fingerprint":string|null,'
        '"unit":string|null,"speaker_role":"PROVEN_FACT | PARTY_ALLEGATION | WITNESS_CLAIM | CONTRACT_CLAUSE",'
        f'"type":"{_CLAIM_TYPES}","quote":string,'
        '"polarity":"affirmed | negated",'
        f'"inference":"{_INFERENCE_TYPES}",'
        '"valid_from":string|null,"valid_until":string|null}]}\n\n'
        "RULES:\n"
        "- Extract ONLY grounded claims explicitly supported by the text.\n"
        '- The "quote" must be a verbatim substring of the input text.\n'
        "- Do NOT hallucinate or generalize beyond the text.\n"
        "- Do NOT include confidence scores.\n"
        '- "value" must be the BARE value with NO negation words. Express negation'
        ' ONLY via "polarity":"negated" (e.g. "the DPA is not signed" →'
        ' value="signed", polarity="negated"). Resolve double negation to its real'
        " polarity.\n"
        '- "canonical_entity": resolve coreferences and titles ("El Sr. Pérez", "D. Juan Pérez García" → "Juan_Perez").\n'
        '- "canonical_predicate": normalize domain synonyms into a standard attribute ("honorarios_devengados" → "amount", "plazo_abono" → "payment_days").\n'
        '- "canonical_value": normalize written numbers, durations, or monetary amounts in ANY language'
        ' into a clean scalar (e.g. "trente jours" or "thirty days" → 30, "ciento cuarenta y dos mil euros" → 142000.0,'
        ' dates → ISO-8601 "YYYY-MM-DD").\n'
        '- "concept_fingerprint": semantic identifier for disambiguating distinct periodic items vs repeated totals (e.g. "invoice:A-01:Q1" vs "contract_total").\n'
        '- "unit": normalized unit or ISO currency ("EUR", "USD", "days", "months") if numeric; otherwise null.\n'
        '- "speaker_role": "PROVEN_FACT" for verified court findings/facts, "PARTY_ALLEGATION" for unilateral defense/plaintiff claims, "WITNESS_CLAIM" for unratified testimony, "CONTRACT_CLAUSE" for binding obligations.\n'
        '- "inference": how the text asserts the value — "authority" for official/'
        'expert statements, "attribution" for reported second-hand speech, '
        '"heuristic" for hedged/approximate language (including irony), "temporal" '
        'for date-bound facts, "deductive" only for direct explicit assertions.\n'
        '- "valid_from"/"valid_until": ISO-8601 dates ONLY when the text states an'
        " explicit validity window; otherwise null.\n"
        '- If no valid claims exist, return: {"claims": []}\n\n'
        "Return as many valid claims as possible (up to 30)."
    )

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": bounded_text},
    ]


def _build_consolidation_prompt(
    policy: str,
    text: str,
    existing_claims: List[ExtractedClaim],
) -> List[Dict[str, str]]:
    bounded_text = text.strip()[:_MAX_TEXT_CHARS]
    policy_instruction = _POLICY_INSTRUCTIONS.get(policy, "Extract grounded factual claims from the text.")
    existing_preview = [
        f"- {claim.entity} | {claim.predicate} | {claim.value}"
        for claim in existing_claims[:_MAX_CONSOLIDATION_CLAIMS]
    ]
    known_claims = "\n".join(existing_preview) if existing_preview else "- none"

    system_content = (
        "You are consolidating factual claims extracted from multiple chunks of the same document.\n\n"
        f"{policy_instruction}\n\n"
        "YOUR TASK:\n"
        "- Read the broader document context.\n"
        "- Identify important grounded claims that were likely missed in chunk-level extraction.\n"
        "- Prefer central claims about product definition, core capabilities, operational benefits, compliance, architecture, and constraints.\n"
        "- Do NOT repeat claims already captured unless a materially better quote is available.\n\n"
        "OUTPUT REQUIREMENTS:\n"
        "- Return ONLY valid JSON.\n"
        "- No explanations, no markdown, no extra keys.\n\n"
        'SCHEMA:\n{"claims":[{"entity":string,"predicate":string,"value":string,'
        f'"type":"{_CLAIM_TYPES}","quote":string}}]}}\n\n'
        "RULES:\n"
        "- Extract ONLY grounded claims explicitly supported by the text.\n"
        '- The "quote" must be a verbatim substring of the input text.\n'
        "- Prefer missing document-level claims over local details already covered.\n"
        "- Avoid generic or weak boolean claims when a more specific factual claim is available.\n"
        '- If no additional claims exist, return: {"claims": []}\n'
        f"- Return at most {_MAX_CONSOLIDATION_CLAIMS} additional claims."
    )
    user_content = (
        "Document text:\n"
        f"{bounded_text}\n\n"
        "Claims already captured:\n"
        f"{known_claims}\n\n"
        "Return only additional high-value grounded claims that are not duplicates of the existing list."
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


_LLM_MAX_TOKENS = int(os.environ.get("DELTORYX_LLM_MAX_TOKENS", "4096"))


def _build_request_payload(
    text: str,
    extraction_config: ExtractionConfig,
    *,
    consolidation: bool = False,
    existing_claims: Optional[List[ExtractedClaim]] = None,
) -> dict[str, Any]:
    return {
        "model": extraction_config.model,
        "temperature": 0,
        "max_tokens": _LLM_MAX_TOKENS,
        "messages": (
            _build_consolidation_prompt(str(extraction_config.policy), text, existing_claims or [])
            if consolidation
            else _build_prompt(str(extraction_config.policy), text)
        ),
    }


def _debug_log(stage: str, **context: Any) -> None:
    if not _DEBUG_EXTRACTION:
        return
    parts = [f"{key}={value!r}" for key, value in context.items()]
    print(f"[claim-extractor:{stage}] " + " ".join(parts))


def _resolve_endpoint(extraction_config: ExtractionConfig) -> str:
    endpoint = str(extraction_config.endpoint or "").strip()
    if endpoint:
        return _normalize_endpoint(endpoint)

    if str(extraction_config.provider).lower() == "local_llm":
        return _DEFAULT_LOCAL_LLM_ENDPOINT

    raise ClaimExtractionError("Extraction config is missing an endpoint.")


def _repair_truncated_json(text: str) -> Optional[Any]:
    """
    Best-effort recovery of a truncated JSON array/object.
    Tries to salvage complete claim objects from a partially-written array.
    Returns parsed data on success, None if unrecoverable.
    """
    # Find the start of the claims array
    array_start = text.find('[')
    if array_start == -1:
        return None

    # Walk backwards from truncation point, finding the last complete object
    segment = text[array_start:]
    # Try increasingly truncated suffixes to find the last valid full object
    last_close = segment.rfind('}')
    while last_close > 0:
        candidate = segment[:last_close + 1] + ']'
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            last_close = segment.rfind('}', 0, last_close)
    return None


_VALID_CLAIM_TYPES = frozenset({"fact", "obligation", "prohibition", "definition", "condition"})


def _validate_llm_response(raw: str) -> List[ExtractedClaim]:
    """
    Parse and validate an LLM JSON response.

    Expected schema:
      {"claims": [{"entity": str, "predicate": str, "value": str,
                   "type": str, "quote": str}]}

    Raises ClaimExtractionError on schema violations so ingestion can fail loudly.
    """
    # Accept fenced markdown JSON outputs from local models.
    clean = raw.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)

    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        # Try to salvage complete claim objects from a truncated response
        repaired = _repair_truncated_json(clean)
        if repaired is not None:
            data = repaired
        else:
            # Re-raise with original error for clarity
            try:
                json.loads(clean)
            except json.JSONDecodeError as exc:
                raise ClaimExtractionError(f"Model returned invalid JSON: {exc}") from exc
            data = repaired  # unreachable, satisfies type checker

    # Accepted shapes:
    # 1) {"claims": [...]} (preferred)
    # 2) [...] (common local-model fallback)
    if isinstance(data, dict):
        items = data.get("claims", [])
    elif isinstance(data, list):
        items = data
    else:
        raise ClaimExtractionError("Model returned an unsupported JSON payload.")

    if not isinstance(items, list):
        raise ClaimExtractionError("Model response field 'claims' must be a list.")

    # Common alternative field names used by some models
    _ENTITY_ALIASES = ("entity", "subject", "actor", "name")
    _PREDICATE_ALIASES = ("predicate", "relation", "relationship", "property", "attribute")
    _VALUE_ALIASES = ("value", "object", "object_value", "result", "detail")
    _QUOTE_ALIASES = ("quote", "text", "excerpt", "sentence", "raw_text")

    def _pick(d: dict, aliases: tuple) -> Optional[str]:
        for key in aliases:
            if key in d:
                v = d[key]
                return str(v).strip() if v is not None else None
        return None

    claims: List[ExtractedClaim] = []
    for item in items:
        if not isinstance(item, dict):
            continue  # skip non-object entries rather than failing the whole ingest

        entity = _pick(item, _ENTITY_ALIASES)
        predicate = _pick(item, _PREDICATE_ALIASES)
        value = _pick(item, _VALUE_ALIASES)

        if not entity or not predicate or not value:
            continue  # skip malformed claim items

        quote = _pick(item, _QUOTE_ALIASES) or ""

        raw_type = str(item.get("type", "fact")).strip().lower()
        claim_type = raw_type if raw_type in _VALID_CLAIM_TYPES else "fact"

        # confidence: no longer requested from LLM, kept at default 1.0
        # tolerated if the LLM still sends it (backward compat)
        try:
            raw_conf = item.get("confidence")
            confidence = 1.0 if raw_conf is None else float(raw_conf)
            if confidence < 0.0 or confidence > 1.0:
                confidence = 1.0
        except (TypeError, ValueError):
            confidence = 1.0

        # Typed-extraction fields — tolerant parsing: anything malformed
        # degrades to the legacy path (polarity=None), never fails ingestion.
        raw_polarity = str(item.get("polarity") or "").strip().lower()
        polarity = raw_polarity if raw_polarity in {"affirmed", "negated"} else None

        raw_inference = str(item.get("inference") or item.get("inference_type") or "").strip().lower()
        inference_type = raw_inference if raw_inference in INFERENCE_WEIGHTS else "default"

        def _clean_opt_str(key: str) -> Optional[str]:
            raw = item.get(key)
            if raw is None:
                return None
            text_value = str(raw).strip()
            return text_value if text_value and text_value.lower() != "null" else None

        raw_canonical = item.get("canonical_value")
        if raw_canonical is not None and str(raw_canonical).strip().lower() != "null":
            try:
                from claim_layer.semantic.normalization import register_canonical_value
                canonical_value = register_canonical_value(value, raw_canonical)
            except Exception:
                canonical_value = raw_canonical
        else:
            canonical_value = None

        canonical_entity = _clean_opt_str("canonical_entity")
        canonical_predicate = _clean_opt_str("canonical_predicate")
        concept_fingerprint = _clean_opt_str("concept_fingerprint")
        unit = _clean_opt_str("unit")
        speaker_role = _clean_opt_str("speaker_role")

        try:
            from claim_layer.semantic.normalization import (
                register_entity_alias,
                register_predicate_alias,
            )
            if canonical_entity:
                register_entity_alias(entity, canonical_entity)
            if canonical_predicate:
                register_predicate_alias(predicate, canonical_predicate)
        except Exception:
            pass

        claims.append(
            ExtractedClaim(
                entity=entity,
                predicate=predicate,
                value=value,
                quote=quote,
                confidence=confidence,
                claim_type=claim_type,
                inference_type=inference_type if polarity is not None else "deductive",
                polarity=polarity,
                valid_from=_clean_opt_str("valid_from") if polarity is not None else None,
                valid_until=_clean_opt_str("valid_until") if polarity is not None else None,
                canonical_value=canonical_value,
                canonical_entity=canonical_entity,
                canonical_predicate=canonical_predicate,
                concept_fingerprint=concept_fingerprint,
                unit=unit,
                speaker_role=speaker_role,
            )
        )
    return claims


def _extract_json_payload(text: str) -> str:
    """
    Best-effort extractor for a top-level JSON object/array from free-form model output.
    """
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return stripped

    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        return text
    start = min(starts)

    if text[start] == "{":
        end = text.rfind("}")
    else:
        end = text.rfind("]")

    if end == -1 or end <= start:
        return text
    return text[start:end + 1]


def _chunk_text(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> List[str]:
    """
    Split long page text into paragraph-aware chunks to improve extraction recall.
    """
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return [cleaned] if cleaned else []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    def flush_current() -> None:
        nonlocal current, current_len
        if current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0

    for para in paragraphs:
        # Very long paragraph: split by sentence-ish boundaries as fallback
        if len(para) > max_chars:
            flush_current()
            sentence_parts = re.split(r"(?<=[\.!?;:])\s+", para)
            segment = ""
            for part in sentence_parts:
                part = part.strip()
                if not part:
                    continue
                candidate = f"{segment} {part}".strip() if segment else part
                if len(candidate) <= max_chars:
                    segment = candidate
                else:
                    if segment:
                        chunks.append(segment)
                    if len(part) <= max_chars:
                        segment = part
                    else:
                        # Hard cut if even a single sentence is too long
                        for i in range(0, len(part), max_chars):
                            chunks.append(part[i:i + max_chars])
                        segment = ""
            if segment:
                chunks.append(segment)
            continue

        projected = current_len + (2 if current else 0) + len(para)
        if projected <= max_chars:
            current.append(para)
            current_len = projected
        else:
            flush_current()
            current.append(para)
            current_len = len(para)

    flush_current()
    return chunks


def _looks_like_heading(paragraph: str) -> bool:
    candidate = paragraph.strip()
    if not candidate or len(candidate) > 120:
        return False
    if re.match(r"^\d+(?:\.\d+)*[\.\)]\s+\S+", candidate):
        return True
    if candidate.endswith(":") and len(candidate.split()) <= 10:
        return True
    words = candidate.split()
    if 1 <= len(words) <= 8 and candidate == candidate.title():
        return True
    return False


def _split_sections(text: str) -> List[Tuple[str, str]]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    if not paragraphs:
        return []

    sections: List[Tuple[str, str]] = []
    current_title = "Document Context"
    current_parts: List[str] = []

    def flush() -> None:
        nonlocal current_parts, current_title
        if current_parts:
            sections.append((current_title, "\n\n".join(current_parts).strip()))
            current_parts = []

    for paragraph in paragraphs:
        if _looks_like_heading(paragraph):
            flush()
            current_title = paragraph.rstrip(":")
            continue
        current_parts.append(paragraph)

    flush()
    return sections


def _chunk_sections(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> List[str]:
    sections = _split_sections(text)
    if not sections:
        return _chunk_text(text, max_chars=max_chars)

    chunked: List[str] = []
    for title, body in sections:
        section_text = f"{title}\n\n{body}".strip() if body else title
        chunked.extend(_chunk_text(section_text, max_chars=max_chars))
    return [chunk for chunk in chunked if chunk.strip()]


def _normalize_phrase(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    normalized = re.sub(r"[\"'`“”‘’]", "", normalized)
    normalized = re.sub(r"[^a-z0-9\s\-\+\(\)/&]", "", normalized)
    return normalized.strip()


def _token_set(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9\+]+", _normalize_phrase(value)) if len(token) > 1}


def _jaccard_similarity(left: str, right: str) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _quote_overlap(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_norm = _normalize_phrase(left)
    right_norm = _normalize_phrase(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm in right_norm or right_norm in left_norm:
        return min(len(left_norm), len(right_norm)) / max(len(left_norm), len(right_norm))
    return _jaccard_similarity(left_norm, right_norm)


def _claim_specificity_score(claim: ExtractedClaim) -> float:
    boolean_penalty = 0.4 if claim.value.strip().lower() in {"true", "false"} else 0.0
    quote_bonus = min(len(claim.quote.strip()), 180) / 180 if claim.quote.strip() else 0.0
    value_bonus = min(len(claim.value.strip()), 120) / 120
    predicate_bonus = min(len(claim.predicate.strip()), 60) / 120
    entity_bonus = min(len(claim.entity.strip()), 60) / 180
    return quote_bonus + value_bonus + predicate_bonus + entity_bonus - boolean_penalty


def _claims_semantically_duplicate(left: ExtractedClaim, right: ExtractedClaim) -> bool:
    same_value = _normalize_phrase(left.value) == _normalize_phrase(right.value)
    same_predicate = _normalize_phrase(left.predicate) == _normalize_phrase(right.predicate)
    same_entity = _normalize_phrase(left.entity) == _normalize_phrase(right.entity)

    if same_entity and same_predicate and same_value:
        return True

    entity_similarity = _jaccard_similarity(left.entity, right.entity)
    predicate_similarity = _jaccard_similarity(left.predicate, right.predicate)
    value_similarity = _jaccard_similarity(left.value, right.value)
    quote_similarity = _quote_overlap(left.quote, right.quote)

    if same_value and (same_predicate or predicate_similarity >= 0.7) and (
        entity_similarity >= 0.45
        or quote_similarity >= 0.75
        or _normalize_phrase(left.entity) in _normalize_phrase(right.entity)
        or _normalize_phrase(right.entity) in _normalize_phrase(left.entity)
    ):
        return True

    if same_entity and value_similarity >= 0.85 and (same_predicate or predicate_similarity >= 0.55):
        return True

    if quote_similarity >= 0.82 and value_similarity >= 0.75 and predicate_similarity >= 0.45:
        return True

    return False


def _dedupe_claims(claims: List[ExtractedClaim]) -> List[ExtractedClaim]:
    seen: Dict[Tuple[str, str, str], ExtractedClaim] = {}
    for claim in claims:
        key = (claim.entity.lower().strip(), claim.predicate.lower().strip(), claim.value.lower().strip())
        existing = seen.get(key)
        if existing is None or claim.confidence > existing.confidence:
            seen[key] = claim
    deduped = list(seen.values())
    collapsed: List[ExtractedClaim] = []
    for claim in deduped:
        duplicate_index = next(
            (index for index, existing in enumerate(collapsed) if _claims_semantically_duplicate(existing, claim)),
            None,
        )
        if duplicate_index is None:
            collapsed.append(claim)
            continue

        existing = collapsed[duplicate_index]
        keep_new = (
            _claim_specificity_score(claim) > _claim_specificity_score(existing)
            or (
                math.isclose(_claim_specificity_score(claim), _claim_specificity_score(existing), rel_tol=1e-6)
                and claim.confidence >= existing.confidence
            )
        )
        if keep_new:
            collapsed[duplicate_index] = claim
    return collapsed


def _call_llm_for_claims(
    text: str,
    extraction_config: ExtractionConfig,
    *,
    consolidation: bool = False,
    existing_claims: Optional[List[ExtractedClaim]] = None,
) -> List[ExtractedClaim]:
    endpoint = _resolve_endpoint(extraction_config)
    payload = _build_request_payload(
        text,
        extraction_config,
        consolidation=consolidation,
        existing_claims=existing_claims,
    )
    _debug_log(
        "request",
        endpoint=endpoint,
        model=extraction_config.model,
        policy=extraction_config.policy,
        consolidation=consolidation,
        text_preview=text[:300],
        text_len=len(text),
    )
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if extraction_config.api_key:
        headers["Authorization"] = f"Bearer {extraction_config.api_key}"

    request = Request(
        f"{endpoint}/v1/chat/completions",
        data=body,
        headers=headers,
        method="POST",
    )

    try:
        with urlopen(request, timeout=_LOCAL_LLM_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""
        raise ClaimExtractionError(
            f"Model endpoint returned HTTP {exc.code}{f': {detail}' if detail else ''}"
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise ClaimExtractionError(f"Model endpoint request failed: {exc}") from exc

    try:
        parsed = json.loads(raw)
        content = parsed["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raw_preview = raw[:400] if raw else "(empty)"
        raise ClaimExtractionError(
            f"Model response did not match OpenAI-compatible chat completions shape. "
            f"Raw response (first 400 chars): {raw_preview}"
        ) from exc

    _debug_log(
        "response",
        raw_preview=raw[:800],
        raw_len=len(raw),
        content_type=type(content).__name__,
    )

    # content can be a string (standard) or a list of content blocks (structured output models)
    if isinstance(content, list):
        # Concatenate all text-type blocks
        parts = [block["text"] for block in content if isinstance(block, dict) and block.get("type") == "text"]
        if not parts:
            raise ClaimExtractionError("Model response content blocks contained no text.")
        content = "\n".join(parts)
    elif content is None:
        raise ClaimExtractionError("Model response content was null.")
    elif not isinstance(content, str):
        raise ClaimExtractionError(f"Model response content has unexpected type: {type(content).__name__}.")

    extracted = _validate_llm_response(_extract_json_payload(content))
    _debug_log(
        "validated",
        claims_count=len(extracted),
        claims_preview=[{
            "entity": claim.entity,
            "predicate": claim.predicate,
            "value": claim.value,
            "quote": claim.quote[:120],
        } for claim in extracted[:5]],
    )
    return extracted


# ---------------------------------------------------------------------------
# Public extractor
# ---------------------------------------------------------------------------

class LLMClaimExtractor(ClaimExtractor):
    """
    Production extractor: all claims are produced by an LLM-backed runtime.
    """

    def __init__(
        self,
        llm_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._llm_fn = llm_fn

    def _extract_from_text(
        self,
        text: str,
        extraction_config: ExtractionConfig,
        *,
        consolidation: bool = False,
        existing_claims: Optional[List[ExtractedClaim]] = None,
    ) -> List[ExtractedClaim]:
        if self._llm_fn is not None:
            raw = self._llm_fn(text)
            return _validate_llm_response(raw)
        return _call_llm_for_claims(
            text,
            extraction_config,
            consolidation=consolidation,
            existing_claims=existing_claims,
        )

    def extract(self, text: str, extraction_config: ExtractionConfig) -> List[ExtractedClaim]:
        provider = str(getattr(extraction_config, "provider", "") or "").lower()
        model = str(getattr(extraction_config, "model", "") or "").strip()
        if provider not in {"local_llm", "openai"}:
            raise ClaimExtractionError(f"Unsupported extraction provider: {provider or 'missing'}")
        if not model:
            raise ClaimExtractionError("Extraction config is missing a model.")
        _resolve_endpoint(extraction_config)

        chunks = _chunk_sections(text)
        if not chunks:
            return []

        extracted: List[ExtractedClaim] = []
        for index, chunk in enumerate(chunks, start=1):
            _debug_log("chunk", index=index, total=len(chunks), chunk_len=len(chunk), chunk_preview=chunk[:300])
            extracted.extend(self._extract_from_text(chunk, extraction_config))

        if len(chunks) > 1:
            consolidated = self._extract_from_text(
                text,
                extraction_config,
                consolidation=True,
                existing_claims=extracted,
            )
            _debug_log("consolidated", added=len(consolidated), existing=len(extracted))
            extracted.extend(consolidated)
        deduped = _dedupe_claims(extracted)
        _debug_log("deduped", before=len(extracted), after=len(deduped))
        return deduped


class DocumentEvidenceExtractor(LLMClaimExtractor):
    """Canonical extractor for persisted document evidence candidates."""


# ---------------------------------------------------------------------------
# Stub — kept for tests that don't exercise real extraction
# ---------------------------------------------------------------------------

class StubClaimExtractor(ClaimExtractor):
    """
    Deterministic extractor for testing.
    Returns a fixed list of claims regardless of input text.
    extraction_config is accepted and ignored — stubs have no config dependency.
    """

    def __init__(self, claims: Optional[List[ExtractedClaim]] = None) -> None:
        self._claims: List[ExtractedClaim] = claims or []

    def extract(self, text: str, extraction_config: Optional["ExtractionConfig"] = None) -> List[ExtractedClaim]:  # type: ignore[override]
        return self._claims
