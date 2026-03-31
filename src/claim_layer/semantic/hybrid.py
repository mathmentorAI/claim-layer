from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claim_layer.store import ClaimLayerStore


def hybrid_search(
    store: ClaimLayerStore,
    project_id: str,
    query: str,
    top_k: int = 20,
    hits: list[tuple[int, float]] | None = None,
) -> list[dict[str, Any]]:
    """SQL-based fact retrieval grouped by (entity, predicate, value).

    When *hits* is provided (non-empty), only fact groups whose supporting
    claim_ids intersect the hit set are returned. This keeps the resolution
    pipeline focused on query-relevant facts.

    When *hits* is None or empty, falls back to returning all fact groups for
    the project (useful for direct/test callers that bypass semantic_search).
    """
    hit_ids: set[int] = {cid for cid, _ in hits} if hits else set()

    if hit_ids:
        placeholders = ",".join("?" * len(hit_ids))
        sql = f"""
            SELECT
                e.name      AS entity,
                f.fact_type AS predicate,
                f.value,
                f.claim_id
            FROM facts f
            JOIN entities e  ON e.id  = f.entity_id
            JOIN claims   c  ON c.id  = f.claim_id
            JOIN documents d ON d.id  = c.document_id
            WHERE d.project_id = ?
              AND f.claim_id IN ({placeholders})
            ORDER BY e.name, f.fact_type, f.value, f.claim_id
        """
        params: list[Any] = [project_id, *hit_ids]
    else:
        sql = """
            SELECT
                e.name      AS entity,
                f.fact_type AS predicate,
                f.value,
                f.claim_id
            FROM facts f
            JOIN entities e  ON e.id  = f.entity_id
            JOIN claims   c  ON c.id  = f.claim_id
            JOIN documents d ON d.id  = c.document_id
            WHERE d.project_id = ?
            ORDER BY e.name, f.fact_type, f.value, f.claim_id
        """
        params = [project_id]

    with store._conn() as conn:
        rows = conn.execute(sql, params).fetchall()

    # group by (entity, predicate, value) — collect supporting claim_ids
    groups: dict[tuple[str, str, str], list[int]] = {}
    for row in rows:
        key = (row["entity"], row["predicate"], row["value"])
        groups.setdefault(key, []).append(row["claim_id"])

    return [
        {
            "entity": entity,
            "predicate": predicate,
            "value": value,
            "supporting_claim_ids": claim_ids,
        }
        for (entity, predicate, value), claim_ids in groups.items()
    ]
