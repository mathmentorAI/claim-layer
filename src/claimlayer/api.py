from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import claim_layer.semantic.embeddings as _emb_module
from claim_layer import ClaimLayerStore, IngestedClaim, IngestedDocument, IngestedEntity, IngestedFact
from claim_layer.api.query import ask as _ask

from claimlayer.embeddings.simple import SimpleHashEmbeddingProvider

# shared sentinel — one instance is sufficient
_DEFAULT_PROVIDER = SimpleHashEmbeddingProvider()
_DEFAULT_DB = None  # resolved lazily per instance when db_path is not supplied


class ClaimLayer:
    """Public API for the ClaimLayer evidence intelligence engine.

    Wraps the existing ``claim_layer`` pipeline and exposes a minimal, clean
    interface for ingestion and truth queries.

    Args:
        db_path:            Path to the SQLite database file.  Defaults to a
                            temporary file so ``ClaimLayer()`` works with zero
                            configuration.
        embedding_provider: An ``EmbeddingProvider`` instance.  Defaults to
                            ``SimpleHashEmbeddingProvider`` — deterministic,
                            no external dependencies, word-overlap similarity.
                            **Not semantic.** For production pass a real provider.
        project_id:         Logical partition key for multi-tenant usage.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        embedding_provider=None,
        project_id: str = "default",
    ) -> None:
        self._provider = embedding_provider or _DEFAULT_PROVIDER
        self._project_id = project_id

        if db_path is None:
            # create a temp file that lives as long as this instance
            self._tmpdir = tempfile.TemporaryDirectory()
            db_path = Path(self._tmpdir.name) / "evidence.db"
        else:
            self._tmpdir = None

        self._store = ClaimLayerStore(Path(db_path), enable_semantic=True)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    @staticmethod
    def _string_to_document(text: str, idx: int, project_id: str) -> IngestedDocument:
        """Wrap a plain string into a minimal IngestedDocument.

        Each string becomes one claim and one fact:
          entity    = "document"
          predicate = "statement"
          value     = the text itself
        """
        cid = f"c{idx}"
        return IngestedDocument(
            project_id=project_id,
            filename=f"input_{idx}.txt",
            entities=[IngestedEntity("e_doc", "document")],
            claims=[IngestedClaim(cid, text, confidence=1.0)],
            facts=[IngestedFact(cid, "e_doc", "statement", text)],
        )

    def ingest(self, documents: list[Any]) -> None:
        """Ingest one or more documents into the evidence store.

        Accepts:
          - ``IngestedDocument`` dataclasses
          - plain dicts with equivalent fields
          - plain strings — each string is wrapped into a minimal document
            with entity="document", predicate="statement", value=<the string>

        When an ``embedding_provider`` was supplied at construction, claim
        embeddings are computed and persisted for semantic search.
        """
        # Embedding injection via scoped module-level override.
        #
        # KNOWN LIMITATION: this is not safe for concurrent use (threads/async).
        # Two simultaneous ingest() calls on different ClaimLayer instances will
        # race on the shared _emb_module.embed reference.
        #
        # Planned fix: pass the provider through ClaimLayerStore's ingestion
        # path explicitly instead of patching the module.  This requires a
        # small signature change in store.ingest_document() and is tracked as
        # a known design decision, not a bug.
        original_embed = _emb_module.embed
        _emb_module.embed = self._provider.embed
        try:
            for idx, doc in enumerate(documents):
                if isinstance(doc, str):
                    doc = self._string_to_document(doc, idx, self._project_id)
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
