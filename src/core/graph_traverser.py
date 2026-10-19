from __future__ import annotations

import heapq
import itertools
import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from core.epistemic_certificate import (
    compute_subjective_opinion,
    generate_epistemic_certificate,
)
from core.interfaces import Claim, INFERENCE_WEIGHTS, Reason, Result


def _noisy_or(confidences: List[float]) -> float:
    """Parallel semiring operator (⊕): monotonic fusion of independent paths."""
    prod = 1.0
    for c in confidences:
        prod *= 1.0 - max(0.0, min(1.0, float(c)))
    return round(1.0 - prod, 4)


@dataclass
class MultihopStep:
    from_entity: str
    predicate: str
    to_value: Any
    claim: Claim


@dataclass
class MultihopPath:
    steps: List[MultihopStep]
    final_value: Any
    confidence: float

    @property
    def supporting_claims(self) -> List[Claim]:
        return [s.claim for s in self.steps]

    @property
    def explanation(self) -> str:
        chain = " -> ".join(
            f"({s.from_entity})--[{s.predicate}]-->({s.to_value})" for s in self.steps
        )
        return f"{chain} => {self.final_value}"


def _normalize_name(name: Optional[str]) -> str:
    if not name:
        return ""
    try:
        from claim_layer.semantic.normalization import normalize_entity_name
        norm = normalize_entity_name(str(name))
        if norm:
            return norm
    except Exception:
        pass
    return re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]+", " ", str(name)).strip().lower()


def _normalize_pred(pred: Optional[str]) -> str:
    if not pred:
        return ""
    try:
        from claim_layer.semantic.normalization import normalize_predicate_name
        norm = normalize_predicate_name(str(pred))
        if norm:
            return re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]+", " ", norm).strip().lower()
    except Exception:
        pass
    return re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]+", " ", str(pred)).strip().lower()


def _canonical_val(val: Any) -> str:
    if val is None:
        return ""
    try:
        from claim_layer.semantic.normalization import normalize_value
        return str(normalize_value(str(val))).strip().lower()
    except Exception:
        return str(val).strip().lower()


def _compute_path_confidence(steps: List[MultihopStep], gamma: float = 0.95) -> float:
    """
    Series semiring operator (⊗): Gödel's T-norm (weakest link) with a bounded
    per-hop transition discount gamma^(k-1):
        Conf = min(s_1, ..., s_k) * (gamma ^ (k - 1))
    Where s_i = claim.confidence * inference_weight.
    Prevents artificial stochastic decay on deductive legal chaining.
    """
    if not steps:
        return 0.0
    step_scores = [
        s.claim.confidence * INFERENCE_WEIGHTS.get(s.claim.inference_type, 0.5)
        for s in steps
    ]
    k = len(steps)
    weakest_link = min(step_scores)
    hop_discount = gamma ** (k - 1)
    return round(weakest_link * hop_discount, 4)


class DependencyGraph:
    """
    Epistemic Dependency Graph over the Provenance Semiring K = ([0, 1], ⊕, ⊗, 0, 1):
    - Series operator (⊗): Gödel T-norm with bounded hop discount along a path.
    - Parallel operator (⊕): Noisy-OR fusion across independent (edge-disjoint) paths.
    - Max-Min Best-First Traversal (Dijkstra in the Gödel Semiring) with O(1) inverted
      token indexing and per-path cycle prevention, ensuring low-reliability paths
      never shadow higher-confidence paths through shared intermediate nodes.
    - Multi-hop contradiction resolution when competing chains reach conflicting values.
    """

    def __init__(self, claims: Optional[List[Claim]] = None, hop_discount: float = 0.95) -> None:
        # entity_norm -> list of claims where entity is subject
        self.by_subject: Dict[str, List[Claim]] = {}
        # token -> set of entity_norm keys in by_subject (O(1) inverted token index)
        self._token_to_subjects: Dict[str, Set[str]] = {}
        # entity_norm -> cached token set
        self._subject_tokens: Dict[str, FrozenSet[str]] = {}
        # value_norm -> list of claims where value is target
        self.by_object: Dict[str, List[Claim]] = {}
        # paragraph_id -> list of claims in same paragraph/chunk
        self.by_chunk: Dict[str, List[Claim]] = {}
        # all claims
        self.claims: List[Claim] = []
        self.hop_discount = hop_discount

        if claims:
            self.add_claims(claims)

    def _index_subject_key(self, sub_key: str) -> None:
        if sub_key in self._subject_tokens:
            return
        toks = frozenset(t for t in sub_key.split() if len(t) >= 3)
        self._subject_tokens[sub_key] = toks
        for tok in toks:
            self._token_to_subjects.setdefault(tok, set()).add(sub_key)

    def add_claims(self, claims: List[Claim]) -> None:
        for c in claims:
            self.claims.append(c)
            can_ent = getattr(c, "canonical_entity", None)
            can_pred = getattr(c, "canonical_predicate", None)
            try:
                from claim_layer.semantic.normalization import (
                    register_entity_alias,
                    register_predicate_alias,
                )
                if can_ent and c.entity:
                    register_entity_alias(c.entity, can_ent)
                if can_pred and c.predicate:
                    register_predicate_alias(c.predicate, can_pred)
            except Exception:
                pass

            sub_keys = {_normalize_name(c.entity)}
            if can_ent:
                sub_keys.add(_normalize_name(can_ent))
            for sub_key in sub_keys:
                if sub_key:
                    bucket = self.by_subject.setdefault(sub_key, [])
                    if c not in bucket:
                        bucket.append(c)
                    self._index_subject_key(sub_key)

            val_str = str(c.value) if c.value is not None else ""
            obj_key = _normalize_name(val_str)
            if obj_key and len(obj_key) >= 3:
                self.by_object.setdefault(obj_key, []).append(c)

            if c.source and c.source.paragraph_id:
                chunk_key = f"{c.source.document_id}::{c.source.paragraph_id}"
                self.by_chunk.setdefault(chunk_key, []).append(c)

    def _resolve_subject_keys(self, entity_norm: str) -> List[str]:
        """Return matching subject keys in `self.by_subject` using the O(1) inverted
        token index, supporting both exact canonical matches and unambiguous subset coreferences.
        """
        if not entity_norm:
            return []
        if entity_norm in self.by_subject:
            return [entity_norm]
        tokens = [t for t in entity_norm.split() if len(t) >= 3]
        if not tokens:
            return []
        t_set = frozenset(tokens)

        # Gather candidate subject keys that share at least one token via inverted index
        candidate_keys: Set[str] = set()
        for tok in t_set:
            candidate_keys.update(self._token_to_subjects.get(tok, ()))

        matches: List[str] = []
        for cand_key in sorted(candidate_keys):
            cand_tokens = self._subject_tokens.get(cand_key)
            if not cand_tokens:
                continue
            if t_set.issubset(cand_tokens) or cand_tokens.issubset(t_set):
                matches.append(cand_key)
        return matches

    def find_paths(
        self,
        start_entity: str,
        target_predicate: str,
        max_hops: int = 3,
    ) -> List[MultihopPath]:
        """
        Traverse the graph from *start_entity* to find values of *target_predicate*
        via Best-First Max-Min search (Dijkstra in the Gödel Semiring) with per-path
        cycle prevention. Ensures weak early paths never block stronger multi-hop paths
        through shared intermediate nodes, and discovers parallel corroborating chains.
        """
        start_norm = _normalize_name(start_entity)
        pred_norm = _normalize_pred(target_predicate)

        if not start_norm:
            return []

        paths: List[MultihopPath] = []
        seen_path_signatures: Set[Tuple[str, ...]] = set()
        initial_keys = self._resolve_subject_keys(start_norm) or [start_norm]

        # Priority queue (max-heap via -prefix_conf):
        # (-prefix_conf, tie_breaker, current_entity_norm, current_steps, path_visited_entities)
        counter = itertools.count()
        heap: List[Tuple[float, int, str, List[MultihopStep], FrozenSet[str]]] = [
            (-1.0, next(counter), k, [], frozenset(initial_keys)) for k in initial_keys
        ]

        # Track best arrival confidence per (node, hop_depth) to prune strictly dominated cyclic detours
        # while allowing distinct parallel paths and stronger longer paths to pass through
        best_arrival: Dict[str, float] = {}

        while heap:
            neg_conf, _, curr_entity, steps, path_visited = heapq.heappop(heap)
            curr_conf = -neg_conf

            if len(steps) >= max_hops:
                continue

            # If we already reached curr_entity with strictly higher confidence via a shorter/equal path,
            # still allow exploration if curr_conf > 0 and this is a distinct simple path, unless heavily dominated
            prev_best = best_arrival.get(curr_entity, -1.0)
            if curr_conf > prev_best:
                best_arrival[curr_entity] = curr_conf

            claims_for_curr = self.by_subject.get(curr_entity, [])

            for claim in claims_for_curr:
                c_pred_norm = _normalize_pred(claim.predicate)
                c_can_pred = _normalize_pred(getattr(claim, "canonical_predicate", None))

                # Direct match at this hop?
                if (
                    c_pred_norm == pred_norm
                    or (pred_norm and pred_norm in c_pred_norm)
                    or (c_can_pred and (c_can_pred == pred_norm or (pred_norm and pred_norm in c_can_pred)))
                ):
                    final_step = MultihopStep(
                        from_entity=claim.entity or curr_entity,
                        predicate=claim.predicate,
                        to_value=claim.value,
                        claim=claim,
                    )
                    full_steps = steps + [final_step]
                    sig = tuple(
                        f"{s.claim.id or ''}::{s.from_entity}::{s.predicate}::{s.to_value}"
                        for s in full_steps
                    )
                    if sig not in seen_path_signatures:
                        seen_path_signatures.add(sig)
                        final_conf = _compute_path_confidence(full_steps, gamma=self.hop_discount)
                        paths.append(
                            MultihopPath(
                                steps=full_steps,
                                final_value=claim.value,
                                confidence=final_conf,
                            )
                        )
                    continue

                # Transition to next entity if claim.value looks like an entity name
                next_val_str = str(claim.value) if claim.value is not None else ""
                next_entity_norm = _normalize_name(next_val_str)

                if next_entity_norm and len(next_entity_norm) >= 3:
                    step = MultihopStep(
                        from_entity=claim.entity or curr_entity,
                        predicate=claim.predicate,
                        to_value=claim.value,
                        claim=claim,
                    )
                    next_steps = steps + [step]
                    next_conf = _compute_path_confidence(next_steps, gamma=self.hop_discount)
                    for resolved_next in self._resolve_subject_keys(next_entity_norm):
                        if resolved_next not in path_visited:
                            heapq.heappush(
                                heap,
                                (
                                    -next_conf,
                                    next(counter),
                                    resolved_next,
                                    next_steps,
                                    path_visited | {resolved_next},
                                ),
                            )

        # Sort paths by confidence DESC, then hop count ASC
        paths.sort(key=lambda p: (-p.confidence, len(p.steps), str(p.final_value)))
        return paths

    def resolve_multihop_detailed(
        self,
        start_entity: str,
        target_predicate: str,
        max_hops: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve *target_predicate* for *start_entity* over the Provenance Semiring:
        - Groups all valid paths by canonical final_value.
        - Within each value group, fuses edge-disjoint independent paths via ⊕ (Noisy-OR).
        - Across competing value groups, applies weighted contradiction penalty and
          surfaces conflicting chains in Result.contradictions.
        """
        paths = self.find_paths(start_entity, target_predicate, max_hops=max_hops)
        if not paths:
            return None

        # Group paths by canonical final_value
        value_groups: Dict[str, List[MultihopPath]] = {}
        for p in paths:
            c_val = _canonical_val(p.final_value)
            value_groups.setdefault(c_val, []).append(p)

        group_summaries: List[Dict[str, Any]] = []
        for c_val, group_paths in value_groups.items():
            # Select mutually edge-disjoint paths (greedy by confidence DESC) so shared intermediate
            # claims do not artificially double-count support
            independent_confs: List[float] = []
            used_claim_ids: Set[str] = set()
            all_group_claims: List[Claim] = []
            seen_group_claim_ids: Set[int] = set()

            for gp in group_paths:
                gp_ids = {
                    s.claim.id or f"{s.from_entity}:{s.predicate}:{s.to_value}"
                    for s in gp.steps
                }
                if not (gp_ids & used_claim_ids):
                    independent_confs.append(gp.confidence)
                    used_claim_ids.update(gp_ids)
                for s in gp.steps:
                    if id(s.claim) not in seen_group_claim_ids:
                        seen_group_claim_ids.add(id(s.claim))
                        all_group_claims.append(s.claim)

            fused_support = (
                independent_confs[0]
                if len(independent_confs) == 1
                else _noisy_or(independent_confs)
            )
            group_summaries.append(
                {
                    "canonical_value": c_val,
                    "representative_value": group_paths[0].final_value,
                    "paths": group_paths,
                    "independent_path_count": len(independent_confs),
                    "fused_support": fused_support,
                    "claims": all_group_claims,
                }
            )

        group_summaries.sort(
            key=lambda g: (-g["fused_support"], -g["paths"][0].confidence, str(g["canonical_value"]))
        )
        winner = group_summaries[0]
        losers = group_summaries[1:]

        winner_support = winner["fused_support"]
        if not losers:
            final_conf = winner_support
            competing_support = 0.0
            contradictions: List[Claim] = []
            reason = Reason.RESOLVED
        else:
            competing_support = _noisy_or([g["fused_support"] for g in losers])
            total_support = winner_support + competing_support
            penalty = (winner_support / total_support) if total_support > 0 else 1.0
            final_conf = round(winner_support * penalty, 4)
            contradictions = [c for g in losers for c in g["claims"]]
            reason = Reason.CONTRADICTION

        subj_opinion = compute_subjective_opinion(winner_support, competing_support)
        supporting_claims = (
            winner["paths"][0].supporting_claims
            if winner["independent_path_count"] == 1
            else winner["claims"]
        )
        cert = generate_epistemic_certificate(
            value=winner["representative_value"],
            confidence=final_conf,
            reason=reason,
            supporting_claims=supporting_claims,
            contradictions=contradictions,
            subjective_opinion=subj_opinion,
        )

        result = Result(
            value=winner["representative_value"],
            confidence=final_conf,
            contradictions=contradictions,
            supporting_claims=supporting_claims,
            reason=reason,
            subjective_opinion=subj_opinion,
            epistemic_certificate=cert,
        )
        return {
            "result": result,
            "paths": paths,
            "winner_group": winner,
            "losing_groups": losers,
            "subjective_opinion": subj_opinion.to_dict(),
            "epistemic_certificate": cert,
        }

    def resolve_multihop(
        self,
        start_entity: str,
        target_predicate: str,
        max_hops: int = 3,
    ) -> Optional[Result]:
        """
        Attempt to resolve *target_predicate* for *start_entity* via multihop traversal.
        Returns Result if a valid path exists, else None.
        """
        detailed = self.resolve_multihop_detailed(
            start_entity, target_predicate, max_hops=max_hops
        )
        return detailed["result"] if detailed else None
