# ClaimLayer

[![DOI](https://zenodo.org/badge/1192448844.svg)](https://doi.org/10.5281/zenodo.19489455)

**Deterministic truth engine for reasoning over unstructured data.**

ClaimLayer is a source-available implementation of the **Evidence Intelligence** paradigm, licensed under the conditions in [LICENSE](./LICENSE):
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
python -m pip install "claim-layer @ git+https://github.com/mathmentorAI/claim-layer.git@v2.0.1"
```

The distribution name is `claim-layer`; the Python import is `claimlayer`.
This command installs the tagged GitHub release and requires Git. A PyPI
release is not currently provided. For local development, clone the repository
and run `python -m pip install '.[dev]'` from its root.

Version 2.0.1 rejects unchecked derivations and separates compatible or unknown
alternatives from contradictions. See the [release notes](./CHANGELOG.md) and
[evidence contracts](./docs/evidence_contracts.md) for migration details.

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

## 📊 Empirical Evaluation on Harvey Legal Agent Benchmark (LAB)

We evaluated **ClaimLayer / Deltoryx** on four multi-document tasks from the **[Harvey Legal Agent Benchmark (LAB)](https://github.com/harveyai/harvey-labs)** (`b58a28a`), comprising **20 source documents** and **199 official rubric criteria**, under two complementary protocols:
1. **Study A — Controlled Direct LLM Tool-Calling (No Agent Harness, No `bash`):** Isolates the information-retrieval and evidence-structuring layer by giving the exact same LLM (`nvidia/nemotron-3-super-120b-a12b`), identical 650-character system prompt, identical 5-tool-call budget, identical `pandoc` `.docx` packaging, and a single uniform judge across all 4 tasks (`nvidia/nemotron-3-super-120b-a12b`) either standard BM25 chunk retrieval tools (`direct_rag`) or ClaimLayer/Deltoryx structured evidence & diff tools (`direct_claimlayer`).
2. **Study B — Autonomous Agent Harness Integration (`OpenCode` / `Harness²` `c5`+`c7`):** Compares the base `LAB/OpenCode` (`v1.14.18`, `tool_mode="base"`, `openai/gpt-4.1`) agent against an augmented harness component tree.

### Study A: Controlled Direct LLM Tool-Calling (`direct_rag` vs. `direct_claimlayer`, No `bash`)

| Task | Docs | Criteria | `direct_rag` (Chunk Search Tools) | `direct_claimlayer` (Evidence & Diff Tools) | Difference (pp) | Criterion Transitions | Oracle Union |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Litigation** (`analyze-counterparty-motion-to-dismiss`) | 6 | 34 | 26 (`76.47%`) | **27 (`79.41%`)** | **`+2.94`** | `+3 / -2` | 29 (`85.29%`) |
| **Structured Finance** (`compare-offering-memorandum-against-indenture`) | 3 | 37 | 11 (`29.73%`) | **11 (`29.73%`)** | **`+0.00`** | `+0 / -0` | 11 (`29.73%`) |
| **Corporate M&A** (`analyze-counterparty-spa-markup`) | 6 | 62 | 13 (`20.97%`) | **32 (`51.61%`)** | **`+30.65`** | **`+23 / -4`** | 36 (`58.06%`) |
| **Banking & Finance** (`analyze-counterparty-markup-of-senior-secured-credit-facility-term-sheet`) | 5 | 66 | 23 (`34.85%`) | **53 (`80.30%`)** | **`+45.45`** | **`+30 / -0`** | 53 (`80.30%`) |
| **Total (Pooled, Single Judge)** | **20** | **199** | **73 (`36.68%`)** | **123 (`61.81%`)** | **`+25.13`** | **`+56 / -6`** | **129 (`64.82%`)** |

> 💡 **Why Study A Matters (Isolating the Evidence Layer from Agent `bash` & Prompt Confounds):**
> - **Eliminates Harness & Packaging Confounds:** Both arms share the exact same system prompt, tool-call budget (5 tool calls + 1 synthesis call), `.docx` container pipeline, and judge (`nvidia/nemotron-3-super-120b-a12b`), removing shell exploration variance and container-repair artifacts.
> - **`+25.13 pp` Gain with Minimal Regressions (`+56 / -6`):** Equipping the LLM with full-document structured claim units (`OriginTier` authority ranks, section/quantitative tags, and deterministic clause-by-clause diffs) raises passed criteria from **73/199 (`36.68%`)** to **123/199 (`61.81%`)**, including **53/66 (`80.30%`, `+30 / -0`)** in *Banking & Finance* and **32/62 (`51.61%`, `+23 / -4`)** in *Corporate M&A*.
> - **Context Volume Trade-off:** Because `direct_claimlayer` returns denser structured evidence (full source-hierarchy overview, controlling playbooks/tables, and redline diff matrices), total solver tokens increase from **142,756** (`direct_rag`) to **640,546** (`direct_claimlayer`).

### Study B: Autonomous Agent Harness Integration (`OpenCode` / [`google-research/harness2`](https://github.com/google-research/harness2), `openai/gpt-4.1`)

| Task | Docs | Criteria | Base Agent Passed | Augmented Agent Passed | Difference (pp) | Criterion Transitions | Judge |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Litigation** (`analyze-counterparty-motion-to-dismiss`) | 6 | 34 | 1 (`2.94%`) | **19 (`55.88%`)** | **`+52.94`** | `+18 / -0` | GPT-4.1 |
| **Structured Finance** (`compare-offering-memorandum-against-indenture`) | 3 | 37 | 3 (`8.11%`) | **12 (`32.43%`)** | **`+24.32`** | `+10 / -1` | Nemotron |
| **Corporate M&A** (`analyze-counterparty-spa-markup`) | 6 | 62 | 15 (`24.19%`) | **24 (`38.71%`)** | **`+14.52`** | `+12 / -3` | Nemotron |
| **Banking & Finance** (`analyze-counterparty-markup-of-senior-secured-credit-facility-term-sheet`) | 5 | 66 | 43 (`65.15%`) | **44 (`66.67%`)** | **`+1.52`** | `+13 / -12` | GPT-4.1 |
| **Total (Pooled)** | **20** | **199** | **62 (`31.16%`)** | **99 (`49.75%`)** | **`+18.59`** | **`+53 / -16`** | Mixed (Paired) |

> 💡 **Methodological Notes on Study B:**
> - **Paired Criterion Gain (`+18.59 pp`) & Complementarity:** After `.docx` container repair, the augmented workflow passes **99/199 (`49.75%`)** vs. **62/199 (`31.16%`)** (`+53` gained, `-16` lost; solver tokens rise from `220,320` to `388,406`, `+76.3%`). A post-hoc **oracle criterion union** across both arms reaches **115/199 (`57.79%`)** overall and **56/66 (`84.85%`)** in *Banking & Finance* (distinguished from a whole-deliverable selector, which is capped at `99/199`).
> - **Why Study A Outperformed Study B on Banking (`53/66` vs. `44/66`):** In Study B, the legacy `deltoryx_audit.py` script truncated claim indexing at 80 paragraphs per document (`paragraphs[:80]`) and the `bash` agent split focus between playbook headings and shell scripts (`+13 / -12`). Indexing all document paragraphs and exposing structured tools directly in Study A eliminated the 12 criterion losses (`+30 / -0`).

📄 **Benchmark Documentation & Replication:**
- 📑 [Technical Benchmark Report (PDF)](./docs/Harvey_LAB_Benchmark_Experiment_ClaimLayer.pdf)
- 📄 [Technical Benchmark Report (Word)](./docs/Harvey_LAB_Benchmark_Experiment_ClaimLayer.docx)
- 📊 [Complete Benchmark Writeup & Audit Notes (Markdown)](./docs/harvey_lab_benchmark.md)
- 💻 [Direct Tool-Calling Benchmark Runner (Study A)](./benchmarks/run_direct_tool_benchmark.py)
- 💻 [OpenCode Harness A/B Runner (Study B)](./benchmarks/run_ab_benchmark.py)

---

## 🤖 Agent Integration: Evidence Intelligence Skill

ClaimLayer v2.0 includes a production-grade agent skill located in [`skills/evidence-intelligence/`](./skills/evidence-intelligence/) designed to equip coding assistants and autonomous agents with deterministic evidence verification.

### Supported Agent Frameworks
You can install the skill by copying [`skills/evidence-intelligence`](./skills/evidence-intelligence) directly into your agent's skills directory:
- **Claude Code:** `~/.claude/skills/evidence-intelligence`
- **Gemini CLI / Antigravity:** `~/.gemini/config/skills/evidence-intelligence`
- **Google Research Harness² / OpenCode:** Include in the harness component tree (`c5: skills/`)

### Try the Offline Deterministic Demo (No API Key Required)
You can test the complete 5-stage Evidence Intelligence pipeline immediately using the built-in deterministic demo:

```bash
# Clone the repository
git clone https://github.com/mathmentorAI/claim-layer.git
cd claim-layer

# Run the full offline verification pipeline
python skills/evidence-intelligence/examples/complete_pipeline.py --demo
```

This runs an end-to-end verification showing:
1. **`ClaimConsolidator`**: Prunes layout noise and normalizes multilingual values (*"30 days"* vs *"trente jours"*).
2. **`EpistemicJudge`**: Detects and blocks unverified party allegations and enforces monotonic truth closure.
3. **`OriginTier`**: Deterministically resolves source precedence (Governing Agreement > Amendment > Emails).
4. **`DependencyGraph`**: Executes 3-hop Dijkstra Max-Min inference over Gödel's T-Norm.
5. **`AggregationEngine`**: Isolates currencies and units without scalar hallucinations.
6. **Merkle SHA-256 Certificates**: Generates a tamper-proof cryptographic audit trail.

### Running with a Live LLM (OpenAI / Gemini / Claude)
```bash
pip install openai
export OPENAI_API_KEY="your-api-key"
python skills/evidence-intelligence/examples/complete_pipeline.py
```

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
