# GitHub Issue Post for `google-research/harness2`

> **Title:** Deterministic Computable Verification in `c7/c8`: Closing the Self-Correction Loop at `k=1` on Harvey LAB (`compare-offering-memorandum-against-indenture`)

---

Hi `Harness²` team and community,

Following up on our earlier exploratory Harvey LAB thread (#91), where we noted an unresolved failure mode on **`structured-finance-securitization/compare-offering-memorandum-against-indenture`**:

> *"The baseline did produce both a `.docx` and a `.md` report, and the evaluator assessed substantive content. The saved Markdown report addresses the clean-up-call discrepancy, while the inspected failed criteria concern other discrepancies it does not address (`3/37`). The reason for this limited coverage remains to be investigated."*

When we subsequently ran a controlled, bash-free tool-calling study (`direct_rag` vs. passive structured retrieval, archived under [`v2.1-study-a-archive`](https://github.com/mathmentorAI/claim-layer/blob/main/docs/harvey_lab_benchmark.md)), Corporate M&A (`+30.65 pp`) and Banking & Finance (`+45.45 pp`) improved substantially, **yet Structured Finance remained completely flat at `11/37` (`+0.00 pp`)**.

Inspecting those trajectories revealed why neither better retrieval tools (`c5/c7` passive lookup) nor soft Markdown instructions (`c1/c2`) solve hierarchical cross-document audits—and why this directly mirrors Anthropic's recent findings on the **80% human supervision ("metawork") bottleneck**:

1. **Passive retrieval does not prevent premature stopping:** Once an LLM spots 1–2 salient discrepancies (e.g., Clean-Up Call `10%` vs `15%`), nothing in a passive tool surface blocks it from writing `output/` and skipping the Priority of Payments Waterfall (`Step 13` junior vs `Step 6` senior Reserve Account replenishment) or Note Coupons (`6.75%` vs `6.50%`).
2. **Passive context does not block authority inversion:** Even when both documents are in context, the solver frequently cites the marketing **Offering Memorandum** (`6.50%`) as governing when the **Executed Master Trust Indenture** (`6.75%`) legally controls.
3. **Post-hoc $k>1$ rollout selection (`c8`) shares blind spots & multiplies cost:** If all $k$ rollouts stop early or blur authority tiers, whole-deliverable selection cannot recover the missing sections—leaving a human associate to manually re-read every page.

---

### Turning `c7` (`scripts/`) into a `<1 ms` Deterministic Compiler Gate (`PASS` / `RETRY` / `ESCALATE`)

To isolate and solve this cleanly, we stripped `claim-layer` v3.0 down to a **zero-dependency Python stdlib verification kernel** (~1,200 LoC, `0` external packages, `0` LLM calls) that drops directly into `OPENCODE_SURFACE` (`c2` `guardrails.md` + `c6` `SKILL.md` + `c7` `scripts/claimlayer_gate.py`) as an **active completion gate** inside a single `k=1` trajectory:

```text
Agent (OpenCode k=1)
  │
  ├── 1. `python3 scripts/claimlayer_gate.py prepare documents`
  │        └─ Registers sources with authority ranks (Indenture=100, OM=50, .eml=10)
  │           and deterministically diffs sections (`build_comparison_policy`) to emit
  │           mandatory `required_predicates` for every divergent clause.
  │
  └── 2. `python3 scripts/claimlayer_gate.py verify proposal.json`  (<1 ms, 0 LLM calls)
           ├─ RETRY (exit 2)    ──► Exact machine-actionable error bounced back to agent:
           │                        • MISSING_REQUIRED_PREDICATE (skipped waterfall / coupon section)
           │                        • HIGHER_TIER_OVERRIDE / INSUFFICIENT_AUTHORITY_TIER (cited OM over Indenture)
           │                        • QUOTE_NOT_IN_SOURCE / QUANTITY_MISMATCH (unit/scale drift, e.g. 30d vs 5bd)
           ├─ PASS  (exit 0)    ──► Writes offline-verifiable SHA-256 Merkle receipt (`CLAIMLAYER-MERKLE-SHA256-v3`);
           │                        agent proceeds to generate final `output/` deliverable.
           └─ ESCALATE (exit 3) ──► Reserved strictly for genuine peer-authority conflicts (two signed
                                    rank-100 instruments contradicting each other).
```

Because `RETRY` strictly preempts `ESCALATE`, skipped sections, unit/scale hallucinations, and OM-vs-Indenture authority inversions are caught and self-corrected **inside the agent's own tool loop in `<1 ms` per check**, with zero extra rollouts and zero human review wasted on ungrounded drafts.

---

### Minimal Reproduction (Zero API Keys, Pure Python Stdlib, `<20 ms`)

Because the engine uses only the Python standard library, `stage_self_contained_harness()` bundles the entire verifier into `scripts/claimlayer/` so isolated Harvey LAB / OpenCode sandboxes require **zero `pip install` and zero network access**:

```bash
git clone https://github.com/mathmentorAI/claim-layer.git
cd claim-layer

# 1. Run the 3-turn Offering Memorandum vs. Indenture trajectory replay (<2 ms, 0 API keys)
PYTHONPATH=src python3 examples/harness2_securitization/replay_om_vs_indenture.py

# 2. Run formal invariant & isolated sandbox tests (G1–G8 + c7 script E2E with clean PATH)
pytest -v
```

Output from [`replay_om_vs_indenture.py`](https://github.com/mathmentorAI/claim-layer/blob/main/examples/harness2_securitization/replay_om_vs_indenture.py):

```text
Divergent Sections Auto-Detected (4 of 5 total sections):
  • [section_2_04] Quantitative divergence ... executed_indenture_2026=['5.1:PERCENT', '5.85:PERCENT', '50000000:USD', '6.75:PERCENT'] vs draft_offering_memorandum=[..., '6.5:PERCENT'].
  • [section_5_04] Textual/structural divergence in 'Section 5.04: Priority of Payments (Waterfall)...'
  • [section_7_01] Quantitative divergence ... executed_indenture_2026=['5:DAYS'] vs draft_offering_memorandum=['30:DAYS'].
  • [section_9_01] Quantitative divergence ... executed_indenture_2026=['10:PERCENT'] vs draft_offering_memorandum=['15:PERCENT'].

[Turn 1] Baseline-style incomplete draft -> Verdict: RETRY (Human Woken: False)
   ✗ MISSING_REQUIRED_PREDICATE: Required predicate 'section_2_04' was omitted from the agent proposal.
   ✗ MISSING_REQUIRED_PREDICATE: Required predicate 'section_5_04' was omitted from the agent proposal.
   ✗ MISSING_REQUIRED_PREDICATE: Required predicate 'section_7_01' was omitted from the agent proposal.
   ✗ QUANTITY_MISMATCH: Quantity 12 (PERCENT) in proposed value '12%' is not grounded in cited quote ...

[Turn 2] Agent inverts authority (cites OM 6.50%) -> Verdict: RETRY (Human Woken: False)
   ✗ HIGHER_TIER_OVERRIDE: Higher-authority source 'executed_indenture_2026' (tier='authoritative', rank=100) states Deal_Waterfall.section_2_04 = '6.75%', overriding 'draft_offering_memorandum' (tier='standard', rank=50).
     ↳ Auto-Remediation to Agent: Replace value '6.50%' with governing value '6.75%' from 'executed_indenture_2026'.

[Turn 3] Agent self-corrected -> Verdict: PASS (Allowed to Proceed: True)
   ✓ All 4 divergent sections verified in 1.48 ms total (0 LLM judge calls, 0 human wait)
   ✓ Merkle Root (CLAIMLAYER-MERKLE-SHA256-v3): 40fbecb7be7eecffb432bd86070434f6cc7fdafd58a214f5188b0daf5fd0179d
   ✓ Offline Receipt Signature Valid: True
```

- **Repository (zero-dependency v3 kernel):** https://github.com/mathmentorAI/claim-layer
- **`Harness²` `c2/c6/c7` Surface & Harvey LAB A/B Runner:** [`examples/harness2_securitization/`](https://github.com/mathmentorAI/claim-layer/tree/main/examples/harness2_securitization)
- **Step-by-Step Integration Guide:** [`docs/IMPLEMENTATION_GUIDE.md`](https://github.com/mathmentorAI/claim-layer/blob/main/docs/IMPLEMENTATION_GUIDE.md)

---

### Design Question for `Harness²` (`c7` / `c8` Evolution)

Right now in `Harness²`, *Propose–Probe–Compose* either synthesizes custom `c7` Python scripts from scratch per task family or relies on $k>1$ candidate selection in `c8`.

Have you explored pairing a **fixed, verified `c7` verification kernel** (handling span/quantity/unit grounding, authority precedence, and exit-code routing deterministically) with *Propose–Probe–Compose* synthesizing **only the declarative `Policy` JSON** (document tier mappings, required predicates, numeric bounds) during the Probe phase? Separating **reusable verification mechanics** from **synthesized task policies** seems like a clean way to prevent buggy synthesized `c7` scripts while getting deterministic self-correction at `k=1`. Would love your thoughts!
