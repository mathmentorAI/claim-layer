# claim-layer — Architecture

## Overview

claim-layer is a structured evidence intelligence system. It ingests documents, extracts claims and facts, and resolves query-aware truth values from conflicting evidence. The system is deterministic, explainable, and requires no external dependencies beyond Python's standard library.

---

## Core Concepts

These terms have precise meanings within this system. They are not interchangeable.

**Claim**
A raw extracted statement from a source document. Stored as free text with a confidence score. A single claim may support multiple facts. Claims are the retrieval unit.

**Fact**
A structured triple: `(entity, predicate, value)`. Derived from a claim. Multiple claims can support the same fact. Multiple facts can share the same `(entity, predicate)` with different values — this is a contradiction. Facts are the resolution unit.

**Evidence**
A claim in the context of a specific fact, augmented with:
- `confidence` — reliability signal of the source claim (stored in DB)
- `similarity` — semantic relevance of the claim to the current query (from vector search)
- `score` — combined weight: `confidence × similarity`

Evidence is the scoring unit.

**Truth**
The selected value for a given `(entity, predicate)` pair after aggregating all supporting evidence and applying contradiction handling. Truth is always accompanied by its evidence trace and any competing alternatives.

---

## System Guarantees

These properties hold for all outputs produced by the system, unconditionally:

- **Deterministic output.** Identical inputs and DB state always produce identical outputs. No randomness is introduced at any stage.
- **Evidence-backed values.** Every resolved truth value is supported by at least one explicit evidence item with a traceable `claim_id`.
- **Contradictions are always surfaced.** When competing values exist for the same `(entity, predicate)`, all alternatives are returned in `contradictions` and `alternative_evidence`. No conflict is silently resolved.
- **Confidence reflects aggregated evidence.** The `confidence` field in the output is derived from `noisy_or` over stored claim confidences and a contradiction penalty. It is not a model output, a guess, or a generated score.
- **No generative step in truth resolution.** The system contains no LLM or generative component in the resolution pipeline. There is no hallucination risk in the output values — every value originates from an ingested document.
- **Full evidence trace.** For every resolved truth, the output includes `supporting_evidence` (claims backing the selected value) and `alternative_evidence` (claims backing each competing value), with per-claim scores.

---

## Non-Goals

The system explicitly does not do the following:

- **Does not generate natural language answers.** Outputs are structured data, not text.
- **Does not infer missing facts.** If a fact is absent from the ingested documents, it is absent from the output. The system does not fill gaps.
- **Does not resolve semantic value equivalence.** Values that cannot be deterministically normalized (e.g., `"around 30 days"`, `"30 días"`) are treated as distinct and may produce contradictions. Numeric equivalence (`"30 days"` vs `"thirty days"`) is resolved in v0.3 via deterministic normalization.
- **Does not guarantee correctness of source data.** Confidence reflects the extraction pipeline's signal, not ground truth. If source documents contain errors, those errors propagate.
- **Does not deduplicate evidence across sources.** Multiple claims from the same document or paragraph are treated as independent evidence. This inflates confidence in correlated sources.
- **Does not rank results by relevance to the query.** The output ordering is by `(entity, predicate)` ascending, not by similarity or importance.

---

## Scoring Model

The scoring model is the foundational formula of the system. All confidence values in the output are derived from it.

**Per-evidence score**
```
score = confidence × similarity
```
Where `confidence` is the stored claim confidence (float in [0, 1]) and `similarity` is the cosine similarity between the query embedding and the claim embedding (float in [0, 1]).

**Aggregated confidence (noisy-OR over scores)**
```
aggregated = 1 - ∏(1 - clamp(sᵢ, 0, 1))  for each score sᵢ in the group
```
Noisy-OR is applied to `score` values, not raw confidences. This means query-irrelevant claims (low similarity → low score) contribute less to the aggregated confidence than query-relevant ones. Noisy-OR models the probability that at least one independent piece of evidence is correct. It saturates toward 1.0 as evidence accumulates and degrades gracefully toward 0.0 with weak evidence. The independence assumption is a known limitation (see Known Limitations).

**Contradiction penalty**
```
penalty = 1 / N
```
Where N is the number of distinct values for the same `(entity, predicate)`. Applied uniformly to all candidates.

**Final confidence**
```
final_confidence = aggregated × penalty
```

This is the value reported in the output. A result with no contradictions (`N = 1`) receives `penalty = 1.0` and is reported at full aggregated confidence. A result with three competing values receives `penalty = 1/3`.

---

## Current Scope Boundary

The system operates at **claim-level retrieval** and **fact-level resolution**.

It does not yet:
- Index facts directly (embeddings are on claims, not `(entity, predicate, value)` triples)
- Perform semantic value equivalence across all surface forms (partial: numeric normalization active in v0.3)
- Deduplicate evidence from correlated sources across documents

These boundaries are the direct consequence of the Known Limitations listed below. Each planned improvement corresponds to crossing one of these boundaries.

---

## Data Flow Diagram

```
query: str
  │
  ▼
semantic_search(store, project_id, query, top_k)
  │   Converts query to embedding vector, searches VectorIndex
  │   → [(claim_id: int, similarity: float)]
  │
  ▼
hybrid_search(store, project_id, query, top_k, hits)
  │   SQL scan over facts filtered by hit claim_ids, grouped by (entity, predicate, value)
  │   → [{entity, predicate, value, supporting_claim_ids: [int]}]
  │
  ▼
weight_evidence(store, grouped_facts, hits)
  │   Attaches per-claim confidence (from DB) and similarity (from hits)
  │   Computes score = confidence × similarity for each evidence item
  │   Calls normalize_value(value) → canonical_value for each group
  │   → [{entity, predicate, value, canonical_value, evidence: [{claim_id, confidence, similarity, score}]}]
  │
  ▼
resolve_truth(store, weighted_facts)
  │   Groups by (entity, predicate, canonical_value) — merges equivalent values
  │   Applies noisy-OR aggregation over merged groups
  │   Applies contradiction penalty (1/N), selects best value
  │   → [{entity, predicate, value, canonical_value, confidence, contradictions, supporting_evidence, alternative_evidence}]
  │
  ▼
ask(store, project_id, query, top_k)
  Orchestration layer — executes the full pipeline and returns structured output
  → {"query": str, "results": [...]}
```

---

## Current Pipeline

### `semantic_search(store, project_id, query, top_k)`
**Module:** `src/claim_layer/semantic/search.py`

Generates an embedding for the query via `embed(query)` and runs cosine similarity search over the in-memory `VectorIndex`. Returns early with `[]` if the embedding is empty (stub provider active).

Output:
```python
[(claim_id: int, similarity: float)]  # sorted by similarity DESC
```

### `hybrid_search(store, project_id, query, top_k, hits=None)`
**Module:** `src/claim_layer/semantic/hybrid.py`

Executes a SQL query over `facts`, joined with `entities`, `claims`, and `documents`. Groups rows by `(entity, predicate, value)`, collecting all `claim_id`s per group.

When `hits` is provided (non-empty), the SQL adds `AND f.claim_id IN (...)` — only fact groups that intersect the semantic hit set are returned. This keeps resolution focused on query-relevant facts.

When `hits` is absent or empty, falls back to returning all fact groups for the project (used by direct callers and tests that bypass `semantic_search`).

Output:
```python
[{
    "entity": str,
    "predicate": str,
    "value": str,
    "supporting_claim_ids": [int]
}]
```

### `weight_evidence(store, grouped_facts, hits)`
**Module:** `src/claim_layer/semantic/weighting.py`

Builds a `sim_map` from `hits` and fetches `confidence` for all claim ids in a single SQL query. For each group, constructs an evidence list with per-claim `score = confidence × similarity`. Missing claim ids default to `0.0` for both values.

Output:
```python
[{
    "entity": str,
    "predicate": str,
    "value": str,
    "canonical_value": int | str,  # int if normalized, original string otherwise
    "evidence": [{"claim_id": int, "confidence": float, "similarity": float, "score": float, "source": int}]
}]
```

### `normalize_value(value: str) -> int | str`
**Module:** `src/claim_layer/semantic/normalization.py`

Deterministic, no-exception value normalizer. Returns an `int` when the value can be unambiguously mapped to a number, or the original string unchanged when uncertain.

Rules (v0.3):
- **Rule A** — leading integer before a unit: `"30 days"` → `30`, `"30-day period"` → `30`
- **Rule B** — single English number word: `"thirty"` → `30`, `"forty five"` → `45`
- **Fallback** — anything ambiguous (e.g., `"around 30 days"`) → returned unchanged

Safety contract: never raises, never modifies the string except when certain.

### `resolve_truth(store, weighted_facts)`
**Module:** `src/claim_layer/semantic/truth.py`

Groups weighted fact entries by `(entity, predicate, canonical_value)`. Groups with the same `canonical_value` are merged before contradiction counting. For each canonical group:

1. Deduplicates evidence by `source` (document_id) — keeps highest-score item per source.
2. Computes `noisy_or` over selected scores within the group.
3. Merges evidence from all raw values that share the same `canonical_value`.
4. If multiple distinct canonical values exist, applies a uniform penalty `1/N`.
5. Selects the candidate with highest adjusted confidence. Tiebreaker: `canonical_value` ascending (deterministic).
6. Preserves the original `value` string of the first raw form seen.

Output:
```python
[{
    "entity": str,
    "predicate": str,
    "value": str,              # original surface form (first seen for this canonical_value)
    "canonical_value": int | str,
    "confidence": float,
    "confidence_explanation": {...},
    "contradictions": [{"value": str, "canonical_value": int | str, "confidence": float}],
    "supporting_evidence": [...],
    "alternative_evidence": [{"value": str, "canonical_value": int | str, "evidence": [...]}]
}]
```

### `ask(store, project_id, query, top_k=20)`
**Module:** `src/claim_layer/api/query.py`

Thin orchestration layer. Executes the pipeline in strict order. Returns early if `hits` or `grouped` is empty. Introduces no SQL queries, transformations, or side effects of its own.

Output:
```python
{"query": str, "results": [...]}  # results is the output of resolve_truth
```

---

## Supporting Infrastructure

### `VectorIndex`
**Module:** `src/claim_layer/semantic/index.py`

In-memory cosine similarity index. Loads claim vectors lazily from `get_claims_with_embeddings()` on first search. Vectors are stored as JSON TEXT in `claims.embedding`. Dimensionality is fixed to the first valid vector loaded; subsequent vectors with mismatched dimensions are silently skipped. Provides `invalidate()` to force reload after new ingestion.

### `embed(text: str) -> List[float]`
**Module:** `src/claim_layer/semantic/embeddings.py`

Stub implementation. Returns `[]`. Replace the function body with a real provider call without changing the signature. Used in `semantic_search` for query embedding and optionally during ingestion for claim embedding.

### `ClaimLayerStore`
**Module:** `src/claim_layer/store.py`

SQLite-backed store. Accepts `enable_semantic: bool = False` (keyword-only). When enabled, calls `embed(claim.text)` after each claim insert and persists non-empty vectors to `claims.embedding`. All semantic modules access the store via its public methods and `_conn()`.

---

## Design Principles

### Separation of concerns
Each pipeline stage has exactly one responsibility:
- `semantic_search` — vector retrieval
- `hybrid_search` — SQL-based fact grouping
- `weight_evidence` — evidence scoring
- `resolve_truth` — truth aggregation and contradiction handling
- `ask` — orchestration only

No stage performs work belonging to another.

### Determinism
All outputs are deterministic given the same inputs and DB state. Ordering is explicit at every stage: similarity DESC in `semantic_search`, score DESC + claim_id ASC in evidence sorting, confidence DESC + value ASC as tiebreaker in `resolve_truth`, entity + predicate ASC in final output. No randomness is introduced at any point.

### Explainability
Every resolved truth value carries a full evidence trace:
- which claims supported it (`supporting_evidence`)
- which claims supported competing values (`alternative_evidence`)
- what the competing values were and their adjusted confidence (`contradictions`)

Confidence scores are always derivable from the raw inputs.

### Query-aware truth
Similarity scores from the vector search propagate through `weight_evidence` into the final `score = confidence × similarity`. A high-confidence claim that is semantically irrelevant to the query receives a lower score than a moderately confident but highly relevant one. Truth resolution is therefore sensitive to the query, not just to stored confidence values.

---

## Known Limitations (Deferred)

### Evidence Overcounting
`noisy_or` assumes statistical independence between evidence items. When multiple claims originate from the same document, paragraph, or extraction run, this assumption is violated and confidence is inflated. Three identical claims from the same source produce nearly the same effect as three independent confirmations.

### Flat Confidence Model
Claim confidence is stored as a single float with no source-quality model behind it. There is no distinction between confidence derived from an authoritative primary source versus an unverified secondary reference, nor any recency decay.

### Partial Value Normalization (v0.3)
Deterministic numeric normalization collapses values like `"30 days"` and `"thirty days"` to the same `canonical_value` before grouping. However, this does not cover:
- Language variants (`"30 días"`)
- Approximate expressions (`"around 30 days"`)
- Semantic equivalences that require embedding-level similarity

These remain as distinct values and may produce spurious contradictions. Full semantic normalization requires fact-level embeddings (deferred).

### canonical_value Unit Collision
`normalize_value()` extracts the leading integer and discards the unit. This means `"30 days"` and `"30 euros"` both produce `canonical_value = 30`. If two facts with the same `(entity, predicate)` differ only in unit (e.g., one value is a duration and another is a currency amount), they will be incorrectly merged into the same canonical group instead of being surfaced as contradictions.

**Fix (future):** Normalize to `(quantity, unit)` tuples rather than bare integers, e.g., `(30, "days")` vs `(30, "euros")`. This requires unit extraction and normalization (deferred).

### Claim-Level Retrieval Granularity
Retrieval operates at claim-level granularity. A claim may contain multiple facts, not all relevant to the query. When `semantic_search` retrieves a claim because it matches one of its facts, `hybrid_search` will include **all** facts linked to that claim — including unrelated ones.

Example: a claim `"ACME pays in 30 days and invoices are monthly"` supports both `payment_term = 30 days` and `billing_cycle = monthly`. A query about billing cycle retrieves the claim, which pulls in the payment term fact as noise.

This is not a bug — it is a consequence of indexing at claim level rather than fact level. Fix: move embeddings to the `facts` table and compute vectors from `f"{entity} | {predicate} | {value}"` triples. This is backlog item: Fact-level indexing (→ affects G5).

### Claim-Level Indexing
Embeddings are computed from `claim.text`, which is a coarse granularity. One claim may contain multiple facts. The unit of semantic truth is a fact (`entity + predicate + value`), not a claim. Embedding at the fact level would require moving the `embedding` column to the `facts` table and computing the vector from the canonical string `f"{entity} | {predicate} | {value}"`.

---

## Planned Improvements

### Evidence clustering
Deduplicate evidence before aggregation by grouping claims with the same `document_id` and `paragraph_id`. Keep one representative per cluster or apply a discount factor to correlated sources before passing to `noisy_or`.

### Confidence modeling
Introduce a source-quality dimension to confidence: document tier, extraction method reliability, claim recency. Replace the flat float with a weighted scoring function upstream of `weight_evidence`.

### Semantic value normalization (partially implemented in v0.3)
Deterministic numeric normalization is active: `normalize_value()` maps English number words and leading integers to a canonical `int`. Values that normalize to the same `int` are merged before grouping — no contradiction is surfaced. Remaining gap: language variants, approximate expressions, and embedding-based equivalence are deferred to a future version.

### Hybrid search optimization
Pass `hits` from `semantic_search` into `hybrid_search` as a filter. Only return fact groups whose `supporting_claim_ids` intersect with the hit set. This removes query-irrelevant groups from the resolution pipeline.

### Fact-level indexing
Migrate `embedding` from `claims` to `facts`. Compute vectors from `f"{entity} | {predicate} | {value}"`. Update `VectorIndex` to operate on `fact_id` instead of `claim_id`. This aligns the semantic retrieval unit with the truth resolution unit.
