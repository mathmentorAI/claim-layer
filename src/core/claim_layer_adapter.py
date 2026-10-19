from __future__ import annotations

import sys
from pathlib import Path
from typing import List

# Make claim-layer importable without modifying its source tree.
_SRC = Path(__file__).parent.parent / "claim-layer" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from core.interfaces import Claim, Result, SourceRef
from core.inference_assignment import assign_inference_type
from core.inference_engine import resolve_claims


class ClaimLayerAdapter:
    """
    Single integration point between Deltoryx and the claim-layer engine.

    Deterministic at the evidence computation layer.
    Deterministic given a fixed claim set.
    Given the same set of claims, the resulting knowledge state is guaranteed to be identical.

    Responsibilities:
      - Translate Deltoryx payloads → claim-layer ingestion calls
      - Translate claim-layer query results → Deltoryx Claim objects
      - Resolve truth from a list of Deltoryx Claims using claim-layer logic
    """

    def __init__(self, store, project_id: str = "default") -> None:
        self.store = store
        self.project_id = project_id

    # ------------------------------------------------------------------
    # A) Ingestion
    # ------------------------------------------------------------------

    def ingest_document(self, payload) -> dict:
        """
        Accept an IngestedDocument (or equivalent dict) produced by a
        ClaimAdapter upstream and forward it verbatim to claim-layer.
        Returns ingestion counts: {documents, entities, claims, facts}.
        """
        return self.store.ingest_document(payload)

    # ------------------------------------------------------------------
    # B) Retrieval
    # ------------------------------------------------------------------

    def get_by_entity(self, entity: str) -> List[Claim]:
        """
        Return all Deltoryx Claim objects for a given entity, across all
        predicates, sourced from claim-layer via get_facts().
        """
        rows = self.store.get_facts(self.project_id, entity_name=entity)

        claims: List[Claim] = []
        for row in rows:
            source = SourceRef(
                document_id=row["filename"] or "",
                page=row["page"] or 0,
                paragraph_id=row["paragraph_id"] or "",
            )
            # Typed-extraction facts carry their (gate-clamped) inference type;
            # legacy facts (NULL) are classified lexically from the claim text.
            stored_inference = row.get("inference_type")
            claims.append(
                Claim(
                    id=str(row["fact_id"]),
                    entity=row["entity_name"],
                    predicate=row["fact_type"],
                    value=row["value"],
                    source=source,
                    confidence=float(row["confidence"]),
                    inference_type=str(stored_inference) if stored_inference else assign_inference_type(
                        predicate=str(row["fact_type"]),
                        value=row["value"],
                        claim_text=str(row.get("claim_text") or ""),
                    ),
                    valid_from=row.get("valid_from"),
                    valid_until=row.get("valid_until"),
                    quote=str(row.get("claim_text") or ""),
                )
            )
        return claims

    def get_all(self) -> List[Claim]:
        """
        Return all Deltoryx Claim objects across all entities in this project.
        """
        rows = self.store.get_facts(self.project_id)
        claims: List[Claim] = []
        for row in rows:
            source = SourceRef(
                document_id=row["filename"] or "",
                page=row["page"] or 0,
                paragraph_id=row["paragraph_id"] or "",
            )
            stored_inference = row.get("inference_type")
            claims.append(
                Claim(
                    id=str(row["fact_id"]),
                    entity=row["entity_name"],
                    predicate=row["fact_type"],
                    value=row["value"],
                    source=source,
                    confidence=float(row["confidence"]),
                    inference_type=str(stored_inference) if stored_inference else assign_inference_type(
                        predicate=str(row["fact_type"]),
                        value=row["value"],
                        claim_text=str(row.get("claim_text") or ""),
                    ),
                    valid_from=row.get("valid_from"),
                    valid_until=row.get("valid_until"),
                    quote=str(row.get("claim_text") or ""),
                )
            )
        return claims

    # ------------------------------------------------------------------
    # C) Resolution
    # ------------------------------------------------------------------

    def resolve(self, claims: List[Claim]) -> Result:
        """
        Compute truth from a pre-filtered list of Deltoryx Claims.

        Delegates to the unified inference engine (core.inference_engine):
        canonical-value grouping via claim-layer normalisation, per-source
        dedup, weighted noisy-OR election, temporal validity, and a
        contradiction penalty proportional to the losing groups' support
        (NOT the legacy flat 1/n).
        """
        return resolve_claims(claims)
