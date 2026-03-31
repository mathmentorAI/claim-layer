from __future__ import annotations

from typing import List

from .base import EmbeddingProvider


class DummyEmbeddingProvider(EmbeddingProvider):
    """Sentinel used when no provider is configured.

    Raises a clear error on any call so the user knows exactly what is missing,
    rather than silently returning empty vectors.
    """

    def embed(self, text: str) -> List[float]:
        raise RuntimeError(
            "No embedding provider configured. "
            "Pass an EmbeddingProvider to ClaimLayer(embedding_provider=...).\n"
            "Example:\n"
            "  from claimlayer.embeddings.base import EmbeddingProvider\n"
            "  class MyProvider(EmbeddingProvider):\n"
            "      def embed(self, text): return my_model.encode(text)"
        )
