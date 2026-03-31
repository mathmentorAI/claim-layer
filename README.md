# ClaimLayer

**Compute truth from evidence, not text**

---

## What this is

ClaimLayer is a deterministic engine that computes truth from structured evidence.

Not generation.
Not retrieval.
Computation.

---

## The problem

Modern AI systems (LLMs + RAG) have a fundamental limitation:

- They retrieve text, not facts
- They generate answers, not truth
- They cannot detect contradictions
- Confidence scores are opaque and non-reproducible

```
Same question → different answer
Different documents → silent conflicts
Confidence → arbitrary number
```

There is no state of knowledge. Only text.

---

## The insight

Truth is not something you generate.

It is something you compute from evidence.

---

## The model

ClaimLayer introduces a minimal but strict model:

**Claim**

A unit of extracted information from a source.

```json
{
  "claim_id": 1,
  "text": "ACME payment terms are 30 days",
  "source": "Contract_A.pdf"
}
```

**Fact**

A structured representation of a claim:

```
(entity, predicate, value)
```

Example:

```
("ACME", "payment_terms", "30 days")
```

**Canonical Value**

A normalized representation of the value:

```
"30 days"     → 30
"thirty days" → 30
```

**Evidence**

Each fact carries a score:

```
score ∈ [0, 1]
```

**Truth Resolution**

Truth is computed by:

1. Grouping facts by `(entity, predicate, canonical_value)`
2. Deduplicating evidence
3. Aggregating scores using `noisy_or(scores)`
4. Applying contradiction penalty

```
final_confidence = noisy_or(scores) × penalty
```

---

## Example

**Input**

Document A
```
ACME payment terms are 30 days
```

Document B
```
ACME payment terms are thirty days
```

Document C
```
ACME payment terms are 45 days
```

**Query**
```
What are the payment terms for ACME?
```

**Output**

```json
{
  "value": "30 days",
  "canonical_value": 30,
  "confidence": 0.36,
  "confidence_explanation": {
    "selected_evidence_count": 2,
    "total_evidence_count": 3,
    "aggregation_method": "noisy_or",
    "penalty": 0.5,
    "penalty_reason": "2 competing values detected"
  },
  "contradictions": [
    {
      "value": "45 days",
      "confidence": 0.18
    }
  ]
}
```

---

## Guarantees

ClaimLayer is designed around strict guarantees:

**G1 — Query-conditioned truth**
Truth is computed only from evidence relevant to the query.

**G2 — Evidence-backed answers**
Every output is traceable to concrete evidence.

**G3 — Canonical consistency**
Semantically equivalent values are merged.

**G4 — Controlled confidence**
Confidence is deterministic, reproducible, and mathematically defined.

**G5 — Explicit contradictions**
Conflicts are not hidden — they are surfaced and penalized.

---

## What this is NOT

- Not a chatbot
- Not a vector database
- Not a RAG pipeline
- Not probabilistic reasoning

This is: an evidence computation engine.

---

## Architecture (simplified)

```
Documents
   ↓
Claims extraction
   ↓
Facts (entity, predicate, value)
   ↓
Normalization (canonical_value)
   ↓
Deduplication
   ↓
Aggregation (noisy_or)
   ↓
Contradiction handling
   ↓
Truth
```

---

## Current limitations

These are explicit and intentional:

**1. Claim-level retrieval**
Retrieval operates at claim granularity. A claim may contain multiple facts, not all relevant to the query.

**2. No cross-document deduplication**
Duplicate content across documents may inflate confidence.

**3. Unit ambiguity**
`"30 days"` and `"30 euros"` both normalize to `30`.
Planned fix: `(quantity, unit)` → `(30, "days")`.

**4. Basic normalization**
Currently supports numeric values and English word numbers.

---

## Roadmap

- Fact-level indexing (G5)
- Unit-aware canonical values
- Cross-document deduplication
- Multi-dimensional confidence model

---

## Why this matters

AI systems today optimize for plausibility.

ClaimLayer optimizes for truth.

---

## Category

We call this: **Evidence Intelligence**

---

## Installation

```bash
pip install claim-layer
```

---

## Status

**v0.3 — Stable core**

- Deterministic truth computation
- Canonical normalization
- Contradiction handling
- Explainable confidence

---

## Usage

```python
from claim_layer import ClaimLayerStore
from claim_layer.api import ask

store = ClaimLayerStore("./evidence.db")

# Ingest documents
store.ingest_document(payload)

# Query
response = ask(store, project_id="demo", query="payment terms", top_k=20)
```

---

*If your system cannot explain why something is true, detect when it is wrong, or quantify uncertainty deterministically — then it does not compute truth. It generates text.*

*ClaimLayer is the missing layer between data and reasoning.*
