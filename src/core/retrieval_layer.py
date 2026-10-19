from __future__ import annotations

from typing import List

from .interfaces import Claim, ClaimLayer
from .query_layer import QueryCandidate
from .graph_traverser import DependencyGraph


class RetrievalLayer:
    def __init__(self, claim_layer: ClaimLayer):
        self.claim_layer = claim_layer
        self.unknown_entity_count: int = 0    # cumulative unknown-entity claims
        self.total_claims_seen: int = 0       # cumulative all claims seen
        self.last_unknown_ratio: float = 0.0  # ratio from the most recent retrieve() call
        self.global_unknown_ratio: float = 0.0  # ratio across all retrieve() calls

    def retrieve_multihop(self, entity: str, predicate: str, max_hops: int = 3) -> List[Claim]:
        """
        Traverse the Epistemic Dependency Graph to resolve k-hop entity chains.
        """
        all_claims: List[Claim] = []
        if hasattr(self.claim_layer, "get_all"):
            all_claims = self.claim_layer.get_all()
        elif hasattr(self.claim_layer, "claims"):
            all_claims = list(getattr(self.claim_layer, "claims", []))
        elif hasattr(self.claim_layer, "get_by_entity"):
            all_claims = self.claim_layer.get_by_entity(entity)

        graph = DependencyGraph(all_claims)
        paths = graph.find_paths(entity, predicate, max_hops=max_hops)
        if paths:
            return paths[0].supporting_claims
        return []

    def retrieve(self, candidates: List[QueryCandidate]) -> List[Claim]:
        """
        Return claims relevant to *candidates*, sorted by candidate score DESC.

        Rules:
          - All candidates must share the same entity (guaranteed by QueryLayer).
          - Claims with entity=None are skipped and counted in unknown_entity_count.
          - A claim is included only if its predicate appears in at least one
            candidate — no implicit entity-only partial matches.
          - When multiple candidates map to the same claim predicate, the
            highest candidate score is used for ordering.
          - If direct 1-hop matching yields no claims, falls back to multi-hop
            graph traversal over the DependencyGraph.
        """
        if not candidates:
            return []

        entity = candidates[0].entity

        # Max score per predicate (multiple candidates may share a predicate)
        candidate_scores: dict[str, float] = {}
        for c in candidates:
            if c.score > candidate_scores.get(c.predicate, 0.0):
                candidate_scores[c.predicate] = c.score

        all_claims = self.claim_layer.get_by_entity(entity)

        total_seen = 0
        unknown = 0
        scored = []
        for claim in all_claims:
            total_seen += 1
            if claim.entity is None:
                unknown += 1
                self.unknown_entity_count += 1
                continue
            if claim.predicate in candidate_scores:
                scored.append((claim, candidate_scores[claim.predicate]))

        self.total_claims_seen += total_seen
        self.last_unknown_ratio = unknown / total_seen if total_seen else 0.0
        self.global_unknown_ratio = (
            self.unknown_entity_count / self.total_claims_seen
            if self.total_claims_seen else 0.0
        )

        scored.sort(key=lambda x: x[1], reverse=True)
        direct_claims = [claim for claim, _ in scored]
        if direct_claims:
            return direct_claims

        # Multi-hop fallback: check if predicate can be reached via dependency graph
        for c in candidates:
            multihop_claims = self.retrieve_multihop(entity, c.predicate)
            if multihop_claims:
                return multihop_claims

        return []
