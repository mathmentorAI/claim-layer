"""Deterministic section-level divergence detector for multi-document audits.

Discovers sections where a secondary document (e.g., Offering Memorandum or Counterparty Markup)
diverges quantitatively or structurally from an authoritative baseline (e.g., Indenture or MSA),
automatically generating completeness predicates for Policy.required_predicates.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from claimlayer.models import Policy, Source, normalize_key
from claimlayer.verifiers.quote_quantity import extract_dates, extract_quantities

_SECTION_HEADER_RE = re.compile(
    r"(?m)^(?:#{1,4}\s*)?"
    r"(?P<sec_id>(?:Section|Article|Clause|Term|Item|Schedule)\s+\d+(?:\.\d+)*)"
    r"(?:\s*[:.\-—]\s*(?P<title>[^\n]+))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SectionDivergence:
    """A deterministic discrepancy detected between an authoritative and secondary section."""

    section_key: str
    section_label: str
    primary_source_id: str
    secondary_source_id: str
    primary_quantities: tuple[str, ...]
    secondary_quantities: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _split_into_sections(text: str) -> dict[str, tuple[str, str]]:
    """Map normalized section_key -> (display_label, body_text)."""
    matches = list(_SECTION_HEADER_RE.finditer(text or ""))
    if not matches:
        return {}

    sections: dict[str, tuple[str, str]] = {}
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sec_id = re.sub(r"\s+", " ", match.group("sec_id").strip())
        title = (match.group("title") or "").strip().rstrip(".")
        label = f"{sec_id}: {title}" if title else sec_id
        key = normalize_key(sec_id)
        body = text[start:end].strip()
        sections[key] = (label, body)
    return sections


def _quantity_tokens(body: str) -> set[str]:
    tokens: set[str] = set()
    for q in extract_quantities(body):
        # Ignore bare section numbers by keeping unit-bearing quantities or large numbers
        if q.unit != "NONE" or q.magnitude >= 100:
            mag = int(q.magnitude) if q.magnitude.is_integer() else round(q.magnitude, 4)
            tokens.add(f"{mag}:{q.unit}")
    for d in extract_dates(body):
        tokens.add(f"DATE:{d}")
    return tokens


def extract_divergent_sections(
    primary: Source,
    secondary: Source,
) -> list[SectionDivergence]:
    """Identify sections where *secondary* diverges quantitatively or omits *primary* provisions."""
    prim_secs = _split_into_sections(primary.text)
    sec_secs = _split_into_sections(secondary.text)
    divergences: list[SectionDivergence] = []

    for key in sorted(prim_secs.keys()):
        p_label, p_body = prim_secs[key]
        p_quants = _quantity_tokens(p_body)

        if key not in sec_secs:
            divergences.append(
                SectionDivergence(
                    section_key=key,
                    section_label=p_label,
                    primary_source_id=primary.id,
                    secondary_source_id=secondary.id,
                    primary_quantities=tuple(sorted(p_quants)),
                    secondary_quantities=(),
                    reason=f"Section '{p_label}' present in '{primary.id}' is missing from '{secondary.id}'.",
                )
            )
            continue

        _, s_body = sec_secs[key]
        s_quants = _quantity_tokens(s_body)
        if p_quants != s_quants:
            divergences.append(
                SectionDivergence(
                    section_key=key,
                    section_label=p_label,
                    primary_source_id=primary.id,
                    secondary_source_id=secondary.id,
                    primary_quantities=tuple(sorted(p_quants)),
                    secondary_quantities=tuple(sorted(s_quants)),
                    reason=(
                        f"Quantitative divergence in '{p_label}': "
                        f"{primary.id}={sorted(p_quants)} vs {secondary.id}={sorted(s_quants)}."
                    ),
                )
            )
        elif normalize_key(p_body) != normalize_key(s_body):
            divergences.append(
                SectionDivergence(
                    section_key=key,
                    section_label=p_label,
                    primary_source_id=primary.id,
                    secondary_source_id=secondary.id,
                    primary_quantities=tuple(sorted(p_quants)),
                    secondary_quantities=tuple(sorted(s_quants)),
                    reason=f"Textual/structural divergence in '{p_label}' between '{primary.id}' and '{secondary.id}'.",
                )
            )

    return divergences


def build_comparison_policy(
    primary: Source,
    secondary: Source,
    *,
    policy_id: str = "document_comparison",
    min_tier_rank: int | None = None,
) -> tuple[Policy, list[SectionDivergence]]:
    """Build a deterministic Policy requiring the agent to audit every divergent section
    and ground governing values in the higher-authority primary instrument."""
    divergences = extract_divergent_sections(primary, secondary)
    required_preds = [d.section_key for d in divergences]
    effective_min_rank = min_tier_rank if min_tier_rank is not None else primary.rank
    policy = Policy(
        policy_id=policy_id,
        min_tier_rank=effective_min_rank,
        required_predicates=required_preds,
        required_source_ids=[primary.id],
    )
    return policy, divergences
