# ClaimLayer · Computable Verification for AI Agents

**Eliminate the 80% human supervision bottleneck ("metawork") without sacrificing safety or auditability.**

AI agents now draft legal analyses, reconcile financials, and propose operational actions at 100× human speed—yet spend up to **80% of wall-clock time idle**, waiting for overwhelmed humans to manually cross-check every citation, number, and amendment against source documents.

**ClaimLayer** is a zero-dependency Python library (~1,200 LoC, pure stdlib) that sits between your AI agent and task completion like a **deterministic `<1 ms` type-checker**, replacing manual post-hoc reading and probabilistic *LLM-as-a-Judge* rollouts with **computable verification (`verify()`)**:

```text
Agent Proposal + Citations ──► ClaimLayer.verify() (<1 ms, 0 LLM calls, 0 external deps)
                                  ├── PASS     ──► Auto-approved + SHA-256 Merkle receipt (Agent continues immediately)
                                  ├── RETRY    ──► Exact error bounced to Agent (Self-corrects with 0 human time)
                                  └── ESCALATE ──► Surgical 15-second side-by-side diff ONLY for genuine conflicts
```

---

## 1. Clone & Verify in 60 Seconds

`claim-layer` uses **only the Python 3.10+ standard library** (`hashlib`, `sqlite3`, `re`, `decimal`, `dataclasses`, `json`).

```bash
git clone https://github.com/mathmentorAI/claim-layer.git
cd claim-layer

# Option A: Editable install (recommended)
pip install -e .

# Option B: Run directly from source with zero pip installs
export PYTHONPATH="$PWD/src"

# 1. Run formal invariant & sandbox E2E test suite (G1–G8, <0.3s)
pytest -v

# 2. Run the 200-task supervision bottleneck benchmark (~17ms total, 85% fewer human interruptions)
python3 benchmarks/verification_bottleneck_bench.py

# 3. Run the Harness² × Harvey LAB Case 1 securitization replay (<2ms, 0 API keys)
python3 examples/harness2_securitization/replay_om_vs_indenture.py
```

---

## 2. How to Implement ClaimLayer in Your Project

Keep your existing LLM (`Claude`, `GPT`, `Gemini`), prompts, and RAG pipeline unchanged. Choose whichever integration matches your stack (full reference & error code catalog in **[`docs/IMPLEMENTATION_GUIDE.md`](./docs/IMPLEMENTATION_GUIDE.md)**):

### Path A · Python Agent Self-Correction Loop (OpenAI / Anthropic / LangGraph)

Ask your agent (via tool-calling or Structured Outputs) to return structured `Assertion` items alongside its draft, and gate completion inside a standard `for` / `while` loop:

```python
from claimlayer import Assertion, FactRecord, Ledger, Policy, Source, verify_receipt

# 1. Register your governing documents & precedence rules once
ledger = Ledger(
    db_path=".claimlayer.sqlite",  # Optional SQLite persistence (omit for pure in-memory)
    sources=[
        Source(
            id="msa_2024",
            text="Section 4.1: ACME shall pay all undisputed invoices within 45 days.",
            tier="standard",          # rank = 50
        ),
        Source(
            id="amendment_2026",
            text="Section 4.1 is hereby amended: ACME shall pay all undisputed invoices within 30 days.",
            tier="authoritative",     # rank = 100
            supersedes=["msa_2024"],
        ),
    ],
    facts=[
        FactRecord(
            subject="ACME",
            predicate="payment_terms",
            value="30 days",
            source_id="amendment_2026",
            quote="ACME shall pay all undisputed invoices within 30 days.",
        )
    ],
)
policy = Policy(policy_id="contract_ops", min_tier_rank=50, required_predicates=["payment_terms"])

# 2. Gate your agent's tool call / structured output in <1 ms
for attempt in range(3):
    proposal = run_your_llm_agent(messages)  # Returns list of Assertion dicts

    verdict = ledger.verify(assertions=proposal, policy=policy, agent_id="contract-agent")

    if verdict.status == "PASS":
        assert verify_receipt(verdict)  # Offline SHA-256 Merkle verification
        break                           # Auto-approved — 0 seconds of human wait!

    if verdict.status == "RETRY":
        # Bounce exact errors back to the LLM — 0 human attention wasted!
        errors = "\n".join(f"- [{i.code}] {i.message} -> {i.remediation}" for i in verdict.issues)
        messages.append({"role": "user", "content": f"Fix verification errors:\n{errors}"})
        continue

    if verdict.status == "ESCALATE":
        # Wake a human ONLY when equally authoritative documents genuinely conflict
        send_to_human_triage(verdict.conflicts)
        break
```

> **Comparing Two Documents (Redlines, Offering Memorandum vs. Indenture)?**
> Call `policy, divergences = build_comparison_policy(primary_doc, secondary_doc)` to automatically populate `policy.required_predicates` with every section where numbers or clauses diverge so the agent cannot stop early.

---

### Path B · MCP Server (`Claude Code`, `Cursor`, `OpenCode`, `Claude Desktop`)

Expose `register_source`, `verify_proposal`, and `check_escalation` over `stdio` JSON-RPC 2.0 by adding this to `.mcp.json` or `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "claimlayer": {
      "command": "python3",
      "args": ["-m", "claimlayer.cli", "mcp", "--db", ".claimlayer.sqlite"],
      "env": {
        "PYTHONPATH": "/absolute/path/to/claim-layer/src"
      }
    }
  }
}
```

Then add to your `CLAUDE.md` or system prompt:
> *"Before finalizing any deliverable, register governing documents with `register_source` and verify all quantitative/contractual claims via `verify_proposal`. Self-correct any `RETRY` issues automatically; only interrupt the human on `ESCALATE`."*

---

### Path C · CLI Gate for Terminal Harnesses (`google-research/harness2`, `SWE-agent`, CI)

Gate shell-based coding or legal agents with deterministic POSIX exit codes (`0` = `PASS`, `2` = `RETRY`, `3` = `ESCALATE`):

```bash
claimlayer verify --bundle proposal.json
```

Because `claimlayer` has zero external dependencies, you can copy `src/claimlayer` directly into air-gapped Docker / OpenCode sandboxes (`scripts/claimlayer/`) with zero `pip install` or network access.

---

## 3. Featured Showcase: `Harness²` × Harvey LAB Case 1

See **[`examples/harness2_securitization/`](./examples/harness2_securitization/)** for a complete integration into **`google-research/harness2`** (`OPENCODE_SURFACE` `c2` + `c6` + `c7`) on Harvey LAB's structured-finance audit workflow (`compare-offering-memorandum-against-indenture`):

- **Turn 1 (`RETRY`, 0 human wait):** Catches premature stopping (`MISSING_REQUIRED_PREDICATE` on skipped Waterfall & Coupon sections) and numeric hallucination (`QUANTITY_MISMATCH`).
- **Turn 2 (`RETRY`, 0 human wait):** Catches **authority inversion** (`HIGHER_TIER_OVERRIDE`) when the agent treats the marketing Offering Memorandum (`6.50%`) as governing over the Executed Master Trust Indenture (`6.75%`).
- **Turn 3 (`PASS`, `<2 ms` total):** Verifies all 4 divergent sections against the controlling Indenture and seals an offline-verifiable `CLAIMLAYER-MERKLE-SHA256-v3` cryptographic receipt.

---

## 4. Formal Verification Guarantees (`G1`–`G8`)

| ID | Invariant | What `claimlayer.verify()` Guarantees |
| :--- | :--- | :--- |
| **`G1`** | **Strict Determinism** | Identical `(assertions, ledger, policy, as_of)` inputs produce byte-identical verdicts and hashes. |
| **`G2`** | **Verbatim Grounding** | Every cited `quote` exists verbatim (whitespace-normalized) inside `Source.text`. |
| **`G3`** | **Quantity, Scale & Unit Integrity** | Normalizes `$500K` == `$500,000`, `thirty (30) days` == `30 days`, and rejects unit drift (`30 EUR` != `30 days`). |
| **`G4`** | **Precedence & Temporal Validity** | Enforces `authoritative` > `standard` > `draft` tiers, `supersedes` chains, and `valid_from` / `valid_until` dates. |
| **`G5`** | **Checklist Completeness** | Blocks completion until all `Policy.required_predicates` and `required_source_ids` are satisfied. |
| **`G6`** | **Non-Redundant Conflict Routing** | Deduplicates per-source citations before Noisy-OR scoring; `RETRY` strictly preempts `ESCALATE` to protect human time. |
| **`G7`** | **Zero-Trust Cryptographic Receipt** | Seals every verdict with an offline-verifiable SHA-256 Merkle root (`verify_receipt(verdict)`). |
| **`G8`** | **Automated Divergence Coverage** | `build_comparison_policy()` auto-extracts divergent clauses across paired documents into `required_predicates`. |

---

## 5. Repository Structure

```text
├── src/claimlayer/
│   ├── models.py                         # Source, FactRecord, Assertion, Policy, Verdict, ConflictDiff
│   ├── verifiers/                        # quote_quantity, precedence, conflict, coverage, diff
│   ├── receipt.py                        # Offline SHA-256 Merkle proof (CLAIMLAYER-MERKLE-SHA256-v3)
│   ├── ledger.py                         # Thread-safe in-memory + optional SQLite ledger
│   ├── verify.py                         # Pure deterministic verify() gate
│   ├── mcp_server.py                     # Native JSON-RPC 2.0 MCP server (stdio & HTTP)
│   └── cli.py                            # `claimlayer verify`, `claimlayer mcp`, `claimlayer demo`
├── docs/
│   ├── IMPLEMENTATION_GUIDE.md           # Full step-by-step developer integration & error code guide
│   └── harvey_lab_benchmark.md           # Prior Harvey LAB Study A & Study B empirical observations
├── examples/
│   └── harness2_securitization/          # Harness² × Harvey LAB Case 1 showcase & c7 surface
├── benchmarks/
│   └── verification_bottleneck_bench.py  # 200-task supervision bottleneck compression benchmark
└── tests/                                # Formal invariant & isolated Harness² sandbox tests (G1–G8)
```

---

## License & Archive

- Licensed under the **Business Source License 1.1 (BSL 1.1)** — see [`LICENSE`](./LICENSE) and [`compliance-check-license.md`](./compliance-check-license.md). Converts to **MPL 2.0** on `2030-03-31`.
- Prior v2.1 retrieval/evidence experiments (Study A & Study B) are archived under Git tag [`v2.1-study-a-archive`](https://github.com/mathmentorAI/claim-layer/tree/v2.1-study-a-archive).
