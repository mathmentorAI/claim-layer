# Empirical Legal Evaluation on Harvey Legal Agent Benchmark (LAB): Controlled Direct LLM Tool-Calling (Study A) and Autonomous Agent Harness Integration (Study B)

**Date:** October 20, 2026  
**Authors:** Francisco Jesús Hernández de Blas, Jose Zamora, & Deltoryx / ClaimLayer Team  
**Benchmark & Harness Context:** [`harveyai/harvey-labs`](https://github.com/harveyai/harvey-labs) (`b58a28a`) and [`google-research/harness2`](https://github.com/google-research/harness2) (`arXiv:2610.14224`)  
**Scope:** 4 multi-document legal tasks, 20 source commercial documents, 199 official binary rubric criteria  

---

## 1. Two Complementary Evaluation Protocols (Section 9.1)

Evaluating an evidence-structuring layer inside an autonomous coding agent (`OpenCode` with `bash` and filesystem access) confounds representation quality with agent shell exploration, prompt length (`9,456` vs. `2,333` characters), and file-packaging repairs. Conversely, evaluating an evidence layer only on short synthetic QA misses complex multi-document legal deliverables.

To address both boundaries, we report two paired evaluations on the same four Harvey LAB tasks (`199` criteria):

1. **Study A — Controlled Direct LLM Tool-Calling (`direct_rag` vs. `direct_claimlayer`, No Agent Harness, No `bash`):**
   - **Identical Solver Model:** `nvidia/nemotron-3-super-120b-a12b` (`temperature=0.0`, `enable_thinking=False`).
   - **Identical System Prompt & Tool Budget:** Both arms receive the exact same 650-character system prompt, no `bash` or filesystem shell, and an identical budget of **5 tool-calling rounds** followed by **1 final synthesis call**.
   - **Identical Container Packaging:** Both arms convert their final Markdown report to `.docx` via `pandoc` with automated ZIP header (`PK\x03\x04`) verification prior to grading (zero container failures in either arm).
   - **Identical Single Judge Across All 4 Tasks:** `evaluation.run_eval` with `nvidia/nemotron-3-super-120b-a12b`.
2. **Study B — Exploratory Autonomous Agent Harness Integration (`OpenCode` / `Harness²` Component Tree `c5`+`c7`):**
   - Compares the base `LAB/OpenCode` (`v1.14.18`, `tool_mode="base"`, `skill_mode="native"`, `openai/gpt-4.1`) agent against an augmented 8-component harness (`c1`–`c8`) after document-container repair.

---

## 2. Study A: Controlled Direct LLM Tool-Calling (No `bash`, No Harness Confounds)

### 2.1 Tool Surfaces Compared
- **Arm 1 (`direct_rag` — Standard Chunk Retrieval Tools):**
  Documents are parsed with the LAB parser and segmented into overlapping 1,200-character chunks (200-character overlap) indexed with BM25. The LLM has three tools:
  1. `list_documents()`
  2. `search_chunks(query, filename_filter, top_k)`
  3. `read_chunk_window(filename, start_chunk, num_chunks)`
- **Arm 2 (`direct_claimlayer` — ClaimLayer / Deltoryx Structured Evidence & Diff Tools):**
  All paragraphs across all case documents are indexed into ClaimLayer/Deltoryx claim units (with no 80-paragraph truncation), tagged with `OriginTier` source authority (`PRIMARY_DOCUMENT` Rank 100, `SECONDARY_ANNEX` Rank 50, `EXTERNAL_INJECTED` Rank 10), section locators, and numerical/date tokens, alongside the deterministic cross-document clause diff matrix (`compute_clause_diffs`). The LLM has three tools:
  1. `get_evidence_overview()` (returns `OriginTier` hierarchy inventory, redline diff pairs, and controlling playbooks/directives/tables)
  2. `get_clause_diffs(filter_query, offset, limit)` (queries the deterministic clause-by-clause redline diff matrix and quantitative deltas)
  3. `query_claims_and_provisions(query, filename_filter, top_k)` (queries typed claim units with authority rank and section/quantitative metadata)

### 2.2 Study A Paired Results (Same Solver & Same Judge Across All 4 Tasks)

| Task (`practice-area / slug`) | Docs | Criteria | `direct_rag` Passed | `direct_claimlayer` Passed | Difference (pp) | Criterion Transitions (Gain / Loss) | Oracle Union |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`litigation-dispute-resolution`**<br>`analyze-counterparty-motion-to-dismiss` | 6 | 34 | `26 / 34` (`76.47%`) | **`27 / 34` (`79.41%`)** | **`+2.94`** | `+3 / -2` | `29 / 34` (`85.29%`) |
| **`structured-finance-securitization`**<br>`compare-offering-memorandum-against-indenture` | 3 | 37 | `11 / 37` (`29.73%`) | **`11 / 37` (`29.73%`)** | **`+0.00`** | `+0 / -0` | `11 / 37` (`29.73%`) |
| **`corporate-ma`**<br>`analyze-counterparty-spa-markup` | 6 | 62 | `13 / 62` (`20.97%`) | **`32 / 62` (`51.61%`)** | **`+30.65`** | **`+23 / -4`** | `36 / 62` (`58.06%`) |
| **`banking-finance`**<br>`analyze-counterparty-markup-of-senior-secured-credit-facility-term-sheet` | 5 | 66 | `23 / 66` (`34.85%`) | **`53 / 66` (`80.30%`)** | **`+45.45`** | **`+30 / -0`** | `53 / 66` (`80.30%`) |
| **Total (Pooled, Single Judge)** | **20** | **199** | **`73 / 199` (`36.68%`)** | **`123 / 199` (`61.81%`)** | **`+25.13`** | **`+56 / -6`** | **`129 / 199` (`64.82%`)** |

### 2.3 Study A Summary Metrics & Resource Trade-offs

| Measure | `direct_rag` | `direct_claimlayer` | Difference / Ratio |
| :--- | :---: | :---: | :---: |
| **Pooled Criteria Passed** | `73 / 199` (`36.68%`) | `123 / 199` (`61.81%`) | **`+50` criteria (`+25.13 pp`, `1.68x`)** |
| **Unweighted Mean of Task Pass Rates** | `40.51%` | `60.26%` | **`+19.75 pp`** |
| **Criterion-Level Gains / Losses** | — | `+56` gained / `-6` lost | Net `+50` criteria |
| **Oracle Criterion Union (Post-hoc across both arms)** | — | `129 / 199` (`64.82%`) | `+6` criteria above `direct_claimlayer` alone |
| **Tool Calls Executed per Task** | `5` (`20` total) | `5` (`20` total) | Matched (`5` tool calls + `1` synthesis call) |
| **Recorded Solver Tokens** | `142,756` | `640,546` | `+497,790` tokens (`4.49x` context volume) |

### 2.4 Key Takeaways from Study A
1. **Substantial Gain on Redline & Quantitative Contract Tasks (`+30.65 pp` and `+45.45 pp`):** When the LLM is restricted to 5 tool-calling rounds without `bash`, standard BM25 chunk search (`direct_rag`) misses scattered clause modifications and fails to align counterparty markups with governing playbooks and financial tables (`13/62` on Corporate M&A; `23/66` on Banking & Finance). Providing structured claim units, `OriginTier` authority inventory, controlling tables, and deterministic clause-by-clause diffs (`direct_claimlayer`) raises Corporate M&A to **`32/62` (`51.61%`, `+23 / -4`)** and Banking & Finance to **`53/66` (`80.30%`, `+30 / -0`)** in a single rollout ($k=1$).
2. **Elimination of the Banking Regression Seen in Study B (`+30 / -0` vs. `+13 / -12`):** Removing the 80-paragraph indexing cap (`paragraphs[:80]`) present in the legacy `deltoryx_audit.py` script and exposing both the controlling playbook/directives and the full-text redline diff matrix through structured tools eliminated the 12 criterion losses observed in the `OpenCode` agent run.
3. **Context Density vs. Token Expenditure:** Because `get_evidence_overview` and `get_clause_diffs` return rich structured tables and redline pairs per call, `direct_claimlayer` consumes `640,546` solver tokens across the 4 tasks versus `142,756` for `direct_rag`.

---

## 3. Study B: Exploratory Autonomous Agent Harness Integration (`OpenCode` / `Harness²`)

### 3.1 Paired Task-Level Breakdown (After Container Repair, Same Judge Within Each Task)

| Task (`practice-area / slug`) | Docs | Criteria | Base Agent Passed | Augmented Agent Passed | Difference (pp) | Criterion Transitions (Gain / Loss) | Judge |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`litigation-dispute-resolution`**<br>`analyze-counterparty-motion-to-dismiss` | 6 | 34 | `1 / 34` (`2.94%`) | **`19 / 34` (`55.88%`)** | **`+52.94`** | `+18 / -0` | `openai/gpt-4.1` |
| **`structured-finance-securitization`**<br>`compare-offering-memorandum-against-indenture` | 3 | 37 | `3 / 37` (`8.11%`) | **`12 / 37` (`32.43%`)** | **`+24.32`** | `+10 / -1` | `nvidia/nemotron-3-super-120b-a12b` |
| **`corporate-ma`**<br>`analyze-counterparty-spa-markup` | 6 | 62 | `15 / 62` (`24.19%`) | **`24 / 62` (`38.71%`)** | **`+14.52`** | `+12 / -3` | `nvidia/nemotron-3-super-120b-a12b` |
| **`banking-finance`**<br>`analyze-counterparty-markup-of-senior-secured-credit-facility-term-sheet` | 5 | 66 | `43 / 66` (`65.15%`) | **`44 / 66` (`66.67%`)** | **`+1.52`** | `+13 / -12` | `openai/gpt-4.1` |
| **Total (Pooled)** | **20** | **199** | **`62 / 199` (`31.16%`)** | **`99 / 199` (`49.75%`)** | **`+18.59`** | **`+53 / -16`** | **Mixed (Matched per task)** |

### 3.2 Methodological Notes on Study B
- **Container Repair & Judge Pairing:** An earlier draft reported `47/199` vs. `106/199`, which combined a `31/62` GPT-4.1 evaluation on the repaired augmented Corporate M&A artifact with a `0/62` pre-repair base M&A score (when both M&A arms scored `0/62` pre-repair due to raw Markdown written to `.docx` paths). Table 3.1 enforces matching judges within each task after container repair (`15/62` vs. `24/62` under Nemotron).
- **Oracle Criterion Union vs. Whole-Deliverable Selection:** In Study B, the post-hoc criterion union across both arms is `115/199` (`57.79%`) and `56/66` (`84.85%`) in Banking. A whole-response selector is capped at `99/199` (`49.75%`).
- **Resource Use & Bundled Intervention:** Solver token usage in Study B rose from `220,320` (base) to `388,406` (augmented, `+76.3%`; logged solver cost `USD 1.8000` vs. `USD 2.4705`, `+37.3%`), with always-on prompt characters increasing from `2,333` to `9,456`.

---

## 4. Repository Artifacts

- **Direct LLM Tool-Calling Runner (Study A):** [`benchmarks/run_direct_tool_benchmark.py`](../benchmarks/run_direct_tool_benchmark.py)
- **Direct LLM Tool-Calling Summary & Per-Task Scores (Study A):** [`benchmarks/direct_tool_results/direct_tool_summary.json`](../benchmarks/direct_tool_results/direct_tool_summary.json)
- **OpenCode Component Tree (Study B):** [`benchmarks/deltoryx_lab/`](../benchmarks/deltoryx_lab/)
- **CLI Indexing & Verification Script (Study B):** [`benchmarks/deltoryx_lab/scripts/deltoryx_audit.py`](../benchmarks/deltoryx_lab/scripts/deltoryx_audit.py)
- **OpenCode A/B Benchmark Runner (Study B):** [`benchmarks/run_ab_benchmark.py`](../benchmarks/run_ab_benchmark.py)
