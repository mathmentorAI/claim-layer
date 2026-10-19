"""
Deterministic value normalization for truth resolution.

Rules (v0.3 — limited, no heuristics):
  A. Extract a leading integer from "N <unit>" patterns  ("30 days" → 30)
  B. Map written English numbers to integers              ("thirty days" → 30)

Safety contract:
  If normalization is uncertain or ambiguous, canonical_value = original_value.
  This function NEVER raises. It returns the input unchanged on any failure.
"""
from __future__ import annotations

import re

# Written English & Spanish number words → integer (single words only, 1–99)
_WORD_TO_INT: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    # Spanish equivalents
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4,
    "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
    "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "dieciséis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "treinta": 30, "cuarenta": 40, "cincuenta": 50,
    "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90,
}

# Two-word written numbers: "twenty one" … "ninety nine"
_TENS = {
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "veinte", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa",
}
_ONES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
}

# Matches a bare integer at the start of the string, optionally followed by text
# e.g. "30", "30 days", "30-day period"
_LEADING_INT = re.compile(r"^\s*(\d+)(?:\s|$|-)")

# Full string is just an integer (no units)
_BARE_INT = re.compile(r"^\s*(\d+)\s*$")

# Bare float (e.g. "25000.0", "142000.50")
_BARE_FLOAT = re.compile(r"^\s*(\d+\.\d+)\s*$")

# Deterministic registries populated at ingestion time by Phase 1 LLM extraction
# or by an injected LLMValueNormalizer / normalizer_fn.
_CANONICAL_OVERRIDES: dict[str, int | float | str] = {}
_ENTITY_ALIAS_REGISTRY: dict[str, str] = {}
_PREDICATE_ALIAS_REGISTRY: dict[str, str] = {}

_HONORIFIC_PREFIX_RE = re.compile(
    r"^(?:el\s+|la\s+|los\s+|las\s+)?(?:d\.|dña\.|dna\.|don|doña|dona|sr\.|sra\.|srta\.|dr\.|dra\.|mr\.|mrs\.|ms\.|prof\.)\s+",
    re.IGNORECASE,
)
_CORP_SUFFIX_RE = re.compile(
    r"[\s,]+(?:s\.a\.u\.|s\.l\.u\.|s\.a\.|s\.l\.|s\.c\.|inc\.|ltd\.|llc|gmbh|s\.a|s\.l)\s*$",
    re.IGNORECASE,
)


def _clean_entity_key(text: str) -> str:
    if not text:
        return ""
    s = text.strip().replace("_", " ")
    # Repeatedly strip leading articles/honorifics (e.g. "El Sr. D. Juan Pérez")
    for _ in range(3):
        s_new = _HONORIFIC_PREFIX_RE.sub("", s).strip()
        if s_new == s:
            break
        s = s_new
    s = _CORP_SUFFIX_RE.sub("", s).strip()
    s = re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ]+", " ", s).strip().lower()
    return re.sub(r"\s+", " ", s)


def register_entity_alias(raw_entity: str, canonical_entity: str) -> str:
    """Register a canonical entity alias mapping (e.g. emitted by Phase 1 LLM extraction)
    so that multi-hop traversal and entity matching resolve coreferences ('El Sr. Pérez',
    'D. Juan Pérez García' -> 'Juan_Perez') deterministically in 0ms.
    """
    if not isinstance(raw_entity, str) or not raw_entity.strip():
        return str(canonical_entity or raw_entity or "")
    if not isinstance(canonical_entity, str) or not canonical_entity.strip():
        return normalize_entity_name(raw_entity)
    canon_clean = _clean_entity_key(canonical_entity)
    raw_clean = _clean_entity_key(raw_entity)
    if raw_clean and canon_clean:
        _ENTITY_ALIAS_REGISTRY[raw_clean] = canon_clean
    _ENTITY_ALIAS_REGISTRY[raw_entity.strip().lower()] = canon_clean or canonical_entity.strip().lower()
    return canon_clean or canonical_entity.strip().lower()


def normalize_entity_name(raw_entity: str | None) -> str:
    """Resolve *raw_entity* to its canonical normalized entity key.
    1. Checks `_ENTITY_ALIAS_REGISTRY` populated at ingestion time by LLM `canonical_entity`.
    2. Strips honorifics ('El Sr.', 'D.', 'Doña') and corporate suffixes ('S.A.', 'S.L.').
    """
    if not raw_entity:
        return ""
    low = str(raw_entity).strip().lower()
    if low in _ENTITY_ALIAS_REGISTRY:
        return _ENTITY_ALIAS_REGISTRY[low]
    cleaned = _clean_entity_key(str(raw_entity))
    if cleaned in _ENTITY_ALIAS_REGISTRY:
        return _ENTITY_ALIAS_REGISTRY[cleaned]
    return cleaned


def register_predicate_alias(raw_predicate: str, canonical_predicate: str) -> str:
    """Register a canonical predicate mapping emitted by Phase 1 LLM extraction."""
    if not isinstance(raw_predicate, str) or not raw_predicate.strip():
        return str(canonical_predicate or raw_predicate or "")
    if not isinstance(canonical_predicate, str) or not canonical_predicate.strip():
        return raw_predicate.strip().lower()
    canon = canonical_predicate.strip().lower()
    _PREDICATE_ALIAS_REGISTRY[raw_predicate.strip().lower()] = canon
    return canon


def normalize_predicate_name(raw_predicate: str | None) -> str:
    """Resolve *raw_predicate* via `_PREDICATE_ALIAS_REGISTRY` if registered."""
    if not raw_predicate:
        return ""
    low = str(raw_predicate).strip().lower()
    return _PREDICATE_ALIAS_REGISTRY.get(low, low)


def _coerce_canonical_scalar(val: object) -> int | float | str:
    """Coerce a canonical value (from LLM JSON or normalizer_fn) into int, float, or str."""
    if isinstance(val, bool):
        return str(val).lower()
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val) if val.is_integer() else val
    s = str(val).strip()
    if _BARE_INT.match(s):
        return int(s)
    if _BARE_FLOAT.match(s):
        f = float(s)
        return int(f) if f.is_integer() else f
    return s


def register_canonical_value(
    raw_value: str, canonical_value: object
) -> int | float | str:
    """Register a canonical value mapping (e.g. produced by an LLM at ingestion time)
    so that downstream deterministic truth resolution (`normalize_value`) resolves
    *raw_value* in any language to *canonical_value* with zero network calls during `ask()`.
    """
    if canonical_value is None or not isinstance(raw_value, str) or not raw_value.strip():
        return normalize_value(raw_value) if isinstance(raw_value, str) else str(raw_value)
    coerced = _coerce_canonical_scalar(canonical_value)
    # If coerced is still a string with a leading integer (e.g. "30 days"), normalize it further
    if isinstance(coerced, str):
        m_int = _BARE_INT.match(coerced) or _LEADING_INT.match(coerced)
        if m_int:
            coerced = int(m_int.group(1))
    _CANONICAL_OVERRIDES[raw_value.strip().lower()] = coerced
    return coerced


def clear_canonical_overrides() -> None:
    """Clear registered canonical overrides (useful for isolated unit tests)."""
    _CANONICAL_OVERRIDES.clear()
    _ENTITY_ALIAS_REGISTRY.clear()
    _PREDICATE_ALIAS_REGISTRY.clear()


class LLMValueNormalizer:
    """Multilingual LLM-backed value normalizer with deterministic SHA-256 caching.

    Can be passed to `ClaimLayer(normalizer_fn=LLMValueNormalizer(...))` to normalize
    complex expressions in any language supported by the LLM (e.g. French 'trente jours',
    German 'dreißig Tage', Portuguese 'trinta dias', Spanish 'ciento cuarenta y dos mil euros',
    'un trimestre y medio') into canonical scalars at ingestion time.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        llm_callable=None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._llm_callable = llm_callable
        self._cache: dict[str, int | float | str] = {}

    def __call__(self, raw_value: str) -> int | float | str:
        if not isinstance(raw_value, str) or not raw_value.strip():
            return raw_value
        key = raw_value.strip().lower()
        if key in self._cache:
            return self._cache[key]
        if key in _CANONICAL_OVERRIDES:
            return _CANONICAL_OVERRIDES[key]

        # Fast path: if already a clean integer/number handled deterministically, avoid LLM call
        fast = normalize_value(raw_value)
        if isinstance(fast, (int, float)):
            self._cache[key] = fast
            return fast

        resolved: object = raw_value
        if self._llm_callable is not None:
            resolved = self._llm_callable(raw_value)
        elif self._api_key:
            import json
            from openai import OpenAI

            client = OpenAI(api_key=self._api_key)
            resp = client.chat.completions.create(
                model=self._model,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a deterministic multilingual canonical value normalizer. "
                            "Convert written numbers, durations, monetary quantities, or dates in ANY language "
                            "into their canonical scalar representation:\n"
                            "- Written durations in days/weeks/months (e.g. 'trente jours', 'dreißig Tage', 'trinta dias') -> integer number of days (e.g. 30).\n"
                            "- Written monetary or numeric amounts (e.g. 'ciento cuarenta y dos mil euros', 'vingt-cinq mille euros') -> numeric float/int (e.g. 142000, 25000).\n"
                            "- Explicit dates in any language -> ISO-8601 string 'YYYY-MM-DD'.\n"
                            "- Otherwise return the concise canonical string.\n"
                            'Return ONLY JSON: {"canonical_value": <number_or_string>}'
                        ),
                    },
                    {"role": "user", "content": raw_value},
                ],
            )
            data = json.loads(resp.choices[0].message.content)
            resolved = data.get("canonical_value", raw_value)

        coerced = register_canonical_value(raw_value, resolved)
        self._cache[key] = coerced
        return coerced


def normalize_value(value: str) -> int | float | str:
    """Return the canonical form of *value*, or *value* itself if uncertain.

    1. Checks deterministic `_CANONICAL_OVERRIDES` populated at ingestion time by
       Phase 1 LLM extraction (`canonical_value`) or `LLMValueNormalizer`.
    2. Falls back to zero-latency deterministic rules (Cases A, B, B2).

    Deterministic. No network calls during resolution. Never raises.
    """
    if not isinstance(value, str):
        return value

    v = value.strip()
    lower = v.lower()

    # --- Case 0: LLM / ingestion-time registered canonical override ---
    if lower in _CANONICAL_OVERRIDES:
        return _CANONICAL_OVERRIDES[lower]

    # --- Case A: bare integer or leading integer before a unit/separator ---
    m = _BARE_INT.match(v)
    if m:
        return int(m.group(1))

    m = _LEADING_INT.match(v)
    if m:
        return int(m.group(1))

    # --- Case B: written English/Spanish number (single word) ---
    if lower in _WORD_TO_INT:
        return _WORD_TO_INT[lower]

    # --- Case B2: two-word written number ("thirty days", "forty five", "treinta días") ---
    parts = lower.split()
    if len(parts) >= 2 and parts[0] in _TENS:
        if parts[1] in _ONES:
            # "forty five" → 45, "forty five days" → 45
            return _WORD_TO_INT[parts[0]] + _ONES[parts[1]]
        if len(parts) >= 3 and parts[1] == "y" and parts[2] in _ONES:
            # "cuarenta y cinco días" → 45
            return _WORD_TO_INT[parts[0]] + _ONES[parts[2]]
        if parts[0] in _WORD_TO_INT:
            # "thirty days" → 30 / "treinta días" → 30 (tens word + non-numeric unit)
            # Only if the unit part is purely alphabetic (not another number word)
            if re.match(r"^[a-záéíóúñ]+$", parts[1]) and parts[1] not in _WORD_TO_INT:
                return _WORD_TO_INT[parts[0]]

    # --- Safety fallback: uncertain → return unchanged ---
    return v
