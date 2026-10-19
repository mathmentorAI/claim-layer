from __future__ import annotations

import hashlib
import math
import re
from typing import List

from .base import EmbeddingProvider

_DIM = 64  # fixed vector size — small enough to be fast, large enough to be useful

_CANONICAL_SYNONYMS = {
    "paid": "payment",
    "pay": "payment",
    "payments": "payment",
    "terms": "term",
    "invoices": "invoice",
    "facturas": "factura",
    "importes": "importe",
    "impagados": "impagada",
    "impagado": "impagada",
    "hechos": "hecho",
    "probados": "probado",
    "fundamentos": "fundamento",
}


class SimpleHashEmbeddingProvider(EmbeddingProvider):
    """Deterministic, zero-dependency embedding provider using word-level hashing.

    Converts text to a fixed-size vector by:
      1. Tokenizing into lowercase alphanumeric words (stripping punctuation)
      2. Mapping each word (and canonical stem/synonym) to a bucket via MD5
      3. Accumulating word counts per bucket
      4. L2-normalizing the resulting vector
    """

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * _DIM
        tokens = re.findall(r"\w+", text.lower())
        expanded: list[str] = []
        for w in tokens:
            expanded.append(w)
            syn = _CANONICAL_SYNONYMS.get(w)
            if syn:
                expanded.append(syn)

        for word in expanded:
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % _DIM
            vec[bucket] += 1.0

        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            vec = [x / norm for x in vec]

        return vec
