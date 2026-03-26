# claim-layer

`claim-layer` is the reusable Python core for Claim Layer's Evidence Intelligence architecture.

It gives you a portable evidence store built on SQLite so any project can ingest structured evidence, keep provenance, detect contradictions, and query an evolving evidence state without depending on this repository's FastAPI app, workspace layout, or frontend.

## What This Package Is For

Use this package when you want to:

- ingest normalized evidence from any pipeline
- persist documents, entities, claims, facts, and source snippets
- query evidence by entity and fact type
- track contradictions across sources
- materialize evidence snapshots over time
- derive graph views and higher-level knowledge summaries

This package is a core library. It is not an app server, not a UI kit, and not tied to a specific LLM provider.

## What It Includes

- SQLite-backed `ClaimLayerStore`
- dataclasses for normalized ingestion payloads
- entity aliasing and light deduplication
- evidence state snapshots and deltas
- contradiction detection
- provenance and paragraph indexes
- evidence graph helpers
- derived knowledge and confidence accumulation queries

## What It Does Not Include

- FastAPI routes
- auth
- frontend components
- conversation storage
- narrative UI logic
- report export specific to this repo
- LLM-bound verification workflows

## Installation

From a local path:

```bash
pip install /path/to/claim-layer
```

From Git:

```bash
pip install "claim-layer @ git+ssh://git@github.com/ORG/claim-layer.git"
```

If your environment uses an older `pip`, prefer a normal install over editable mode.

## Public API

Main entrypoint:

```python
from claim_layer import ClaimLayerStore
```

Constructor:

```python
store = ClaimLayerStore("./data/evidence.db")
```

Main ingestion method:

```python
store.ingest_document(payload)
```

## Data Model

The package expects a normalized document payload with these concepts:

- `project_id`: logical partition key
- `filename`: source document name
- `entities`: known entities for the document
- `claims`: textual claims with confidence and provenance
- `facts`: structured facts linked to claims and entities
- `sources`: provenance snippets inside each fact

Dataclasses exposed by the package:

- `IngestedDocument`
- `IngestedEntity`
- `IngestedClaim`
- `IngestedFact`
- `IngestedSource`

## Minimal Example

```python
from pathlib import Path
from claim_layer import ClaimLayerStore, IngestedDocument

store = ClaimLayerStore(Path("./evidence.db"))

payload = IngestedDocument(
    project_id="demo",
    filename="contract.pdf",
    entities=[
        {"entity_id": "acme", "name": "Acme Corp", "entity_type": "organization"},
    ],
    claims=[
        {
            "claim_id": "c1",
            "text": "Acme Corp agrees to pay $50,000.",
            "confidence": 0.91,
            "page": 3,
            "paragraph_id": "0002",
        }
    ],
    facts=[
        {
            "claim_ref": "c1",
            "entity_ref": "acme",
            "fact_type": "payment_amount",
            "value": "$50,000",
            "sources": [
                {"page": 3, "paragraph_id": "0002", "text": "Acme Corp agrees to pay $50,000."}
            ],
        }
    ],
)

store.ingest_document(payload)
result = store.query_evidence("demo", "Acme Corp", "payment_amount")
print(result["candidate_values"])
```

## Accepted Input Shapes

You can ingest either:

- package dataclasses
- plain dictionaries with equivalent fields

Example dictionary payload:

```python
payload = {
    "project_id": "demo",
    "filename": "contract.pdf",
    "entities": [
        {"entity_id": "acme", "name": "Acme Corp", "entity_type": "organization"},
    ],
    "claims": [
        {
            "claim_id": "c1",
            "text": "Acme Corp agrees to pay $50,000.",
            "confidence": 0.91,
            "page": 3,
            "paragraph_id": "0002",
        }
    ],
    "facts": [
        {
            "claim_ref": "c1",
            "entity_ref": "acme",
            "fact_type": "payment_amount",
            "value": "$50,000",
            "sources": [
                {"page": 3, "paragraph_id": "0002", "text": "Acme Corp agrees to pay $50,000."}
            ],
        }
    ],
}

store.ingest_document(payload)
```

## Core Capabilities

Persistence and ingestion:

- `ingest_document`
- `upsert_document`
- `upsert_entity`
- `upsert_entity_with_dedup`
- `insert_claim`
- `insert_fact`
- `insert_fact_source`
- `delete_document_by_filename`

Retrieval and evidence queries:

- `get_entities`
- `get_claims`
- `get_facts`
- `get_contradictions`
- `get_cross_document_entities`
- `get_fact_types_summary`
- `query_evidence`

Evidence state:

- `capture_snapshot`
- `get_state_history`
- `get_evidence_state`
- `compute_delta`
- `get_evidence_units`

Derived intelligence:

- `derive_knowledge`
- `get_confidence_accumulation`
- `detect_gaps`
- `benchmark_facts`

Provenance helpers:

- `get_paragraphs_for_entity`
- `get_paragraphs_for_fact_type`

Graph helpers:

- `get_evidence_graph`
- `get_entity_clusters`
- `get_cluster_facts`

## Storage Model

The SQLite schema stores:

- `documents`
- `entities`
- `claims`
- `facts`
- `fact_sources`
- `entity_aliases`
- `evidence_snapshots`

This makes the package suitable for:

- single-user local apps
- backend services
- test fixtures
- embedded evidence stores per project or per tenant

## Recommended Integration Pattern

For a new project:

1. Build your own extraction pipeline.
2. Normalize its output into the `IngestedDocument` shape.
3. Call `store.ingest_document(...)`.
4. Use the query helpers for API routes, analytics, or reasoning layers.

That keeps your extraction pipeline and your evidence model decoupled.

## Example: Build an API on Top

```python
from fastapi import FastAPI
from claim_layer import ClaimLayerStore

app = FastAPI()
store = ClaimLayerStore("./data/evidence.db")

@app.get("/evidence/query")
def evidence_query(project_id: str, entity: str, fact_type: str):
    return store.query_evidence(project_id, entity, fact_type)
```

## Limits and Current Scope

This package currently assumes:

- a SQLite backend
- normalized ingestion input
- project partitioning by `project_id`
- deterministic persistence and query behavior

If you need:

- Postgres
- vector search
- LLM verification
- report rendering
- multi-service orchestration

those should sit on top of this package, not inside its core store.

## Compatibility

- Python `>=3.9`
- no required third-party runtime dependencies

## Tests

The package includes tests at:

- [tests/test_store.py](./tests/test_store.py)

Run them with:

```bash
PYTHONPATH=src python3 -m pytest tests -q
```

## Versioning Guidance

Treat the following as the stable contract:

- constructor: `ClaimLayerStore(db_path)`
- ingestion: `ingest_document(payload)`
- normalized payload fields
- read/query methods documented above

If you evolve the payload shape, version it deliberately and keep adapters at the project boundary.
