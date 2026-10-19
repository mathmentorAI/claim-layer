from __future__ import annotations

import re
from enum import Enum
from typing import Any, Optional
from core.interfaces import Claim


class OriginTier(str, Enum):
    PRIMARY_DOCUMENT = "primary_document"
    ANNEX = "annex"
    SECONDARY_ANNEX = "annex"
    EXTERNAL_INJECTED = "external_injected"


_ORIGIN_RANKS = {
    OriginTier.PRIMARY_DOCUMENT: 100,
    OriginTier.ANNEX: 50,
    OriginTier.EXTERNAL_INJECTED: 10,
}

_INJECTED_CUES = re.compile(
    r"(?:^|[\W_])(injected|inyectad[oa]|nota_interna|internal_note|nota_externa|external|extern[oa]|mock|synthetic|sintetic[oa]|override)(?:$|[\W_])",
    re.IGNORECASE,
)
_ANNEX_CUES = re.compile(
    r"(?:^|[\W_])(anexo|annex|addenda|appendix|apendice|apéndice|peritaje|suplemento)(?:$|[\W_])",
    re.IGNORECASE,
)


def get_origin_tier(claim: Claim) -> OriginTier:
    """
    Determine the authority tier of a claim based on its explicit metadata
    or its source document coordinates.
    """
    # 1. Inspect document_id for structural cues
    doc_id = claim.source.document_id if claim.source else ""
    if doc_id:
        if _INJECTED_CUES.search(doc_id):
            return OriginTier.EXTERNAL_INJECTED
        if _ANNEX_CUES.search(doc_id):
            return OriginTier.ANNEX

    # 2. Explicit claim-level or source-level tier attribute
    explicit = getattr(claim, "origin_tier", None)
    if not explicit and claim.source:
        explicit = getattr(claim.source, "origin_tier", None)

    if isinstance(explicit, OriginTier):
        return explicit

    if explicit:
        norm = str(explicit).strip().lower()
        if "." in norm:
            norm = norm.split(".")[-1]
        if norm in {"annex", "secondary", "secondary_annex", "anexo"}:
            return OriginTier.ANNEX
        if norm in {"external_injected", "injected", "internal_note", "external", "nota_externa"}:
            return OriginTier.EXTERNAL_INJECTED
        if norm in {"primary_document", "primary", "documental_base", "base"}:
            return OriginTier.PRIMARY_DOCUMENT

    return OriginTier.PRIMARY_DOCUMENT


def get_origin_rank(claim: Claim) -> int:
    """Return integer precedence rank (higher = greater authority)."""
    tier = get_origin_tier(claim)
    return _ORIGIN_RANKS.get(tier, 100)
