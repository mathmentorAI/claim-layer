from typing import Optional
import re
from core.interfaces import Reason, Result
from core.grounding_protocol import apply_grounding_protocol
from core.aggregation_engine import AggregationEngine
from core.query_layer import _extract_entity, QueryCandidate


class DeltoryxEngine:
    def __init__(self, claim_layer, query_layer, retrieval_layer, aggregation_engine: Optional[AggregationEngine] = None):
        self.claim_layer = claim_layer
        self.query_layer = query_layer
        self.retrieval_layer = retrieval_layer
        self.aggregation_engine = aggregation_engine or AggregationEngine()

    def ask(self, text: str, protocol_id: Optional[str] = None) -> Result:
        # Detect if question asks for an aggregation (count, sum, list, average)
        agg_intent = self.aggregation_engine.detect_intent(text)

        # Zero-Config: discover known entities & predicates from ledger if available
        ledger_claims = []
        if hasattr(self.claim_layer, "get_all"):
            try:
                res = self.claim_layer.get_all()
                if isinstance(res, list):
                    ledger_claims = res
            except Exception:
                pass
        elif hasattr(self.claim_layer, "claims"):
            raw_c = getattr(self.claim_layer, "claims", [])
            if isinstance(raw_c, list):
                ledger_claims = list(raw_c)

        known_ents = [c.entity for c in ledger_claims if getattr(c, "entity", None)]
        known_preds = [c.predicate for c in ledger_claims if getattr(c, "predicate", None)]

        # parse() raises ValueError if entity cannot be extracted — propagate as-is
        try:
            candidates = self.query_layer.parse(
                text,
                known_entities=known_ents or None,
                known_predicates=known_preds or None,
            )
        except TypeError:
            candidates = self.query_layer.parse(text)

        if not candidates:
            extracted_entity = _extract_entity(text)
            # Dynamic open-domain predicate matching against ledger claims for this entity
            if extracted_entity and hasattr(self.claim_layer, "get_by_entity"):
                entity_claims = self.claim_layer.get_by_entity(extracted_entity)
                if isinstance(entity_claims, list) and entity_claims:
                    q_tokens = set(re.findall(r"\w+", text.lower()))
                    dynamic_preds: dict[str, float] = {}
                    for c in entity_claims:
                        pred_str = getattr(c, "predicate", "") or ""
                        p_tokens = set(re.findall(r"\w+", pred_str.lower()))
                        if p_tokens and (q_tokens & p_tokens):
                            overlap = len(q_tokens & p_tokens) / max(len(p_tokens), 1)
                            dynamic_preds[pred_str] = max(dynamic_preds.get(pred_str, 0.0), round(0.75 + 0.25 * overlap, 4))
                    if dynamic_preds:
                        candidates = sorted(
                            [QueryCandidate(entity=extracted_entity, predicate=p, score=s) for p, s in dynamic_preds.items()],
                            key=lambda x: x.score,
                            reverse=True,
                        )

        if not candidates:
            # If aggregation intent was detected, attempt to retrieve claims for entity directly
            extracted_entity = _extract_entity(text)
            if agg_intent and extracted_entity:
                claims = self.claim_layer.get_by_entity(extracted_entity)
                if claims:
                    return self.aggregation_engine.aggregate(claims, agg_intent)

            return Result(
                value=None,
                confidence=0.0,
                contradictions=[],
                supporting_claims=[],
                reason=Reason.NO_PREDICATE_MATCH,
            )

        # If no direct claims exist for candidate predicates on entity, check multihop resolution
        candidate_preds = {c.predicate for c in candidates}
        direct_claims = [
            c for c in self.claim_layer.get_by_entity(candidates[0].entity)
            if c.predicate in candidate_preds
        ]

        if not direct_claims:
            from core.graph_traverser import DependencyGraph
            all_claims = []
            if hasattr(self.claim_layer, "get_all"):
                all_claims = self.claim_layer.get_all()
            elif hasattr(self.claim_layer, "claims"):
                all_claims = list(getattr(self.claim_layer, "claims", []))
            elif hasattr(self.claim_layer, "get_by_entity"):
                all_claims = self.claim_layer.get_by_entity(candidates[0].entity)

            graph = DependencyGraph(all_claims)
            for cand in candidates:
                multihop_res = graph.resolve_multihop(candidates[0].entity, cand.predicate)
                if multihop_res:
                    return apply_grounding_protocol(multihop_res)

        claims = self.retrieval_layer.retrieve(candidates)

        if not claims:
            return Result(
                value=None,
                confidence=0.0,
                contradictions=[],
                supporting_claims=[],
                reason=Reason.NO_EVIDENCE_FOUND,
            )

        if agg_intent:
            return self.aggregation_engine.aggregate(claims, agg_intent)

        resolved = self.claim_layer.resolve(claims)
        return apply_grounding_protocol(resolved)
