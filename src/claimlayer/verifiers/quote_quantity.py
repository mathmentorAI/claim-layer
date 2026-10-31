"""Deterministic span, quantity, unit, and date grounding checks."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from claimlayer.models import Assertion, Issue, Policy, Source

_QUOTE_MAP = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "‘": "'",
        "’": "'",
        "–": "-",
        "—": "-",
        "\u00a0": " ",
    }
)

_WORD_NUMBERS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "hundred": 100,
    "cero": 0,
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "veinte": 20,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
    "cien": 100,
}

_SCALE_FACTORS: dict[str, float] = {
    "k": 1_000.0,
    "thousand": 1_000.0,
    "mil": 1_000.0,
    "m": 1_000_000.0,
    "mm": 1_000_000.0,
    "million": 1_000_000.0,
    "millions": 1_000_000.0,
    "millon": 1_000_000.0,
    "millón": 1_000_000.0,
    "millones": 1_000_000.0,
    "b": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
    "billion": 1_000_000_000.0,
    "billions": 1_000_000_000.0,
}

_UNIT_ALIASES: dict[str, str] = {
    "$": "USD",
    "us$": "USD",
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
    "%": "PERCENT",
    "percent": "PERCENT",
    "pct": "PERCENT",
    "bps": "BPS",
    "day": "DAYS",
    "days": "DAYS",
    "día": "DAYS",
    "días": "DAYS",
    "dia": "DAYS",
    "dias": "DAYS",
    "month": "MONTHS",
    "months": "MONTHS",
    "mes": "MONTHS",
    "meses": "MONTHS",
    "year": "YEARS",
    "years": "YEARS",
    "año": "YEARS",
    "años": "YEARS",
    "ano": "YEARS",
    "anos": "YEARS",
    "hour": "HOURS",
    "hours": "HOURS",
    "hora": "HOURS",
    "horas": "HOURS",
    "hr": "HOURS",
    "hrs": "HOURS",
    "x": "MULTIPLIER",
    "times": "MULTIPLIER",
}

_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

_NUMERIC_QUANTITY_RE = re.compile(
    r"\(?(?P<prefix>US\$|\$|€|£)?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,3}(?:\.\d{3})+,\d+|\d+(?:\.\d+)?)\)?"
    r"(?:\s*(?P<scale>billion|billions|bn|million|millions|millones|millón|millon|thousand|mil|mm|k|m|b)\b)?\)?"
    r"(?:\s*(?:\([a-zA-Z0-9]+\)\s*)?(?:business\s+|calendar\s+|naturales\s+|h[aá]biles\s+)?"
    r"(?P<suffix>%|bps|percent|pct|usd|dollars?|eur|euros?|gbp|pounds?|days?|d[ií]as?|months?|mes(?:es)?|years?|a[ñn]os?|hours?|horas?|hrs?|hr|x|times))?",
    re.IGNORECASE,
)

_WORD_QUANTITY_RE = re.compile(
    r"\b(?P<word>"
    + "|".join(sorted(_WORD_NUMBERS.keys(), key=len, reverse=True))
    + r")\b"
    r"(?:\s*\(\d+\))?"
    r"(?:\s+(?:business|calendar|naturales|h[aá]biles))?"
    r"\s+(?P<unit>days?|d[ií]as?|months?|mes(?:es)?|years?|a[ñn]os?|hours?|horas?|percent|%|usd|dollars?|eur|euros?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedQuantity:
    magnitude: float
    unit: str  # "NONE" if dimensionless

    def matches(self, other: ParsedQuantity, rel_tol: float = 1e-6) -> bool:
        if not math.isclose(self.magnitude, other.magnitude, rel_tol=rel_tol, abs_tol=1e-6):
            return False
        if self.unit == "NONE":
            return True
        return self.unit == other.unit

    def same_magnitude_wrong_unit(self, other: ParsedQuantity) -> bool:
        return (
            math.isclose(self.magnitude, other.magnitude, rel_tol=1e-6, abs_tol=1e-6)
            and self.unit != "NONE"
            and other.unit != "NONE"
            and self.unit != other.unit
        )


def normalize_span(text: str) -> str:
    """Normalize punctuation variants and collapse whitespace for deterministic quote checks."""
    translated = (text or "").translate(_QUOTE_MAP)
    return re.sub(r"\s+", " ", translated).strip()


def canonicalize_unit(raw_unit: str | None) -> str:
    if not raw_unit:
        return "NONE"
    cleaned = raw_unit.strip().lower()
    return _UNIT_ALIASES.get(cleaned, cleaned.upper())


def _parse_float_token(raw_num: str) -> float:
    if "," in raw_num and "." in raw_num:
        if raw_num.rfind(",") > raw_num.rfind("."):
            # European decimal format: 1.250,50
            return float(raw_num.replace(".", "").replace(",", "."))
        # Standard format: 1,250.50
        return float(raw_num.replace(",", ""))
    if "," in raw_num:
        parts = raw_num.split(",")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            return float(raw_num.replace(",", ""))
        return float(raw_num.replace(",", "."))
    return float(raw_num)


def extract_dates(text: str) -> list[str]:
    return _ISO_DATE_RE.findall(text or "")


def extract_quantities(text: str, explicit_unit: str | None = None) -> list[ParsedQuantity]:
    """Extract normalized (magnitude, unit) quantities from text, excluding ISO dates."""
    if not text:
        return []
    scrubbed = _ISO_DATE_RE.sub(" ", text.translate(_QUOTE_MAP))
    default_unit = canonicalize_unit(explicit_unit)
    results: list[ParsedQuantity] = []

    for m in _NUMERIC_QUANTITY_RE.finditer(scrubbed):
        raw_num = m.group("num")
        prefix = m.group("prefix")
        scale = m.group("scale")
        suffix = m.group("suffix")

        # Note: if suffix was Absent and 'm'/'k'/'b' was actually currency/unit check
        magnitude = _parse_float_token(raw_num)
        if scale:
            magnitude *= _SCALE_FACTORS.get(scale.lower(), 1.0)

        unit = "NONE"
        if prefix:
            unit = canonicalize_unit(prefix)
        if suffix:
            suffix_unit = canonicalize_unit(suffix)
            if unit == "NONE":
                unit = suffix_unit
        if unit == "NONE" and default_unit != "NONE":
            unit = default_unit

        results.append(ParsedQuantity(magnitude=round(magnitude, 6), unit=unit))

    for m in _WORD_QUANTITY_RE.finditer(scrubbed):
        word_val = float(_WORD_NUMBERS[m.group("word").lower()])
        unit = canonicalize_unit(m.group("unit"))
        cand = ParsedQuantity(magnitude=word_val, unit=unit)
        if not any(existing.matches(cand) and existing.unit == cand.unit for existing in results):
            results.append(cand)

    return results


def canonicalize_value(value: str, explicit_unit: str | None = None) -> str:
    """Produce a deterministic canonical key for value comparison across sources."""
    dates = extract_dates(value)
    if dates and len(normalize_span(value)) == 10:
        return f"DATE:{dates[0]}"

    quantities = extract_quantities(value, explicit_unit=explicit_unit)
    if len(quantities) == 1:
        q = quantities[0]
        mag = int(q.magnitude) if q.magnitude.is_integer() else round(q.magnitude, 6)
        return f"QTY:{mag}:{q.unit}"

    return f"STR:{normalize_span(value).lower()}"


def verify_quote_and_quantities(
    assertion: Assertion,
    source: Source | None,
    policy: Policy,
) -> list[Issue]:
    """Verify that the source exists, the quote is grounded, and all numbers/dates/units match."""
    issues: list[Issue] = []

    if source is None:
        issues.append(
            Issue(
                code="SOURCE_NOT_FOUND",
                disposition="RETRY",
                assertion_id=assertion.id,
                subject=assertion.subject,
                predicate=assertion.predicate,
                message=f"Assertion '{assertion.id}' cites unknown source_id '{assertion.source_id}'.",
                remediation=(
                    f"Cite a valid source_id registered in the ledger instead of '{assertion.source_id}'."
                ),
            )
        )
        return issues

    norm_quote = normalize_span(assertion.quote)
    norm_source = normalize_span(source.text)

    if policy.require_exact_quote:
        if not norm_quote:
            issues.append(
                Issue(
                    code="EMPTY_QUOTE",
                    disposition="RETRY",
                    assertion_id=assertion.id,
                    subject=assertion.subject,
                    predicate=assertion.predicate,
                    message=f"Assertion '{assertion.id}' provided an empty citation quote.",
                    remediation=f"Provide an exact verbatim quote from source '{source.id}'.",
                )
            )
            return issues

        if norm_quote not in norm_source and norm_quote.lower() not in norm_source.lower():
            issues.append(
                Issue(
                    code="QUOTE_NOT_IN_SOURCE",
                    disposition="RETRY",
                    assertion_id=assertion.id,
                    subject=assertion.subject,
                    predicate=assertion.predicate,
                    message=(
                        f"Quote '{assertion.quote[:80]}' does not appear in source '{source.id}'."
                    ),
                    remediation=(
                        f"Extract an exact verbatim substring from '{source.id}' or remove ungrounded claim."
                    ),
                )
            )
            return issues

    if policy.require_quantity_match:
        # 1. Check ISO dates in value against quote/source
        val_dates = extract_dates(assertion.value)
        quote_dates = set(extract_dates(assertion.quote)) | set(extract_dates(source.text))
        for d in val_dates:
            if d not in quote_dates:
                issues.append(
                    Issue(
                        code="DATE_MISMATCH",
                        disposition="RETRY",
                        assertion_id=assertion.id,
                        subject=assertion.subject,
                        predicate=assertion.predicate,
                        message=(
                            f"Date '{d}' in proposed value '{assertion.value}' is absent from cited quote."
                        ),
                        remediation=f"Align date in '{assertion.predicate}' with the exact date in '{source.id}'.",
                    )
                )

        # 2. Check numeric quantities & units in value against quote
        val_quantities = extract_quantities(assertion.value, explicit_unit=assertion.unit)
        quote_quantities = extract_quantities(assertion.quote)
        if not quote_quantities:
            quote_quantities = extract_quantities(source.text)

        for vq in val_quantities:
            exact_match = any(
                vq.matches(qq) and not vq.same_magnitude_wrong_unit(qq)
                for qq in quote_quantities
            )
            if exact_match:
                continue

            unit_clash = next((qq for qq in quote_quantities if vq.same_magnitude_wrong_unit(qq)), None)
            if unit_clash is not None:
                issues.append(
                    Issue(
                        code="UNIT_MISMATCH",
                        disposition="RETRY",
                        assertion_id=assertion.id,
                        subject=assertion.subject,
                        predicate=assertion.predicate,
                        message=(
                            f"Unit mismatch for '{assertion.predicate}': proposed {vq.magnitude:g} {vq.unit}, "
                            f"but source '{source.id}' states {unit_clash.magnitude:g} {unit_clash.unit}."
                        ),
                        remediation=(
                            f"Correct the unit of '{assertion.predicate}' to '{unit_clash.unit}' as stated in '{source.id}'."
                        ),
                    )
                )
            else:
                issues.append(
                    Issue(
                        code="QUANTITY_MISMATCH",
                        disposition="RETRY",
                        assertion_id=assertion.id,
                        subject=assertion.subject,
                        predicate=assertion.predicate,
                        message=(
                            f"Quantity {vq.magnitude:g} ({vq.unit}) in proposed value '{assertion.value}' "
                            f"is not grounded in cited quote '{assertion.quote[:80]}'."
                        ),
                        remediation=(
                            f"Use the exact figure supported by '{source.id}' without rounding or hallucinating."
                        ),
                    )
                )

    return issues
