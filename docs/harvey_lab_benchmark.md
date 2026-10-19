# Exploratory Legal Agent Evaluation: Base `LAB/OpenCode` vs. `ClaimLayer / Deltoryx` Augmented Workflow on Harvey Legal Agent Benchmark (LAB)

**Date:** October 19, 2026  
**Authors:** Francisco Jesús Hernández de Blas & Deltoryx / ClaimLayer Team  
**Platform Checkout Inspected:** Commit `d70bf3ffb19205984e6b4667aa3ad80b0e5831f8`  
**Benchmark & Harness Context:** [`harveyai/harvey-labs`](https://github.com/harveyai/harvey-labs) (`b58a28a`) and [`google-research/harness2`](https://github.com/google-research/harness2) (`arXiv:2610.14224`)  
**Agent Substrate:** `OpenCode` (`v1.14.18`, `tool_mode="base"`, `skill_mode="native"`)  
**Solver Model:** `openai/gpt-4.1`  
**Evaluators (Paired Within Each Task):** `harvey-labs/evaluation/run_eval.py` using `openai/gpt-4.1` (Litigation, Banking) and `nvidia/nemotron-3-super-120b-a12b` (Structured Finance, Corporate M&A)  
**Scope:** 4 selected multi-document legal tasks, 20 source documents, 199 rubric evaluation criteria  

---

## 1. Study Design and Boundaries

This report summarizes the artifact-based reassessment of an exploratory integration comparing a base `LAB/OpenCode` agent against an augmented workflow incorporating a **ClaimLayer / Deltoryx** component tree (`c1`–`c8`: system prompts, guardrails, memory, tool guidance, `c5: skills/evidence_intelligence/SKILL.md`, and `c7: scripts/deltoryx_audit.py`).

### 1.1 Experimental Configuration
- **Solver & Execution Limits:** Both arms use `openai/gpt-4.1` with `tool_mode="base"`, `skill_mode="native"`, 80 maximum turns, one continuation, and a default 900-second timeout.
- **Prompt & Workflow Differences:** Saved metrics record `2,333` always-on prompt characters for the base arm and `9,456` for the augmented arm, along with differing `opencode_only` flags. The augmented workflow combines document-to-text mirrors, a local SQLite claim store, source-tier labels, clause-difference tables, instructions to index and verify, and a deliverable container check.
- **Evaluation Scope:** Four tasks were selected as a convenience sample covering litigation, structured finance, corporate M&A, and banking (`34`, `37`, `62`, and `66` rubric criteria respectively; `199` correlated criteria across 4 cases). This is an author-run exploratory study using the LAB evaluator, not an evaluation or endorsement by the benchmark or `Harness²` authors, nor a reproduction of `Harness²` recursive optimization.

---

## 2. Paired Results After Document-Container Repair

Table 1 reports the recalculated descriptive results from paired saved `scores.json` evaluations where **both arms within each task share the same judge** after document-container repair. We report **criterion pass rate** (not factual accuracy or complete-task pass rate; under the evaluator's all-criteria rule, complete-task success is `0/4` in both arms).

### 2.1 Paired Task-Level Breakdown

| Task (`practice-area / slug`) | Docs | Criteria | Base Passed | Augmented Passed | Difference (pp) | Criterion Transitions (Gain / Loss) | Judge |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`litigation-dispute-resolution`**<br>`analyze-counterparty-motion-to-dismiss` | 6 | 34 | `1 / 34` (`2.94%`) | **`19 / 34` (`55.88%`)** | **`+52.94`** | `+18 / -0` | `openai/gpt-4.1` |
| **`structured-finance-securitization`**<br>`compare-offering-memorandum-against-indenture` | 3 | 37 | `3 / 37` (`8.11%`) | **`12 / 37` (`32.43%`)** | **`+24.32`** | `+10 / -1` | `nvidia/nemotron-3-super-120b-a12b` |
| **`corporate-ma`**<br>`analyze-counterparty-spa-markup` | 6 | 62 | `15 / 62` (`24.19%`) | **`24 / 62` (`38.71%`)** | **`+14.52`** | `+12 / -3` | `nvidia/nemotron-3-super-120b-a12b` |
| **`banking-finance`**<br>`analyze-counterparty-markup-of-senior-secured-credit-facility-term-sheet` | 5 | 66 | `43 / 66` (`65.15%`) | **`44 / 66` (`66.67%`)** | **`+1.52`** | `+13 / -12` | `openai/gpt-4.1` |
| **Total (Pooled)** | **20** | **199** | **`62 / 199` (`31.16%`)** | **`99 / 199` (`49.75%`)** | **`+18.59`** | **`+53 / -16`** | **Mixed (Matched per task)** |

### 2.2 Summary Metrics

| Measure | Base Arm | Augmented Arm | Difference / Ratio |
| :--- | :---: | :---: | :---: |
| **Pooled Criteria Passed** | `62 / 199` (`31.16%`) | `99 / 199` (`49.75%`) | **`+37` criteria (`+18.59 pp`, `1.60x`)** |
| **Unweighted Mean of Task Pass Rates** | `25.10%` | `48.42%` | **`+23.32 pp`** |
| **Criterion-Level Gains / Losses** | — | `+53` gained / `-16` lost | Net `+37` criteria |
| **Oracle Criterion Union (Post-hoc across both arms)** | — | `115 / 199` (`57.79%`) | Banking union: `56 / 66` (`84.85%`) |
| **Oracle Whole-Deliverable Selector (1 response/task)** | — | `99 / 199` (`49.75%`) | Selects augmented arm on all 4 tasks |
| **Recorded Solver Tokens** | `220,320` | `388,406` | **`+168,086` tokens (`+76.3%`)** |
| **Logged Solver Cost (Historical USD, excl. judge)** | `USD 1.8000` | `USD 2.4705` | **`+USD 0.6705` (`+37.3%`)** |

---

## 3. Methodological Notes: Artifact Repair, Judge Sensitivity, and Oracle Union

### 3.1 Why Earlier Unpaired "Strict" Aggregates (`47/199` vs. `106/199`) Were Replaced
An earlier draft reported `47/199` (`23.62%`) versus `106/199` (`53.27%`). Reassessment of the saved evaluation files identified three reasons why that aggregate is not retained as a primary controlled comparison:
1. **Pre-Repair Container Failures in Corporate M&A:** Saved pre-repair files show `0/62` for *both* corporate M&A arms before container repair (when raw Markdown was written to `.docx` filenames, causing `pandoc` ZIP unpacking to fail), not only for the base arm.
2. **Judge Differences on Repaired M&A:** After container repair, the augmented M&A deliverable scored `31/62` under `openai/gpt-4.1` and `24/62` under `nvidia/nemotron-3-super-120b-a12b`, while the repaired base deliverable was scored under Nemotron (`15/62`).
3. **Structured Finance Readability Stage:** An earlier `openai/gpt-4.1` evaluation on structured finance scored `0/37` due to an artifact read failure, whereas the later Nemotron evaluation scored `12/37` (vs. `3/37` for the base arm under Nemotron).

The `106/199` aggregate combined the `31/62` GPT-4.1 M&A score with the later structured-finance score while retaining the `0/62` un-repaired base M&A score (`47/199`). Table 1 above instead enforces **matching judges within each task** and evaluates both repaired M&A containers (`15/62` vs. `24/62` under Nemotron), yielding `62/199` (`31.16%`) versus `99/199` (`49.75%`).

### 3.2 Oracle Criterion Union vs. Realizable $k=2$ Selection
Across the Table 1 evaluations, the post-hoc union of criteria passed by either the base arm or the augmented arm is **`115 / 199` (`57.79%`)**, and **`56 / 66` (`84.85%`)** in *Banking & Finance*.
- **Why this is not a $k=2$ selector score:** This union uses ground-truth rubric verdicts to count any criterion passed in either output. A realizable selector that chooses one complete deliverable per task cannot combine mutually exclusive per-criterion advantages from two separate documents. Even an oracle whole-response selector would pick the augmented deliverable in all four tasks and remain at **`99 / 199` (`49.75%`)** (`44 / 66` in Banking).
- **Implication for Agent Harnesses:** The `+53` gains and `-16` losses (`+13 / -12` in Banking) demonstrate substantial criterion-level complementarity between a playbook-focused pass and a full-text diff pass, motivating **rubric-blind candidate synthesis/merging** rather than winner-take-all rollout selection.
- **No Direct Comparison to Published `Harness²` Table 2:** Published `Harness²` scores (e.g., `81.9%` at $k=1$ and `84.5%` at $k=5$ with Gemini 3.5 Flash) use different foundation models, task subsets, and recursive training/selection protocols, and should not be directly equated with the single-task Banking oracle union.

---

## 4. Qualitative Observations and Limits of Attribution

### 4.1 Qualitative Task Patterns
- **Litigation (`1/34` $\rightarrow$ `19/34`, `+18 / -0`):** Pre-indexing plain-text mirrors of the 6 court filings allowed the solver to complete the opposition brief within the turn budget and address FRCP Rule 9(b) particularity, forum-selection scope, and accrual timing criteria.
- **Structured Finance (`3/37` $\rightarrow$ `12/37`, `+10 / -1`):** Document indexing and hierarchy prompts helped surface discrepancies between the Indenture and the Offering Memorandum (such as Reserve Account replenishment priority and Class C Note coupon differences).
- **Corporate M&A (`15/62` $\rightarrow$ `24/62`, `+12 / -3`):** Extracting tabular schedules alongside SPA text helped connect working-capital collar modifications to the balance sheet figures in `dataforge-financial-summary.xlsx`.
- **Banking & Finance (`43/66` $\rightarrow$ `44/66`, `+13 / -12`):** Full-text markup diffing recovered 13 criteria where the negotiation playbook was silent (such as deleted maturity extension options), but lost 12 criteria passed by the base run, yielding a net gain of 1 criterion.

### 4.2 Bundled Intervention and Implementation Boundaries
1. **Bundled Intervention:** Because plain-text mirrors, clause-difference tables, longer system/skill prompts (`9,456` vs. `2,333` chars), increased solver token expenditure (`+76.3%`), and container checks were introduced together, the `+18.59 pp` improvement cannot be causally attributed to a single mechanism without component ablations and a parsing-matched baseline.
2. **Differences Between the Inspected Audit Script and the Formal v2 Specification:**
   - `benchmarks/deltoryx_lab/scripts/deltoryx_audit.py` assigns document authority via filename heuristics, extracts at most the first 80 paragraphs per document with page locators set to `1`, and assigns fixed confidence constants by source tier.
   - Records are labelled `deductive` without executing the formal rule-and-premise proof checker specified in Section 6 of the paper, and opinion values use fixed constants rather than empirical calibration or dependence-aware scoring.
   - The `verified=true` status in the 4 saved `DELTORYX-MERKLE-SHA256-v2` certificates represents a cryptographic self-check over recorded artifacts, not a proof of semantic accuracy or complete rubric satisfaction.

---

## 5. Repository Artifacts

- **Component Tree:** [`benchmarks/deltoryx_lab/`](../benchmarks/deltoryx_lab/)
- **CLI Indexing & Verification Script:** [`benchmarks/deltoryx_lab/scripts/deltoryx_audit.py`](../benchmarks/deltoryx_lab/scripts/deltoryx_audit.py)
- **Skill Protocol:** [`benchmarks/deltoryx_lab/skills/evidence_intelligence/SKILL.md`](../benchmarks/deltoryx_lab/skills/evidence_intelligence/SKILL.md)
- **A/B Benchmark Runner:** [`benchmarks/run_ab_benchmark.py`](../benchmarks/run_ab_benchmark.py)

