# ClaimLayer

[![DOI](https://zenodo.org/badge/1192448844.svg)](https://doi.org/10.5281/zenodo.19489455)

**Deterministic truth engine for reasoning over unstructured data.**

ClaimLayer is the open-source implementation of the **Evidence Intelligence** paradigm:
a computational layer that transforms unstructured text into **structured, auditable, and contradiction-aware knowledge**.

---

## Why ClaimLayer

Most AI systems today follow this pattern:

```
Data → Retrieval (RAG) → LLM → Answer
```

This has a fundamental limitation:

- No explicit representation of truth
- No knowledge state
- No contradiction handling
- No auditability

ClaimLayer introduces the missing layer:

```
Data → Retrieval → ClaimLayer → Deterministic Knowledge → LLM (optional)
```

Instead of generating answers from text, ClaimLayer:

- Constructs **evidence units**
- Tracks **source-level provenance**
- Detects **contradictions as first-class objects**
- Computes **confidence mathematically**
- Maintains an explicit **epistemic state (Eₜ)**

---

## Core Concept

Knowledge is not generated.
It is computed from evidence.

```
Kₜ = F(Eₜ)
```

Where:

- **Eₜ** = set of evidence units extracted from documents
- **Kₜ** = resulting knowledge state

---

## Installation

```bash
pip install claimlayer
```

---

## Quickstart (30 seconds)

```python
from claimlayer import ClaimLayer

cl = ClaimLayer()

cl.ingest([
    "ACME payment terms are 30 days",
    "ACME payment terms are thirty days",
    "ACME payment terms are 45 days"
])

result = cl.ask("What are the payment terms for ACME?")
print(result)
```

---

## What happens under the hood

- `"30 days"` and `"thirty days"` are merged into a canonical value
- `"45 days"` is detected as a contradiction
- Confidence is penalized based on conflicting evidence
- All outputs are traceable to their original sources

---

## 🏆 Empirical Validation: Harvey Legal Agent Benchmark (Google Research Harness²)

To empirically prove that deterministic epistemic grounding fundamentally outperforms probabilistic test-time search, ClaimLayer was evaluated on the **Harvey Legal Agent Benchmark (LAB)**—an official multi-document legal reasoning suite released with Google Research's [Harness²](https://github.com/google-research/harness2).

The evaluation spans 4 practice areas (*Banking & Finance*, *Corporate*, *Employment*, and *Real Estate*), 20 real-world commercial contracts (40–150 pages), and 199 official rubric evaluation criteria scored by the strict `evaluation.run_eval` benchmark judge.

### Benchmark Results

| System Configuration | Strict LAB Score | % Rubric Passed | Banking & Finance | Relative Gain |
| :--- | :---: | :---: | :---: | :---: |
| **Harness² Baseline (Official Google Agent)** | 47 / 199 | **23.62%** | 33.33% | *Reference* |
| **Harness² + ClaimLayer ($k=1$)** | 106 / 199 | **53.27%** | 68.18% | **+126% (+29.65 pp)** |
| **Harness² + ClaimLayer ($k=2$)** | 122 / 199 | **61.31%** | **84.85%** | **+159% (+37.69 pp)** |
| *Published Google Harness² ($k=5$)* | - | - | *84.50%* | *Reference ($5\times$ compute)* |

> 💡 **Key Takeaway:** At $k=2$, ClaimLayer matches and outperforms Google's published $k=5$ score in Banking & Finance while requiring **over 60% less test-time inference compute** and eliminating non-monotonic contract hallucinations.

### Why Standard RAG and GraphRAG Collapse Here

A common misconception is that legal contract analysis is an open-domain "retrieval" problem. It is not:
- **The Non-Monotonicity Trap:** When an amendment overrides a master agreement clause, semantic similarity (vector embeddings / GraphRAG) assigns nearly identical relevance scores to both the obsolete draft and the governing amendment. The LLM invariably confuses historical terms with active commitments.
- **ClaimLayer's Deterministic Solution:** ClaimLayer enforces an explicit `OriginTier` source hierarchy and monotonic truth maintenance (JTMS). Amendments deterministically supersede prior clauses *before* reasoning occurs, guaranteeing legal defensibility without relying on brute-force multi-agent sampling.

📄 **Full Benchmark Reports & Documentation:**
- 📑 [Full Technical Report (PDF)](./docs/Informe_Experimento_Harvey_LAB_Deltoryx_v2.pdf)
- 📄 [Full Technical Report (Word)](./docs/Informe_Experimento_Harvey_LAB_Deltoryx_v2.docx)
- 📊 [Complete Benchmark Writeup (Markdown)](./docs/harvey_lab_benchmark.md)
- 💻 [Replication Runner Script](./benchmarks/run_ab_benchmark.py)

---

## Embeddings (Important)

ClaimLayer **does not depend on embeddings as a core mechanism**.

Embeddings are:

- Optional
- Replaceable
- Used only as a retrieval signal

By default, ClaimLayer uses a **simple deterministic embedding** for zero-setup usage.

> ⚠️ For production, provide your own embedding provider:

```python
cl = ClaimLayer(embedding_provider=MyEmbeddingProvider())
```

---

## Architecture

ClaimLayer is designed with strict separation of concerns:

**Core (`claim_layer/`)**
- Deterministic reasoning engine
- Evidence modeling
- Contradiction detection
- Confidence computation (Noisy-OR)

**Public API (`claimlayer/`)**
- User-facing interface
- Embedding provider integration

This ensures:

- Stability of the reasoning model
- Replaceable infrastructure (LLMs, embeddings)
- Full auditability

---

## Key Features

- Evidence Units: `(claim, source, confidence, metadata)`
- Source-level provenance (paragraph-level)
- Explicit contradiction detection
- Mathematical confidence aggregation
- Deterministic reasoning (no hallucinations)
- Snapshot-based knowledge state (Eₜ)

---

## Limitations (Current Version)

- Retrieval operates at **claim-level granularity**
- A claim may contain multiple facts not fully disentangled
- Ingestion embedding uses a **temporary scoped override** (not concurrency-safe)

Planned:

- Fact-level indexing
- Explicit dependency injection for ingestion
- Distributed ingestion pipeline

---

## Philosophy

> AI systems should not guess truth.
> They should compute it.

---

## Positioning

- RAG → retrieves text
- LLMs → generate answers
- ClaimLayer → constructs and reasons over evidence

---

## Use Cases

- Legal due diligence (contract contradiction detection)
- Healthcare / clinical protocol analysis
- Financial compliance & audit trails
- Any domain where decisions must be **defensible**

---

## Roadmap

- Fact-level reasoning
- Multi-document aggregation at scale
- Evidence graph queries
- Enterprise-grade ingestion pipelines

---

## Contributing

We welcome contributions, but the core principles are strict:

- Determinism over heuristics
- Explicit evidence over implicit reasoning
- Auditability over convenience

---

## License

This project is licensed under the **Business Source License 1.1 (BSL 1.1)**.

- Free for non-production, testing, and evaluation use (local development, PoC, academic research)
- Any use in a Production Environment (including internal use for real business operations) requires an explicit commercial license
- Building competing products in Evidence Intelligence, AI verification, or RAG auditing is strictly prohibited

On **2030-03-31**, the license automatically converts to **MPL 2.0** (Mozilla Public License 2.0).

For full terms, see the [`LICENSE`](LICENSE) file.

**Why BSL?**

ClaimLayer is not a typical library. It is the core of a new category: Evidence Intelligence.

We believe in open access to the technology, but we also need to protect the integrity of the system and prevent extractive reuse by large platforms.

If you are interested in commercial licensing or partnerships, please contact us.

---

## Final Note

This is not a better RAG system.
This is a different layer.

**Evidence Intelligence starts here.**
