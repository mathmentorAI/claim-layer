from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple
from core.claim_extractor import ExtractedClaim
from core.interfaces import INFERENCE_WEIGHTS


_BOILERPLATE_ENTITIES = {
    "page", "document", "header", "footer", "section", "table", "null",
    "none", "n/a", "pagina", "página", "documento", "pie de pagina",
}

_PREDICATE_ALIASES = {
    "has_payment_days": "payment_days",
    "plazo_pago": "payment_days",
    "dias_pago": "payment_days",
    "delito_imputado": "delito",
    "crimen": "delito",
    "acusado_de": "delito",
    "cuantia": "amount",
    "cuantía": "amount",
    "importe": "amount",
    "importe_reclamado": "amount",
    "monto": "amount",
    "total_debt": "amount",
}


def _normalize_str(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s).strip().lower())


class ClaimConsolidator:
    """
    Consolidates and prunes candidate extracted claims before ingestion.
    Resolves the precision drop and over-extraction observed in benchmarks
    (pruning 400+ noisy candidate fragments to ~120-150 high-value claims).
    """

    def __init__(self, max_claims: int = 150) -> None:
        self.max_claims = max_claims

    def _is_noise(self, claim: ExtractedClaim) -> bool:
        entity_norm = _normalize_str(claim.entity)
        val_norm = _normalize_str(claim.value)
        quote_norm = _normalize_str(claim.quote)
        pred_norm = _normalize_str(claim.predicate)

        # Drop empty or single-character entities
        if not entity_norm or len(entity_norm) < 2:
            return True

        # Drop boilerplate entities (exact match or prefix like "page 1", "pagina 3")
        if any(entity_norm == b or entity_norm.startswith(b + " ") for b in _BOILERPLATE_ENTITIES):
            return True

        # Drop layout predicates
        if pred_norm in {"header", "footer", "page", "section", "table", "pie de pagina"}:
            return True

        # Drop empty values or trivial placeholders
        if not val_norm or (val_norm in {"null", "none", "n/a", "?", "true", "false"} and len(quote_norm) < 10):
            return True

        # Drop claims with no grounding quote
        if not quote_norm or len(quote_norm) < 4:
            return True

        return False

    def _canonicalize_predicate(self, predicate: str, canonical_override: Optional[str] = None) -> str:
        if canonical_override and canonical_override.strip():
            try:
                from claim_layer.semantic.normalization import register_predicate_alias
                return register_predicate_alias(predicate, canonical_override)
            except Exception:
                return canonical_override.strip().lower()
        try:
            from claim_layer.semantic.normalization import normalize_predicate_name
            reg = normalize_predicate_name(predicate)
            if reg != predicate.strip().lower():
                return reg
        except Exception:
            pass
        norm = _normalize_str(predicate)
        return _PREDICATE_ALIASES.get(norm, predicate.strip())

    def _are_subsumed(self, val_a: str, val_b: str) -> Optional[str]:
        """
        If one value is a substring/subsumption of another, return the more specific one.
        e.g. ('estafa', 'estafa continuada') -> 'estafa continuada'
        ('30', '30 days') -> '30 days'
        """
        a_norm = _normalize_str(val_a)
        b_norm = _normalize_str(val_b)
        if a_norm == b_norm:
            return val_a

        if a_norm in b_norm and len(b_norm) - len(a_norm) < 25:
            return val_b
        if b_norm in a_norm and len(a_norm) - len(b_norm) < 25:
            return val_a
        return None

    def _extract_quantities(self, text: str) -> Set[str]:
        if not text:
            return set()
        return set(re.findall(r"\b\d+(?:[.,]\d+)*\b", text))

    def _can_subsume(self, a: ExtractedClaim, b: ExtractedClaim) -> Optional[str]:
        """
        Check if two claims can be subsumed semantically without dropping distinct facts.
        Requires:
        1. Lexical subsumption between values.
        2. Contextual alignment (same paragraph/page coordinates if both present).
        3. No conflicting temporal anchors (valid_from/valid_until).
        4. No conflicting distinct quantities in values or quotes.
        """
        preferred_val = self._are_subsumed(a.value, b.value)
        if preferred_val is None:
            return None

        # Check paragraph/chunk provenance
        p_a = a.paragraph_id.strip() if a.paragraph_id else ""
        p_b = b.paragraph_id.strip() if b.paragraph_id else ""
        if p_a and p_b and p_a != p_b:
            # Different paragraphs/sections: distinct occurrences, do not merge
            return None

        # Check page coordinates
        if a.page_number and b.page_number and a.page_number != b.page_number:
            return None

        # Check temporal anchors
        if a.valid_from and b.valid_from and a.valid_from != b.valid_from:
            return None
        if a.valid_until and b.valid_until and a.valid_until != b.valid_until:
            return None

        # Check quantitative anchors: if both mention explicit different amounts
        q_a = self._extract_quantities(f"{a.value} {a.quote}")
        q_b = self._extract_quantities(f"{b.value} {b.quote}")
        if q_a and q_b and not (q_a & q_b):
            # Non-overlapping quantities (e.g. 10.000 vs 45.000): distinct charges, do not merge
            return None

        return preferred_val

    def consolidate(
        self,
        claims: List[ExtractedClaim],
        max_output_claims: Optional[int] = None,
    ) -> List[ExtractedClaim]:
        """
        Deduplicate, merge subsumed variants, and prune low-information claims.
        """
        target_max = max_output_claims or self.max_claims

        # Step 1: Filter noise
        valid_claims = [c for c in claims if not self._is_noise(c)]

        # Step 2: Group by (canonical_entity, canonical_predicate) for subsumption merging
        buckets: Dict[Tuple[str, str], List[ExtractedClaim]] = {}
        for c in valid_claims:
            can_pred = getattr(c, "canonical_predicate", None)
            c.predicate = self._canonicalize_predicate(c.predicate, canonical_override=can_pred)
            can_ent = getattr(c, "canonical_entity", None)
            if can_ent and c.entity:
                try:
                    from claim_layer.semantic.normalization import register_entity_alias
                    register_entity_alias(c.entity, can_ent)
                except Exception:
                    pass
            ent_key = _normalize_str(can_ent or c.entity)
            key = (ent_key, _normalize_str(c.predicate))
            buckets.setdefault(key, []).append(c)

        consolidated: List[ExtractedClaim] = []

        for (ent_key, pred_key), group in buckets.items():
            merged_for_bucket: List[ExtractedClaim] = []
            for claim in group:
                merged = False
                for idx, existing in enumerate(merged_for_bucket):
                    preferred_val = self._can_subsume(existing, claim)
                    if preferred_val is not None:
                        # Subsumed variant within same context: merge into the more specific claim
                        # Keep best quote and highest confidence, and retain underlying instances
                        best_conf = max(existing.confidence, claim.confidence)
                        best_quote = existing.quote if len(existing.quote) >= len(claim.quote) else claim.quote
                        existing.value = preferred_val
                        existing.confidence = best_conf
                        existing.quote = best_quote
                        if getattr(existing, "canonical_value", None) is None and getattr(claim, "canonical_value", None) is not None:
                            existing.canonical_value = claim.canonical_value
                        if not getattr(existing, "instances", None):
                            import copy
                            base_snapshot = copy.copy(existing)
                            base_snapshot.instances = []
                            existing.instances = [base_snapshot]
                        claim_snapshot = claim
                        if getattr(claim_snapshot, "instances", None):
                            import copy
                            claim_snapshot = copy.copy(claim)
                            claim_snapshot.instances = []
                        existing.instances.append(claim_snapshot)
                        merged = True
                        break
                if not merged:
                    merged_for_bucket.append(claim)

            consolidated.extend(merged_for_bucket)

        # Step 3: Information Density Ranking if still exceeding target_max
        if len(consolidated) > target_max:
            def quality_score(c: ExtractedClaim) -> float:
                weight = INFERENCE_WEIGHTS.get(c.inference_type, 0.5)
                quote_len_bonus = min(len(c.quote or ""), 150) / 150.0 * 0.2
                # Boost claims with explicit amounts, dates or formal types
                type_boost = 0.2 if c.claim_type in {"obligation", "prohibition", "condition"} else 0.0
                return c.confidence * weight + quote_len_bonus + type_boost

            consolidated.sort(key=quality_score, reverse=True)
            consolidated = consolidated[:target_max]

        return consolidated
