"""
ClaimLayer — Quickstart

Run with:
    PYTHONPATH=src python3 examples/quickstart.py

No external dependencies. No API keys. No configuration.

Uses the built-in SimpleHashEmbeddingProvider — word-overlap similarity,
deterministic, zero external deps. Not semantic. For production, pass a
real EmbeddingProvider.
"""

from claimlayer import ClaimLayer

cl = ClaimLayer()

cl.ingest([
    "ACME payment terms are 30 days",
    "ACME payment terms are thirty days",
    "ACME payment terms are 45 days",
])

result = cl.ask("What are the payment terms for ACME?")

for r in result["results"]:
    print(f"value:          {r['value']}")
    print(f"canonical:      {r['canonical_value']}")
    print(f"confidence:     {r['confidence']}")
    print(f"contradictions: {[c['value'] for c in r['contradictions']]}")
    print()
