"""Deterministic verification modules for ClaimLayer."""

from claimlayer.verifiers.conflict import evaluate_conflicts_and_thresholds
from claimlayer.verifiers.coverage import verify_coverage
from claimlayer.verifiers.diff import (
    SectionDivergence,
    build_comparison_policy,
    extract_divergent_sections,
)
from claimlayer.verifiers.precedence import is_source_active, verify_precedence_and_validity
from claimlayer.verifiers.quote_quantity import (
    canonicalize_unit,
    canonicalize_value,
    extract_dates,
    extract_quantities,
    normalize_span,
    verify_quote_and_quantities,
)

__all__ = [
    "canonicalize_unit",
    "canonicalize_value",
    "evaluate_conflicts_and_thresholds",
    "extract_dates",
    "extract_quantities",
    "is_source_active",
    "normalize_span",
    "verify_coverage",
    "verify_precedence_and_validity",
    "verify_quote_and_quantities",
]
