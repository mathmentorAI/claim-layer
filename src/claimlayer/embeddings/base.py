from __future__ import annotations

from typing import List


class EmbeddingProvider:
    """Base class for all embedding providers.

    Subclass this and implement ``embed`` to plug a real model into ClaimLayer.

    Example::

        class OpenAIProvider(EmbeddingProvider):
            def embed(self, text: str) -> List[float]:
                return openai.Embedding.create(input=text, model="text-embedding-3-small")
                    .data[0].embedding
    """

    def embed(self, text: str) -> List[float]:
        raise NotImplementedError
