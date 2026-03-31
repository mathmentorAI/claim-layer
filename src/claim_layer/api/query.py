from __future__ import annotations

from typing import TYPE_CHECKING, Any

from claim_layer.semantic.hybrid import hybrid_search
from claim_layer.semantic.search import semantic_search
from claim_layer.semantic.truth import resolve_truth
from claim_layer.semantic.weighting import weight_evidence

if TYPE_CHECKING:
    from claim_layer.store import ClaimLayerStore


def ask(
    store: ClaimLayerStore,
    project_id: str,
    query: str,
    top_k: int = 20,
    embed_fn=None,
) -> dict[str, Any]:
    hits = semantic_search(store, project_id, query, top_k, embed_fn=embed_fn)
    if not hits:
        # No semantic match → no evidence relevant to this query.
        # Do NOT fall through to hybrid_search: an empty hit set would trigger
        # its full-scan fallback, returning facts unrelated to the query.
        return {"query": query, "results": []}

    grouped = hybrid_search(store, project_id, query, top_k, hits=hits)
    if not grouped:
        return {"query": query, "results": []}

    weighted = weight_evidence(store, grouped, hits)
    resolved = resolve_truth(store, weighted)

    return {"query": query, "results": resolved}
