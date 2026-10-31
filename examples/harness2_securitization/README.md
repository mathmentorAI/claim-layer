# Harness² × ClaimLayer v3 — Case 1: Offering Memorandum vs. Indenture

This directory contains a complete, reproducible integration of **ClaimLayer v3** into the **`google-research/harness2`** 8-component agent surface (`OPENCODE_SURFACE`) for **Harvey LAB Case 1**:
`structured-finance-securitization / compare-offering-memorandum-against-indenture`.

---

## Why This Task Needs Computable Verification

In structured finance transactions, counsel must audit a marketing **Preliminary Offering Memorandum (OM)** against the legally binding **Executed Master Trust Indenture** alongside informal **Associate Deal Emails**:

| Document | Governing Role | ClaimLayer Tier (`rank`) |
| :--- | :--- | :--- |
| **Executed Master Trust Indenture** | Controlling legal instrument | `authoritative` (`100`) |
| **Preliminary Offering Memorandum** | Marketing disclosure (subordinate) | `standard` (`50`) |
| **Associate Instructions (`.eml`)** | Informal internal email | `draft` (`10`) |

Without a deterministic verification gate, frontier LLM agents routinely exhibit three silent failure modes that force senior associates to re-read every page manually ("metawork"):

1. **Premature Stopping (`MISSING_REQUIRED_PREDICATE`):** Checking one obvious discrepancy (e.g., Clean-Up Call `10%` vs `15%`) and declaring completion while skipping the Priority of Payments Waterfall (`Step 13` vs `Step 6`) or Class C Coupon (`6.75%` vs `6.50%`).
2. **Authority Inversion (`HIGHER_TIER_OVERRIDE` / `INSUFFICIENT_AUTHORITY_TIER`):** Treating the Offering Memorandum's `6.50%` figure as governing instead of flagging that it violates the `6.75%` Executed Indenture.
3. **Quantitative / Unit Drift (`QUANTITY_MISMATCH`):** Misstating numbers, scales, or cure-period units (`30 days` vs `5 business days`).

---

## Mapping Onto the `Harness²` Surface (`c2` + `c6` + `c7`)

Because `claimlayer` uses **zero external dependencies** (pure Python stdlib), `run_harness2_ab.py` bundles the entire verification engine directly inside `scripts/`—requiring **zero `pip install` or network access** inside the Harvey LAB / OpenCode sandbox:

```text
harness_surface/
├── guardrails.md                         # [c2] Instructs agent to run `prepare` first & `verify` before output/
├── skills/
│   └── claimlayer_verify/SKILL.md        # [c6] Skill schema for structured assertion verification
└── scripts/
    └── claimlayer_gate.py                # [c7] Deterministic CLI gate (`prepare` & `verify`, exit codes 0/2/3)
```

---

## 1. Run the Instant Offline Replay (<2 ms, Zero API Keys)

Replays a 3-turn trajectory (`RETRY` on omitted sections & wrong figure → `RETRY` on OM vs. Indenture authority inversion → `PASS` with offline SHA-256 Merkle receipt):

```bash
PYTHONPATH=src python3 examples/harness2_securitization/replay_om_vs_indenture.py
```

---

## 2. Inspect or Run the Live `Harness²` / Harvey LAB A/B Benchmark

### Dry-Run (Stages Self-Contained Surface & Prints Commands, No API Key Required)

```bash
python3 examples/harness2_securitization/run_harness2_ab.py --dry-run
```

### Full Live A/B Execution (Requires `harveyai/harvey-labs` + `OPENAI_API_KEY`)

```bash
export OPENAI_API_KEY="sk-..."
python3 examples/harness2_securitization/run_harness2_ab.py \
    --lab-root /path/to/harvey-labs \
    --model openai/gpt-5.4 \
    --run-eval
```

---

## 3. Ready-to-Publish GitHub Discussion Post

See [`GITHUB_DISCUSSION_POST.md`](./GITHUB_DISCUSSION_POST.md) for the technical write-up prepared for `google-research/harness2` Discussions.
