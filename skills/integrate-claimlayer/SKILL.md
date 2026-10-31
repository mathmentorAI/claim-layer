---
name: integrate-claimlayer
description: >-
  Interactive setup and integration wizard for adding ClaimLayer v3 deterministic
  computable verification (`verify()` -> PASS / RETRY / ESCALATE) to an AI agent,
  RAG pipeline, SaaS backend, or MCP/CLI harness. Use this skill whenever a
  developer asks to install, configure, or integrate ClaimLayer into their product
  or agent workflow to eliminate hallucinations and reduce human supervision wait time.
---

# Integrate ClaimLayer v3 into a Product or Agent

Guide the developer step-by-step to wire **ClaimLayer v3** (`claimlayer.verify()`) as a deterministic `<1 ms` compiler gate between their LLM/agent output and task completion or side-effects. Always communicate in the same language the developer uses.

---

## Core Architecture Rule

Never replace the developer's existing LLM (`Claude`, `GPT`, `Gemini`), prompts, or RAG retrieval stack. Insert `claimlayer.verify()` right before the agent returns its final deliverable or triggers an external action:

- **`PASS`**: Every quote, number, scale, unit, date, authority tier, and mandatory field checks out → auto-approve immediately with an offline SHA-256 Merkle receipt (`verify_receipt(verdict)`).
- **`RETRY` (`requires_human=False`)**: Ungrounded quote, quantity/unit mismatch, expired/superseded clause, authority inversion, or skipped required field → bounce `verdict.issues` directly back into the LLM retry loop (`max_retries=3`) with **zero human interruption**.
- **`ESCALATE` (`requires_human=True`)**: Genuine contradiction between peer authoritative sources or an executive policy cap (`numeric_bounds`) → route `verdict.conflicts` (`ConflictDiff`) to a human supervisor for 15-second resolution, then persist the chosen value as a `FactRecord` precedent.

---

## Step-by-Step Workflow

### Step 1: Audit the Target Codebase Automatically

Before asking questions, inspect the developer's workspace (`pyproject.toml`, `requirements.txt`, `package.json`, `go.mod`, agent entrypoints, tool schemas) to classify their integration path:

1. **Path A — Python Backend / Agent Loop** (`openai`, `anthropic`, `google-genai`, `langgraph`, `pydantic-ai`, `fastapi`, `django`):
   Use the zero-dependency in-process `claimlayer` Python library (`Ledger` + `ledger.verify()`).
2. **Path B — TypeScript / Node.js / Go / Java Product**:
   Connect over HTTP to the ClaimLayer FastAPI Control Plane (`POST /api/v1/verify` and `POST /api/v1/escalations/resolve`) or invoke `claimlayer verify --bundle` via subprocess.
3. **Path C — MCP Client or Terminal Coding/Legal Harness** (`Claude Code`, `Cursor`, `OpenCode`, `google-research/harness2`):
   Configure the native `stdio` MCP server (`python3 -m claimlayer.cli mcp --db .claimlayer.sqlite`) or copy `src/claimlayer` into `scripts/` for air-gapped CLI gating.

Read the matching code template in [references/stack_templates.md](./references/stack_templates.md).

---

### Step 2: Ask 3 Targeted Domain Questions

Summarize what you detected in their codebase and ask **only** the domain questions not already obvious from their code:

1. **Source Authority Hierarchy (`Source.tier`):**
   - Which documents or records are legally/operationally controlling (`authoritative`, rank `100`, e.g., signed contracts, executed indentures, ERP records)?
   - Which are secondary (`standard`, rank `50`, e.g., proposals, offering memoranda, markups)?
   - Which are informal (`draft`, rank `10`, e.g., emails, Slack messages) that must never override binding records?
   - Do newer amendments supersede base agreements (`supersedes=["base_doc_id"]`)?
2. **Completeness & Safety Policy (`Policy`):**
   - Are there mandatory fields/clauses the agent must never skip (`required_predicates`), or is it comparing two documents side-by-side (use `build_comparison_policy(primary, secondary)`)?
   - Are there monetary/quantity thresholds requiring executive sign-off (`numeric_bounds`)?
3. **Human Escalation Sink (`ESCALATE`):**
   - Where should genuine peer-authority conflicts (`verdict.conflicts`) be surfaced (database table, API response payload, webhook/Slack, or the React Surgical Triage UI)?

---

### Step 3: Install & Implement the Gate

1. **Install `claim-layer` (0 external dependencies, Python 3.10+ stdlib only):**
   ```bash
   pip install "git+https://github.com/mathmentorAI/claim-layer.git"
   ```
   *(If `claim-layer/` is already vendored locally, run `pip install -e ./claim-layer` or copy `src/claimlayer` directly into the service/sandbox.)*
2. **Extend the LLM Structured Output / Tool Schema:**
   Add an `assertions` list alongside the agent's existing response fields, where each item contains:
   - `subject` (`str`): Entity, party, or deal identifier.
   - `predicate` (`str`): Normalized field or section key (must match `Policy.required_predicates` if configured).
   - `value` (`str`): Proposed value with explicit units/dates (e.g., `"30 days"`, `"$50,000,000"`, `"6.75%"`).
   - `source_id` (`str`): Registered `Source.id` in the `Ledger`.
   - `quote` (`str`): Exact verbatim substring from `Source.text` proving the claim.
3. **Wire the Verification & Self-Correction Loop:**
   Adapt the matching template from [references/stack_templates.md](./references/stack_templates.md) into the developer's agent entrypoint. Ensure `RETRY` errors feed `[issue.code] issue.message -> issue.remediation` back to the LLM without waking a human.

---

### Step 4: Run Deterministic Verification & Add a Smoke Test

1. Run the bundled smoke-check helper to confirm `claimlayer` imports cleanly and enforces `RETRY` → `PASS` + SHA-256 Merkle verification:
   ```bash
   python3 skills/integrate-claimlayer/scripts/verify_integration.py
   ```
   *(Adjust path to wherever this skill is located.)*
2. Add a fast unit test in the developer's test suite verifying their specific `Policy`:
   - **Negative case:** An assertion with a fabricated quote, wrong unit, or superseded `source_id` returns `verdict.status == "RETRY"` and `verdict.requires_human is False`.
   - **Positive case:** A grounded assertion against the governing `authoritative` source returns `verdict.status == "PASS"` and `verify_receipt(verdict) is True`.
