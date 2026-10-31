# ClaimLayer v3 Integration Templates by Stack

Load only the template matching the developer's detected architecture.

---

## Template A1: Python Agent Loop (OpenAI / Anthropic / Gemini / Custom SDK)

```python
from typing import Any
from claimlayer import (
    Assertion,
    FactRecord,
    Ledger,
    Policy,
    Source,
    build_comparison_policy,
    verify_receipt,
)

def build_domain_ledger(db_path: str = ".claimlayer.sqlite") -> tuple[Ledger, Policy]:
    ledger = Ledger(
        db_path=db_path,
        sources=[
            Source(
                id="governing_contract_v2",
                title="Executed Agreement",
                text="...",  # Load plain text of authoritative source
                tier="authoritative",  # rank=100 ('authoritative' > 'standard' > 'draft')
                supersedes=["legacy_contract_v1"],
            ),
        ],
    )
    policy = Policy(
        policy_id="prod_verification_gate",
        min_tier_rank=50,  # Blocks 'draft' (rank=20) emails/chats from governing
        required_predicates=["payment_terms", "liability_cap"],
        numeric_bounds={
            "liability_cap": (None, 500_000.0)  # (min, max) -> triggers ESCALATE above 500,000
        },
    )
    return ledger, policy


def run_verified_agent(
    messages: list[dict[str, str]],
    ledger: Ledger,
    policy: Policy,
    call_llm_structured: Any,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Gate an LLM agent with <1 ms deterministic self-correction."""
    for attempt in range(max_retries):
        # Expected schema from LLM: {"answer": str, "assertions": list[dict]}
        draft = call_llm_structured(messages)
        verdict = ledger.verify(
            assertions=draft.get("assertions", []),
            policy=policy,
            agent_id="prod-agent",
        )

        if verdict.status == "PASS":
            assert verify_receipt(verdict)
            return {
                "status": "APPROVED",
                "answer": draft["answer"],
                "receipt": verdict.receipt.to_dict(),
                "attempts": attempt + 1,
            }

        if verdict.status == "RETRY":
            # Bounce exact deterministic errors back to the LLM — 0 human wait!
            remediation_lines = "\n".join(
                f"- [{iss.code}] {iss.message} Fix: {iss.remediation}"
                for iss in verdict.issues
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "ClaimLayer verification rejected your draft (RETRY). "
                        "Correct every issue below citing verbatim quotes from governing sources:\n"
                        f"{remediation_lines}"
                    ),
                }
            )
            continue

        if verdict.status == "ESCALATE":
            # Genuine conflict between peer authoritative docs or executive threshold exceeded
            return {
                "status": "NEEDS_HUMAN_DECISION",
                "escalation_id": verdict.verdict_id,
                "conflicts": [c.to_dict() for c in verdict.conflicts],
                "draft_answer": draft["answer"],
            }

    raise RuntimeError("Agent failed deterministic verification after max_retries.")
```

> **Tip — Cross-Document Comparison (`Redline` / `OM vs. Indenture`):**
> Replace manual `required_predicates` with:
> ```python
> policy, divergences = build_comparison_policy(primary=authoritative_doc, secondary=markup_doc)
> ```

---

## Template A2: JSON Schema for LLM Structured Outputs / Tool Calling

Attach this JSON Schema to OpenAI `response_format`, Anthropic `input_schema`, or Pydantic models:

```json
{
  "type": "object",
  "required": ["answer", "assertions"],
  "additionalProperties": false,
  "properties": {
    "answer": {
      "type": "string",
      "description": "Final human-readable deliverable grounded strictly in verified assertions."
    },
    "assertions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["subject", "predicate", "value", "source_id", "quote"],
        "additionalProperties": false,
        "properties": {
          "subject": { "type": "string" },
          "predicate": { "type": "string" },
          "value": { "type": "string", "description": "Explicit value with unit or ISO date (e.g. '30 days', '$50,000')." },
          "source_id": { "type": "string", "description": "Exact ID of the governing document." },
          "quote": { "type": "string", "description": "Exact verbatim substring copied from the source text." }
        }
      }
    }
  }
}
```

---

## Template B: TypeScript / Node.js / Non-Python Backend (HTTP Control Plane)

Run the Control Plane (`uvicorn api.main:app --port 8000`) and gate your TypeScript agent loop:

```typescript
interface AssertionInput {
  subject: string;
  predicate: string;
  value: string;
  source_id: string;
  quote: string;
}

export async function verifyAgentProposal(
  agentId: string,
  assertions: AssertionInput[],
  policy?: Record<string, unknown>,
) {
  const res = await fetch(`${process.env.CLAIMLAYER_URL ?? "http://localhost:8000"}/api/v1/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_id: agentId, assertions, policy }),
  });
  if (!res.ok) throw new Error(`ClaimLayer HTTP ${res.status}`);
  return res.json() as Promise<{
    verdict_id: string;
    status: "PASS" | "RETRY" | "ESCALATE";
    allowed_to_proceed: boolean;
    requires_human: boolean;
    issues: Array<{ code: string; message: string; remediation: string }>;
    conflicts: Array<Record<string, unknown>>;
    receipt: { merkle_root: string; signature_valid?: boolean };
  }>;
}
```

When a human supervisor resolves an `ESCALATE` item in your UI, persist the precedent so future agents never escalate the same conflict again:

```typescript
await fetch(`${process.env.CLAIMLAYER_URL ?? "http://localhost:8000"}/api/v1/escalations/resolve`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    verdict_id: verdict.verdict_id,
    subject: "Vendor_X",
    predicate: "payment_terms",
    selected_value: "30 days",
    resolver: "ops-lead@company.com",
  }),
});
```

---

## Template C: MCP Server (`Claude Code`, `Cursor`, `OpenCode`, `Claude Desktop`)

1. Add to `.mcp.json` or `claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "claimlayer": {
         "command": "python3",
         "args": ["-m", "claimlayer.cli", "mcp", "--db", ".claimlayer.sqlite"]
       }
     }
   }
   ```
2. Add to `CLAUDE.md`, `GEMINI.md`, or `AGENTS.md`:
   ```markdown
   ## Mandatory ClaimLayer Verification
   1. Register governing documents via `register_source` (`authoritative` > `standard` > `draft`).
   2. Before finalizing any deliverable or side-effect, call `verify_proposal` with verbatim quotes for all quantitative, temporal, and contractual claims.
   3. If `verify_proposal` returns `RETRY`, fix all reported issues automatically without interrupting the user. Only ask the user if `verify_proposal` returns `ESCALATE`.
   ```
