# ClaimLayer v3 · Developer Implementation Guide

This guide shows step-by-step how to integrate **ClaimLayer** into your own AI agents, tool loops, MCP clients, or multi-agent control planes after cloning the repository.

---

## 1. Mental Model (Where ClaimLayer Sits)

ClaimLayer is **not** an LLM wrapper, RAG framework, or vector database. Keep your existing model (`Claude`, `GPT`, `Gemini`), prompts, and retrieval stack unchanged.

Insert `claimlayer.verify()` as a **deterministic `<1 ms` compiler gate** right before your agent emits its final deliverable or executes a side-effect:

```text
Your Existing Agent / RAG Stack
        │
        ▼  Produces structured `Assertion` list (value + source_id + verbatim quote)
┌───────────────────────────────┐
│   claimlayer.verify() (<1ms)  │  0 LLM calls · Pure Python stdlib
└───────┬───────────┬───────────┘
        │           │
        │ PASS      ├──► Proceed immediately + attach SHA-256 Merkle receipt (0 human wait)
        │           │
        │ RETRY     ├──► Feed `verdict.issues` back to the Agent tool loop (0 human wait)
        │           │
        └ ESCALATE  └──► Wake a human ONLY for genuine peer-authority conflicts or policy caps
```

---

## 2. Installation

### Option A: Zero-Dependency Core Library (`claimlayer`)

`claimlayer` uses **only the Python 3.10+ standard library** (`hashlib`, `sqlite3`, `re`, `decimal`, `dataclasses`, `json`).

```bash
git clone https://github.com/mathmentorAI/claim-layer.git
cd claim-layer

# Install editable package into your virtualenv
pip install -e .
```

> **Air-gapped / Sandboxed Agents (`Docker`, `Harness²`, `Modal`, `E2B`):**
> Because `claimlayer` has zero third-party dependencies, you don't even need `pip` inside sandboxes—you can copy `src/claimlayer` directly next to your agent script or set `PYTHONPATH=/path/to/claim-layer/src`.

### Option B: Control Plane API + Surgical Human Triage UI (Optional)

If you want a shared HTTP verification server and the 15-second React Triage Desk for human supervisors:

```bash
pip install fastapi uvicorn pydantic
cd frontend && npm install && cd ..
```

---

## 3. Pattern 1: Python SDK Self-Correction Loop (Recommended for Custom Agents)

Use this pattern with the **Anthropic SDK**, **OpenAI SDK**, **LangGraph**, **PydanticAI**, or any Python agent loop.

### Step 1: Register Governing Sources & Policy

```python
from claimlayer import (
    Assertion,
    FactRecord,
    Ledger,
    NumericBound,
    Policy,
    Source,
    verify,
    verify_receipt,
)

ledger = Ledger(
    db_path=".claimlayer.sqlite",  # Omit `db_path` for pure in-memory speed
    sources=[
        Source(
            id="msa_2024",
            title="Master Services Agreement (2024)",
            text="Section 4.1: Customer shall pay all undisputed invoices within 45 days. Liability cap is $250,000.",
            tier="standard",          # rank = 50
        ),
        Source(
            id="amendment_2026",
            title="Executed First Amendment (2026)",
            text="Section 4.1 is amended: Customer shall pay all undisputed invoices within 30 days.",
            tier="authoritative",     # rank = 100
            supersedes=["msa_2024"],  # Overrides msa_2024 where facts overlap
        ),
        Source(
            id="sales_thread_eml",
            title="Account Executive Email",
            text="Let's offer net 60 days informally.",
            tier="draft",             # rank = 10
        ),
    ],
    facts=[
        FactRecord(
            subject="Customer",
            predicate="payment_terms",
            value="30 days",
            source_id="amendment_2026",
            quote="Customer shall pay all undisputed invoices within 30 days.",
        )
    ],
)

policy = Policy(
    policy_id="deal_desk_v1",
    min_tier_rank=50,  # Blocks `draft` emails from governing (`INSUFFICIENT_AUTHORITY_TIER`)
    required_predicates=["payment_terms", "liability_cap"],
    numeric_bounds={
        "liability_cap": NumericBound(max_value=500_000, unit="USD", action="ESCALATE")
    },
)
```

### Step 2: Gate Your Agent Inside a `while` Loop

Ask your LLM (via tool-calling or Structured Outputs) to return its answer alongside an `assertions` array:

```python
MAX_RETRIES = 3
messages = [{"role": "user", "content": "Extract governing payment terms and liability cap."}]

for attempt in range(MAX_RETRIES):
    # 1. Call your LLM (OpenAI / Anthropic / Gemini / local model)
    llm_output = call_your_llm(messages)  # Returns {"summary": "...", "assertions": [...]}

    # 2. Run deterministic <1 ms verification
    verdict = ledger.verify(
        assertions=llm_output["assertions"],
        policy=policy,
        agent_id="deal-desk-agent",
    )

    if verdict.status == "PASS":
        assert verify_receipt(verdict)  # Cryptographic SHA-256 Merkle proof
        save_approved_deliverable(llm_output["summary"], receipt=verdict.receipt.to_dict())
        break

    if verdict.status == "RETRY":
        # Bounce exact machine-readable errors back to the LLM — ZERO human interruption!
        feedback = "\n".join(
            f"- [{i.code}] {i.message} Remediation: {i.remediation}"
            for i in verdict.issues
        )
        messages.append({
            "role": "user",
            "content": f"ClaimLayer verification failed (RETRY). Fix these exact errors:\n{feedback}",
        })
        continue

    if verdict.status == "ESCALATE":
        # Genuine conflict between peer authoritative docs or executive threshold exceeded
        route_to_human_triage(verdict.conflicts, escalation_id=verdict.verdict_id)
        break
```

### Bonus: Auto-Building Policies for Document Comparisons (Redlines, OM vs. Indenture)

When comparing two versions or instruments (e.g., an **Executed Indenture** vs. a **Draft Offering Memorandum**), use `build_comparison_policy()` so the agent cannot skip any divergent clause:

```python
from claimlayer import build_comparison_policy

policy, divergences = build_comparison_policy(
    primary=executed_indenture,     # tier="authoritative"
    secondary=offering_memorandum,  # tier="standard"
)
# `policy.required_predicates` automatically contains every section key where numbers or text diverge!
```

---

## 4. Pattern 2: MCP Server (`Claude Code`, `Cursor`, `OpenCode`, `Claude Desktop`)

ClaimLayer ships with a native, zero-dependency JSON-RPC 2.0 MCP server over `stdio`.

### Step 1: Add to `.mcp.json` or `claude_desktop_config.json`

```json
{
  "mcpServers": {
    "claimlayer": {
      "command": "python3",
      "args": [
        "-m",
        "claimlayer.cli",
        "mcp",
        "--db",
        ".claimlayer.sqlite"
      ],
      "env": {
        "PYTHONPATH": "/absolute/path/to/claim-layer/src"
      }
    }
  }
}
```

*(If you ran `pip install -e .` in the Python environment used by `command`, you can omit `env.PYTHONPATH`.)*

### Step 2: Add 5 Lines to Your Agent's `CLAUDE.md` / `systemprompt.md`

```markdown
## Mandatory Computable Verification (`claimlayer` MCP)
1. Register governing source documents first via `register_source` (`authoritative` > `standard` > `draft`).
2. Before presenting conclusions or writing final deliverables, call `verify_proposal` with every quantitative or contractual claim and its verbatim `quote`.
3. If `verify_proposal` returns `RETRY`, fix every reported issue yourself without asking the user. Only ask the user if `verify_proposal` returns `ESCALATE`.
```

---

## 5. Pattern 3: Shell CLI Gate (`Harness²`, CI/CD, Sandboxed Coding Agents)

For terminal-native agents (`OpenCode`, `google-research/harness2`, `SWE-agent`, `Codex CLI`), gate completion using standard POSIX exit codes:

```bash
claimlayer verify --bundle proposal.json
# Exit code 0 -> PASS     (Cryptographic receipt printed to stdout)
# Exit code 2 -> RETRY    (Agent must self-correct issues[] and re-run)
# Exit code 3 -> ESCALATE (Route ConflictDiff[] to human reviewer)
```

Minimal `proposal.json` schema:

```json
{
  "sources": [
    {
      "id": "indenture_2026",
      "tier": "authoritative",
      "text": "Section 2.04: Class C Notes ($50,000,000 principal) bear interest at 6.75% per annum."
    }
  ],
  "policy": {
    "policy_id": "securitization_gate",
    "min_tier_rank": 100,
    "required_predicates": ["section_2_04"]
  },
  "assertions": [
    {
      "subject": "Class_C_Notes",
      "predicate": "section_2_04",
      "value": "6.75% ($50M)",
      "source_id": "indenture_2026",
      "quote": "Class C Notes ($50,000,000 principal) bear interest at 6.75% per annum."
    }
  ]
}
```

See [`examples/harness2_securitization/`](../examples/harness2_securitization/) for a complete stateful 2-step `Harness²` `c7` gate (`claimlayer_gate.py prepare` + `claimlayer_gate.py verify`).

---

## 6. Pattern 4: Shared REST Control Plane + 15-Second Human Triage UI

When running fleets of background agents across Legal, Finance, or Operations:

### Step 1: Start the Control Plane & Triage UI

```bash
# Terminal 1: FastAPI Control Plane + HTTP MCP (http://localhost:8000)
uvicorn api.main:app --reload --port 8000

# Terminal 2: Surgical 15-Second Triage Desk (http://localhost:5173)
cd frontend && npm run dev
```

### Step 2: Submit Proposals Over HTTP (`POST /api/v1/verify`)

```bash
curl -s http://localhost:8000/api/v1/verify \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "ap-invoice-agent-04",
    "assertions": [
      {
        "subject": "Vendor_X",
        "predicate": "payment_terms",
        "value": "30 days",
        "source_id": "amendment_2026",
        "quote": "pay all undisputed invoices within 30 days"
      }
    ]
  }'
```

### Step 3: Compounding Precedents (Resolve Once, Never Escalate Twice)

When `POST /api/v1/verify` returns `ESCALATE`, it appears in the **Surgical Triage Desk** (`http://localhost:5173`) showing only the two conflicting quotes side-by-side.
Once a human clicks **Select Governing Truth** (`POST /api/v1/escalations/resolve`), ClaimLayer writes an authoritative `FactRecord` to the SQLite ledger (`precedents` table)—so **every future agent run resolves that conflict automatically in `<1 ms` (`RETRY` / `PASS`) without ever waking a human again**.

---

## 7. Deterministic Error Codes Reference

| `Issue.code` | Verdict Route | Trigger Condition |
| :--- | :--- | :--- |
| `EMPTY_PROPOSAL` | `RETRY` | Agent submitted zero assertions. |
| `SOURCE_NOT_FOUND` | `RETRY` | `Assertion.source_id` does not exist in `Ledger`. |
| `QUOTE_NOT_IN_SOURCE` | `RETRY` | `Assertion.quote` is not a normalized verbatim substring of `Source.text`. |
| `QUANTITY_MISMATCH` | `RETRY` | Number, scale (`K`/`M`/`B`), or unit (`USD`/`EUR`/`%`/`days`) in `value` does not match `quote`. |
| `DATE_MISMATCH` | `RETRY` | Date in `value` (`YYYY-MM-DD` or `Month DD, YYYY`) does not match `quote`. |
| `SOURCE_NOT_YET_EFFECTIVE` | `RETRY` | `Source.valid_from > Policy.as_of`. |
| `SOURCE_EXPIRED` | `RETRY` | `Source.valid_until < Policy.as_of`. |
| `INSUFFICIENT_AUTHORITY_TIER` | `RETRY` | `Source.rank < Policy.min_tier_rank` (e.g., citing an email instead of a contract). |
| `SOURCE_SUPERSEDED` | `RETRY` | Cited source was superseded by an amendment covering `(subject, predicate)`. |
| `HIGHER_TIER_OVERRIDE` | `RETRY` | A higher-tier source in `Ledger` contradicts the proposed value. |
| `SAME_TIER_CONTRADICTION` | `RETRY` | Cited source or already-resolved precedent contradicts `Assertion.value`. |
| `MISSING_REQUIRED_PREDICATE` | `RETRY` | Proposal skipped a mandatory field/section in `Policy.required_predicates`. |
| `MISSING_REQUIRED_SOURCE` | `RETRY` | Proposal failed to cite a mandatory governing document in `Policy.required_source_ids`. |
| `PEER_SOURCE_CONFLICT` | `ESCALATE` | Two active sources of equal highest authority state incompatible values. |
| `LOW_CONSOLIDATED_CONFIDENCE` | `ESCALATE` | Deduplicated Noisy-OR source confidence falls below `Policy.confidence_threshold`. |
| `NUMERIC_BOUND_EXCEEDED` | `ESCALATE` / `RETRY` | Proposed quantity violates `Policy.numeric_bounds` (`action` configurable). |
