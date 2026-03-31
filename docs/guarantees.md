# Evidence Intelligence — System Guarantees

**Version:** v0.3
**Enforced by:** `tests/invariants/test_system_guarantees.py`
**Defined in:** `docs/architecture.md` — "System Guarantees" section

---

## Guarantees

### G1 — Deterministic output for identical inputs
Given the same query, store state, and pipeline inputs, the system always produces identical outputs. No randomness is introduced at any stage. Ordering is explicit and stable at every step.

### G2 — All returned values are supported by explicit evidence
Every resolved truth value in the output is backed by at least one `supporting_evidence` entry with a traceable `claim_id` that exists in the database. The system never returns a value without a source.

### G3 — Contradictions are always surfaced, never hidden
When multiple distinct **canonical values** exist for the same `(entity, predicate)`, all competing values appear in `contradictions` and `alternative_evidence`. No conflict is silently resolved or discarded.

**Canonical grouping (added in v0.3):** Values are normalized via `normalize_value()` before contradiction detection. Two raw values that produce the same `canonical_value` (e.g., `"30 days"` and `"thirty days"` both → `30`) are merged into a single candidate and do **not** appear as contradictions. Values that cannot be deterministically normalized (e.g., `"around 30 days"`) retain their original string as `canonical_value` and are treated as distinct candidates.

**Changed from v0.2:** Previously, every distinct raw string was a separate candidate. Now, candidates are counted at the `canonical_value` level. The contradiction set may be smaller when normalization applies.

### G4 — Confidence is derived from aggregated NON-REDUNDANT evidence (no model guessing)
The `confidence` field in every output is computed from deduplicated evidence only:

**Deduplication (applied before aggregation):**
Evidence items within a fact group are deduplicated by source (`document_id`). When multiple claims from the same document support the same `(entity, predicate, value)`, only the one with the highest `score` is selected for aggregation. All items are retained in the output with `selected: true/false` and `reason: "duplicate"` for discarded ones.

**Redundancy definition:** Two evidence items are redundant when they share the same `source` (document_id) within the same `(entity, predicate, value)` group. The same fact repeated across chunks of the same document is redundant; the same fact attested by two *different* documents is not.

**Independence definition:** Two pieces of evidence are considered independent if and only if they originate from different `document_id`s. This is the boundary at which deduplication stops and confidence accumulation begins.

**Limitation of this definition:** This definition does not guarantee true independence at the content level. Multiple documents may contain identical information — for example, the same contract duplicated across two PDFs, or the same paragraph re-indexed under a different filename. In such cases, the system will treat the evidence as independent and confidence will be accumulated, potentially overstating certainty. Content-level deduplication (hash-based or embedding-based) is a known limitation deferred to a future version.

**Scoring formula (applied to selected evidence only):**
```
score             = confidence × similarity
aggregated        = noisy_or([score for ev in evidence if ev.selected])
penalty           = 1 / N  (where N = number of distinct values for the predicate)
final_confidence  = aggregated × penalty
```
This value is fully derivable from the raw inputs. It is not a model output, a heuristic guess, or an opaque score. Duplicate evidence does NOT increase confidence.

**Changed from v0.1:** Previously, all evidence items were passed to `noisy_or` regardless of source, causing confidence inflation when the same fact appeared multiple times from the same document.

### G5 — Query-aware truth (similarity affects resolution)
The query used to retrieve claims propagates through `weight_evidence` as similarity scores. A high-confidence claim that is semantically irrelevant to the query contributes less to the resolved truth than a lower-confidence but highly relevant one. Truth resolution is always sensitive to the query.

### G6 — No generative step in truth resolution (no hallucination in output values)
The resolution pipeline contains no LLM, generative model, or inference step. Every value in the output — including winning values, contradiction values, and alternative values — originates from an explicitly ingested document. The system cannot produce values absent from the source data.

---

## Change Policy

If a change to the codebase causes any test in `tests/invariants/test_system_guarantees.py` to fail:

- **This is NOT a test issue.**
- **This indicates a change in system semantics.**

### Required actions before merging

1. Identify which guarantee(s) are affected.
2. Update the guarantee description in this document to reflect the new behavior.
3. Update `docs/architecture.md` — "System Guarantees" section if needed.
4. Update or replace the failing invariant test(s) to enforce the new guarantee.
5. Bump the version of this document (`v0.X → v0.Y`).
6. Document the change explicitly in the guarantee entry: what changed, why, and what the previous behavior was.

### What counts as a guarantee change

| Change | Guarantee affected |
|---|---|
| Evidence deduplication (same source) | G4 — confidence values will differ |
| Source-aware confidence weighting | G4 — formula changes |
| Semantic value normalization | G3 — fewer contradictions surfaced (implemented v0.3) |
| Filtering hybrid_search by hits | G1, G2 — output set may shrink |
| Fact-level embeddings | G5 — similarity computation unit changes |

---

## Planned Evolution

Future versions may modify guarantees through the following improvements. Each change must explicitly state how it alters truth computation before being merged.

**Evidence deduplication (→ affects G4)**
Claims from the same `document_id` / `paragraph_id` will be clustered before aggregation. `noisy_or` will operate on deduplicated or discount-weighted scores. Aggregated confidence will decrease for correlated sources.

**Source-aware confidence modeling (→ affects G4)**
The flat `confidence` float will be replaced or supplemented by a source-quality model. The scoring formula will change to account for document tier, recency, and extraction reliability.

**Semantic value normalization (→ affects G3) — implemented in v0.3**
`normalize_value()` maps English number words and leading integers to a canonical `int` before grouping. `"30 days"` and `"thirty days"` both normalize to `30` and are merged into a single candidate. Fewer contradictions are surfaced. Remaining gaps: language variants, unit-aware normalization (see below), and embedding-based equivalence are deferred.

**Unit-aware canonical values (→ affects G3) — deferred**
`normalize_value()` discards units: `"30 days"` and `"30 euros"` both produce `canonical_value = 30`. Values differing only in unit may be incorrectly merged. Fix: normalize to `(quantity, unit)` tuples, e.g., `(30, "days")` vs `(30, "euros")`. This will change which values are considered equivalent and which are surfaced as contradictions.

**Hybrid search optimization (→ affects G1, G2) — implemented**
`hybrid_search` now accepts `hits` and filters `AND f.claim_id IN (...)` when provided. Fact groups with no overlap with the hit set are excluded from resolution. The output set is smaller and query-relevant.

**Fact-level embeddings (→ affects G5)**
Embeddings will be computed from `f"{entity} | {predicate} | {value}"` triples instead of claim text. Similarity scores will reflect fact-level relevance rather than claim-level relevance, changing which values are considered query-aware.
