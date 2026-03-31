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

# Written English number words → integer (single words only, 1–99)
_WORD_TO_INT: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

# Two-word written numbers: "twenty one" … "ninety nine"
_TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}
_ONES = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}

# Matches a bare integer at the start of the string, optionally followed by text
# e.g. "30", "30 days", "30-day period"
_LEADING_INT = re.compile(r"^\s*(\d+)(?:\s|$|-)")

# Full string is just an integer (no units)
_BARE_INT = re.compile(r"^\s*(\d+)\s*$")


def normalize_value(value: str) -> int | str:
    """Return the canonical form of *value*, or *value* itself if uncertain.

    Deterministic. No side effects. Never raises.
    """
    if not isinstance(value, str):
        return value

    v = value.strip()

    # --- Case A: bare integer or leading integer before a unit/separator ---
    m = _BARE_INT.match(v)
    if m:
        return int(m.group(1))

    m = _LEADING_INT.match(v)
    if m:
        return int(m.group(1))

    # --- Case B: written English number (single word) ---
    lower = v.lower()
    if lower in _WORD_TO_INT:
        return _WORD_TO_INT[lower]

    # --- Case B2: two-word written number ("thirty days", "forty five") ---
    parts = lower.split()
    if len(parts) >= 2 and parts[0] in _TENS:
        if parts[1] in _ONES:
            # "forty five" → 45, "forty five days" → 45
            return _WORD_TO_INT[parts[0]] + _ONES[parts[1]]
        if parts[0] in _WORD_TO_INT:
            # "thirty days" → 30  (tens word + non-numeric unit)
            # Only if the unit part is purely alphabetic (not another number word)
            if re.match(r"^[a-z]+$", parts[1]) and parts[1] not in _WORD_TO_INT:
                return _WORD_TO_INT[parts[0]]

    # --- Safety fallback: uncertain → return unchanged ---
    return v
