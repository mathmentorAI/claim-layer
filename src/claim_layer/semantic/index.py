from __future__ import annotations

import math
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from claim_layer.store import ClaimLayerStore


class VectorIndex:
    def __init__(self, store: ClaimLayerStore, project_id: str) -> None:
        self._store = store
        self._project_id = project_id
        self.vectors: List[List[float]] = []
        self.claim_ids: List[int] = []
        self._loaded = False

    def _load(self) -> None:
        rows = self._store.get_claims_with_embeddings(self._project_id)
        vectors: List[List[float]] = []
        claim_ids: List[int] = []
        expected_dim: int | None = None  # fixed from the first valid vector; never updated

        for row in rows:
            vec = row.get("embedding")
            if not vec:
                continue
            if expected_dim is None:
                expected_dim = len(vec)  # anchor: all subsequent vectors must match this
            if len(vec) != expected_dim:
                continue  # dimensionality mismatch — skip silently, never correct
            vectors.append(vec)
            claim_ids.append(row["id"])

        self.vectors = vectors
        self.claim_ids = claim_ids
        self._loaded = True

    def invalidate(self) -> None:
        """Reset the index so the next search reloads from the store."""
        self._loaded = False
        self.vectors = []
        self.claim_ids = []

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    def search(
        self, query_embedding: List[float], top_k: int = 20
    ) -> List[tuple[int, float]]:
        if not self._loaded:
            self._load()

        if not query_embedding or not self.vectors:
            return []

        scores = [
            (claim_id, self._cosine_similarity(query_embedding, vec))
            for claim_id, vec in zip(self.claim_ids, self.vectors)
        ]
        scores.sort(key=lambda t: t[1], reverse=True)
        return scores[:top_k]
