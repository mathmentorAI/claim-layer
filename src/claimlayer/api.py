from __future__ import annotations

from pathlib import Path
from typing import Any

import claim_layer.semantic.embeddings as _emb_module
from claim_layer import ClaimLayerStore
from claim_layer.api.query import ask as _ask

from claimlayer.embeddings.default import DummyEmbeddingProvider


class ClaimLayer:
    """Public API for the ClaimLayer evidence intelligence engine.

    Wraps the existing ``claim_layer`` pipeline and exposes a minimal, clean
    interface for ingestion and truth queries.

    Args:
        db_path:            Path to the SQLite database file.
        embedding_provider: An ``EmbeddingProvider`` instance.  Required for
                            semantic search.  If omitted, ``ask()`` will return
                            no results and ``ingest()`` will store facts without
                            embeddings.
        project_id:         Logical partition key for multi-tenant usage.
    """

    def __init__(
        self,
        db_path: str | Path,
        embedding_provider=None,
        project_id: str = "default",
    ) -> None:
        self._provider = embedding_provider or DummyEmbeddingProvider()
        self._project_id = project_id
        self._store = ClaimLayerStore(
            db_path,
            enable_semantic=embedding_provider is not None,
        )

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest(self, documents: list[Any]) -> None:
        """Ingest one or more documents into the evidence store.

        Each document may be an ``IngestedDocument`` dataclass or a plain dict
        with equivalent fields (see ``claim_layer.models``).

        When an ``embedding_provider`` was supplied at construction, claim
        embeddings are computed via the provider and persisted alongside each
        claim so they are available for semantic search.
        """
        # Temporarily inject the provider into the embedding module so that
        # ClaimLayerStore's semantic path (enable_semantic=True) uses our
        # provider instead of the stub.  The original is restored in `finally`
        # so other callers are never affected.
        original_embed = _emb_module.embed
        _emb_module.embed = self._provider.embed
        try:
            for doc in documents:
                self._store.ingest_document(doc)
        finally:
            _emb_module.embed = original_embed

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def ask(self, query: str, top_k: int = 20) -> dict[str, Any]:
        """Resolve truth for *query* from the ingested evidence.

        Calls the existing pipeline:
            semantic_search → hybrid_search → weight_evidence → resolve_truth

        Returns the structured output of ``resolve_truth``, including
        ``value``, ``canonical_value``, ``confidence``,
        ``confidence_explanation``, ``contradictions``, and
        ``supporting_evidence`` for each resolved fact.

        Returns ``{"query": query, "results": []}`` when no relevant evidence
        is found (no embedding hits or empty store).
        """
        return _ask(
            self._store,
            self._project_id,
            query,
            top_k,
            embed_fn=self._provider.embed,
        )
