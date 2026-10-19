# Evidence Intelligence Skill v2.0 (Evaluation Package)

Proprietary material. See `LEGAL_NOTICE.txt` before use.

## 1. Directory Structure

```
evidence-intelligence/
├── SKILL.md                  v2.0 Instructions, epistemic closure, and structured prompts
├── examples/
│   └── complete_pipeline.py  5-phase end-to-end pipeline (with deterministic offline demo mode)
├── LEGAL_NOTICE.txt          Ownership, licensing terms, and usage scope
└── README.md                 This file
```

## 2. Installing the Skill into Your Agent

Copy the `evidence-intelligence` folder into your agent's skills directory:

- **Gemini CLI / Antigravity:** `~/.gemini/config/skills/evidence-intelligence`
- **Claude Code:** `~/.claude/skills/evidence-intelligence`
- **Google Research Harness² / OpenCode:** Include in the harness tree (`c5: skills/`)

Restart the agent. The skill activates automatically when requesting Evidence Intelligence implementations.

## 3. Running the Reference Pipeline (v2.0)

Requirements: Python 3.9 or higher.

### Immediate Deterministic Run (No API Key Required)
The script includes an offline deterministic demonstration of all v2.0 modules (`ClaimConsolidator`, `EpistemicJudge`, `OriginTier`, `DependencyGraph` with Gödel's T-Norm, and `AggregationEngine` with periodic payment disambiguation):

```bash
python examples/complete_pipeline.py --demo
```

### Full Run with Live LLM Extraction & Inference
```bash
pip install openai
export OPENAI_API_KEY="your-api-key"
python examples/complete_pipeline.py
```

### Quick Verification of `ClaimLayer` v2.0

```python
from claimlayer import ClaimLayer
cl = ClaimLayer()
cl.ingest([
    "ACME payment terms are 30 days",
    "ACME payment terms are thirty days",
    "ACME payment terms are 45 days",
])
print(cl.ask("What are the payment terms for ACME?"))
```

This unifies `"30 days"` and `"thirty days"` (and any LLM-supported language, e.g. French *"trente jours"*, German *"dreißig Tage"*, or written amounts like *"one hundred forty-two thousand euros"*) under canonical value `30`, accumulates confidence via Noisy-OR with **0 ms query-time latency**, flags `"45 days"` as a penalized contradiction with an auditable explanation, and returns structured citations (`[input_0.txt, Page 1, Paragraph p1]`).

> **License:** Business Source License 1.1 (BSL 1.1). Evaluation and non-production use is free; production use requires an explicit commercial license. Converts to MPL 2.0 on 2030-03-31. See the root `LICENSE` file.

## 4. Key Guarantees Verified in v2.0

1. **Typed Ontological Extraction & Contextual Consolidation (`ClaimConsolidator`):** Extracts `fact`, `petitum`, `grounds`, and `evidence` claims, normalizing values across languages at ingestion time, resolving entity coreference and predicate aliases without query overhead.
2. **Decoupled Epistemic Judge (`EpistemicJudge`) & Monotonic Closure:** Guarantees that the LLM cannot self-certify. All inferences require verified premises (`premises: ["c1", "c2"]`) and automatically blocks unilateral unverified allegations.
3. **Deterministic Contradiction Resolution via `OriginTier`:** Enforces `PRIMARY_DOCUMENT (100) > SECONDARY_ANNEX (50) > EXTERNAL_INJECTED (10)`.
4. **Multihop Reasoning & Unit-Isolated Aggregation (`AggregationEngine`):** Executes 3-hop reasoning via Gödel T-Norm Dijkstra search, isolates currencies/units (`EUR` vs `USD` vs `DAYS`), and preserves periodic payment installments (`Q1`, `Q2`, `Q3`).
5. **Cryptographic Traceability (100% Citations):** Issues tamper-evident Merkle SHA-256 certificates with Jøsang subjective logic opinions $\omega=(b,d,u)$.
