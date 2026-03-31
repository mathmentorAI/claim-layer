from __future__ import annotations

import hashlib
import math
from typing import List

from .base import EmbeddingProvider

_DIM = 64  # fixed vector size — small enough to be fast, large enough to be useful


class SimpleHashEmbeddingProvider(EmbeddingProvider):
    """Deterministic, zero-dependency embedding provider using word-level hashing.

    Converts text to a fixed-size vector by:
      1. Tokenizing into lowercase words
      2. Mapping each word to a bucket via MD5 (word → bucket index mod DIM)
      3. Accumulating word counts per bucket
      4. L2-normalizing the resulting vector

    This is a bag-of-words model: texts that share words produce non-zero cosine
    similarity.  It is NOT semantic — "car" and "automobile" have zero overlap —
    but it is functional and requires no external API, model, or configuration.

    Intended for quickstart and testing only.
    For production, replace with a real EmbeddingProvider.
    """

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * _DIM
        for word in text.lower().split():
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % _DIM
            vec[bucket] += 1.0

        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            vec = [x / norm for x in vec]

        return vec
