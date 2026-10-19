from __future__ import annotations

import re
from typing import Any


_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_ARITH_RE = re.compile(r"\b\d+(?:\.\d+)?\s*[-+*/%]\s*\d+(?:\.\d+)?\b")


# ---------------------------------------------------------------------------
# Keyword tables (per inference type, multilingual: EN + ES)
#
# Rules are substring-based and language-agnostic at match time; each table
# concatenates the cues for every supported language. Adding a language means
# extending these tuples — the classification logic below does not change.
# Short words that could match inside larger words are anchored with spaces.
# ---------------------------------------------------------------------------

_SEMANTIC_TERMS = (
    # EN
    "defined as", "shall mean", "means", "refers to", "definition",
    # ES
    "se define como", "significa", "se refiere a", "definición", "quiere decir",
)

_SYNTACTIC_PREDICATES = (
    "syntax", "grammar", "regex", "format", "schema", "json", "xml",
    "sintaxis", "formato", "esquema",
)

_HEURISTIC_TERMS = (
    # EN
    "rule of thumb", "roughly", "approximately", "quick estimate",
    # ES
    "regla general", "aproximadamente", "más o menos", "a ojo", "grosso modo",
)

_ABDUCTIVE_TERMS = (
    # EN
    "best explanation", "it seems", "probably because",
    # ES
    "la mejor explicación", "parece que", "parece", "probablemente porque",
)

_NARRATIVE_TERMS = (
    "story", "narrative", "plot", "retelling",
    "historia", "relato", "narrativa", "trama",
)

_TEMPORAL_PREDICATES = (
    "date", "deadline", "expiry", "duration", "days", "months", "years", "time",
    "fecha", "plazo", "vencimiento", "duración", "duracion", "días", "dias", "meses", "años", "anos",
)

_TEMPORAL_TERMS = (
    # EN — short prepositions are space-anchored so they only match whole words
    # (bare "to"/"from" used to mark any text containing them as temporal).
    "before", "after", "during", "until", "by ", " from ", " to ",
    "valid until", "expires",
    # ES
    "antes de", "después de", "despues de", "durante", "hasta el", "desde el",
    "vigente hasta", "válido hasta", "valido hasta", "válida hasta", "valida hasta",
    "vence el", "vencimiento",
)

_ARITHMETIC_PREDICATES = (
    "amount", "total", "sum", "count", "ratio", "percent", "percentage", "price", "cost",
    "importe", "suma", "cantidad", "porcentaje", "precio", "coste", "costo",
)

_AUTHORITY_TERMS = (
    # EN
    "according to", "certified by", "audited by", "official", "expert",
    # ES
    "según", "de acuerdo con", "certificado por", "auditado por", "oficial",
    "experto", "confirmó", "confirmado por", "confirma que",
)

_CAUSAL_TERMS = (
    # EN
    "because", "due to", "caused by", "leads to", "results in",
    # ES
    "porque", "debido a", "causado por", "provoca", "da lugar a", "conduce a",
)

_DEFAULT_TERMS = (
    # EN
    "by default", "unless otherwise", "otherwise specified", "assume",
    # ES
    "por defecto", "por omisión", "salvo que", "a menos que", "se asume",
)

_PROBABILISTIC_TERMS = (
    # EN
    "likely", "probability", "chance", "statistically", "distribution",
    # ES
    "probable", "probabilidad", "estadísticamente", "distribución", "distribucion",
)

_MULTI_HOP_CHAIN_TERMS = (
    # EN
    "therefore", "thus", "given that", "based on",
    # ES
    "por lo tanto", "por tanto", "así que", "asi que", "dado que", "con base en",
)

_MULTI_HOP_CONNECTORS = (
    " and ", " then ", " plus ", " combined with ",
    " y ", " entonces ", " más ", " mas ", " junto con ", " combinado con ",
)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _normalise_type_name(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def assign_inference_type(predicate: str, value: Any, claim_text: str = "") -> str:
    """
    Deterministically classify evidence into an inference type.

    Important:
    - This function is rule-based and deterministic (no LLM).
    - Cue tables cover English and Spanish; extend the tables above for more languages.
    - If no high-confidence rule matches, it falls back to "default".
    - It intentionally prefers conservative categories over overconfident ones.
    """
    p = _normalise_type_name(str(predicate))
    t = str(claim_text or "").strip().lower()
    v = str(value).strip().lower() if value is not None else ""
    merged = f"{p} {t} {v}"

    # 1) Very explicit, high-signal patterns first
    if _contains_any(merged, _SEMANTIC_TERMS):
        return "semantic"

    if _contains_any(p, _SYNTACTIC_PREDICATES):
        return "syntactic"

    # Explicit low-reliability markers should downgrade classification even if
    # a high-signal predicate name is present (e.g., "delivery_days roughly 30").
    if _contains_any(merged, _HEURISTIC_TERMS):
        return "heuristic"

    if _contains_any(merged, _ABDUCTIVE_TERMS):
        return "abductive"

    if _contains_any(merged, _NARRATIVE_TERMS):
        return "narrative"

    if (
        _contains_any(p, _TEMPORAL_PREDICATES)
        or _contains_any(merged, _TEMPORAL_TERMS)
        or _DATE_RE.search(merged) is not None
    ):
        return "temporal"

    if _ARITH_RE.search(merged) is not None or _contains_any(p, _ARITHMETIC_PREDICATES):
        return "arithmetic"

    # 2) Mid-signal deterministic patterns
    if _contains_any(merged, _AUTHORITY_TERMS):
        return "authority"

    if _contains_any(merged, _CAUSAL_TERMS):
        return "causal"

    if _contains_any(merged, _DEFAULT_TERMS):
        return "default"

    if _contains_any(merged, _PROBABILISTIC_TERMS):
        return "probabilistic"

    # Multi-hop requires explicit chaining language; this is intentionally strict.
    if _contains_any(merged, _MULTI_HOP_CHAIN_TERMS) and _contains_any(
        merged, _MULTI_HOP_CONNECTORS
    ):
        return "multi_hop"

    # Conservative fallback: do not escalate to a stronger type without clear evidence.
    return "default"
