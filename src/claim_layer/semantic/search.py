from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .embeddings import embed
from .index import VectorIndex

if TYPE_CHECKING:
    from claim_layer.store import ClaimLayerStore


def semantic_search(
    store: ClaimLayerStore,
    project_id: str,
    query: str,
    top_k: int = 20,
    embed_fn=None,
) -> list[tuple[int, float]]:
    """Pure vector retrieval. Returns (claim_id, similarity) sorted by similarity DESC.

    embed_fn — optional callable (str) -> List[float].  When provided it is used
    instead of the module-level stub, allowing callers to inject a real provider
    without modifying this module.
    """
    query_vec = (embed_fn or embed)(query)
    if not query_vec:
        return []

    idx = VectorIndex(store, project_id)
    return idx.search(query_vec, top_k=top_k)


def enrich_claims(
    store: ClaimLayerStore,
    claim_ids: list[int],
) -> list[dict[str, Any]]:
    """Fetch claim + first fact context for each claim_id in a single SQL query.

    Returns rows in the same order as claim_ids. Claims missing from the DB are skipped.
    """
    if not claim_ids:
        return []

    placeholders = ",".join("?" * len(claim_ids))
    with store._conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
                c.id          AS claim_id,
                c.text,
                c.confidence,
                e.name        AS entity,
                f.fact_type   AS predicate,
                f.value
            FROM claims c
            LEFT JOIN facts f    ON f.claim_id = c.id
            LEFT JOIN entities e ON e.id = f.entity_id
            WHERE c.id IN ({placeholders})
            ORDER BY c.id, f.id
            """,
            claim_ids,
        ).fetchall()

    # one row per claim: keep the first fact encountered (lowest f.id per claim)
    seen: set[int] = set()
    id_to_row: dict[int, dict[str, Any]] = {}
    for row in rows:
        cid = row["claim_id"]
        if cid not in seen:
            seen.add(cid)
            id_to_row[cid] = {
                "claim_id": cid,
                "text": row["text"],
                "confidence": row["confidence"],
                "entity": row["entity"],
                "predicate": row["predicate"],
                "value": row["value"],
            }

    # order follows claim_ids, not SQL ORDER BY — safe against DB reordering
    return [id_to_row[cid] for cid in claim_ids if cid in id_to_row]
