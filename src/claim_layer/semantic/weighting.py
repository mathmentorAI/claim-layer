from __future__ import annotations

from typing import TYPE_CHECKING, Any

from claim_layer.semantic.normalization import normalize_value

if TYPE_CHECKING:
    from claim_layer.store import ClaimLayerStore


def weight_evidence(
    store: ClaimLayerStore,
    grouped_facts: list[dict[str, Any]],
    hits: list[tuple[int, float]],
) -> list[dict[str, Any]]:
    if not grouped_facts:
        return []

    # Step 1 — similarity map from vector search hits
    sim_map: dict[int, float] = {claim_id: sim for claim_id, sim in hits}

    # Step 2 — fetch all confidences in one query
    all_claim_ids: list[int] = []
    for group in grouped_facts:
        all_claim_ids.extend(group.get("supporting_claim_ids") or [])

    # conf_map: claim_id → {confidence, source}
    # source = document_id, used downstream for evidence deduplication
    conf_map: dict[int, dict[str, Any]] = {}
    if all_claim_ids:
        placeholders = ",".join("?" * len(set(all_claim_ids)))
        with store._conn() as conn:
            rows = conn.execute(
                f"SELECT id, confidence, document_id FROM claims WHERE id IN ({placeholders})",
                list(set(all_claim_ids)),
            ).fetchall()
        conf_map = {
            row["id"]: {"confidence": row["confidence"], "source": row["document_id"]}
            for row in rows
        }

    # Step 3 & 4 — build weighted evidence per group
    results: list[dict[str, Any]] = []
    for group in grouped_facts:
        evidence: list[dict[str, Any]] = []
        for claim_id in group.get("supporting_claim_ids") or []:
            info = conf_map.get(claim_id, {"confidence": 0.0, "source": None})
            confidence = info["confidence"]
            similarity = sim_map.get(claim_id, 0.0)
            evidence.append(
                {
                    "claim_id": claim_id,
                    "confidence": confidence,
                    "similarity": similarity,
                    "score": confidence * similarity,
                    "source": info["source"],  # document_id — dedup key component
                }
            )

        raw_value = group.get("value") or ""
        results.append(
            {
                "entity": group.get("entity") or "",
                "predicate": group.get("predicate") or "",
                "value": raw_value,
                "canonical_value": normalize_value(raw_value),
                "evidence": evidence,
            }
        )

    return results
