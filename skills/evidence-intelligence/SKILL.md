---
name: evidence-intelligence
description: Implements a deterministic Enterprise RAG v2.0 architecture using ClaimLayer, Typed Ontological Extraction, Contextual Consolidation, Decoupled Epistemic Judge with Monotonic Closure, Multihop Provenance Semirings (Gödel T-Norm + Dijkstra Max-Min), Non-Monotonic Truth Maintenance (JTMS), Allen's Temporal Interval Algebra, Jøsang's Subjective Logic, Merkle SHA-256 Cryptographic Certificates, and Deterministic Aggregation Engine.
---

# Skill: Evidence Intelligence (v2.0)

> **PROPRIETARY & CONFIDENTIALITY NOTICE**  
> © Francisco Hernández de Blas — Deltoryx / ClaimLayer. All rights reserved.  
> Licensed under the Business Source License 1.1 (BSL 1.1).  
> Free for non-production, testing, PoC, and academic evaluation use.  
> Production and commercial deployments require an explicit commercial license.  
> Converts automatically to MPL 2.0 on 2030-03-31. See the root LICENSE file.

This skill guides the construction and integration of an **Evidence Intelligence (v2.0)** system designed to eliminate hallucinations and enforce formal traceability across complex multi-document corpora (legal, clinical, financial, and compliance records). Under this paradigm, knowledge state $K_t = \mathcal{F}(E_t)$ is not assumed from unstructured text; it is mathematically computed from structured evidence units $e = (c, s, \gamma, \kappa)$, where $c = (\text{entity}, \text{predicate}, \text{value})$ and $\kappa = (\kappa_{\text{extraction}}, \kappa_{\text{structuring}})$.

---

## 5-Phase Architecture (v2.0)

When tasked with implementing this architecture for a project (legal due diligence, contract audit, clinical histories, financial reconciliation), systematically follow this 5-phase pipeline:

1. **Typed Ontological Extraction + Universal LLM-Assisted Normalization + Contextual Consolidation (`ClaimConsolidator`):**
   - Extract structured evidence units with `(id, entity, canonical_entity, predicate, canonical_predicate, value, canonical_value, concept_fingerprint, unit, speaker_role, claim_type, quote, page, paragraph_id, origin_tier, valid_from, valid_until)`.
   - **Universal Multilingual Value Normalization (`canonical_value` + `LLMValueNormalizer`):** The LLM extractor emits in `canonical_value` the canonical scalar form of numbers written in words, currency amounts, deadlines, or dates in **any language supported by the LLM** (e.g., *"one hundred forty-two thousand euros"* $\to 142000.0$, *"trente jours"* / *"dreißig Tage"* / *"trinta dias"* $\to \text{"30 days"} \to 30$, *"January 15, 2026"* $\to \text{"2026-01-15"}$). For unstructured text, `ClaimLayer(normalizer_fn=LLMValueNormalizer(...))` normalizes at ingestion time into a deterministic cache (`register_canonical_value`) with **0 ms query-time latency and 0 extra API calls during `ask()`**.
   - **Entity Coreference & Predicate Alias Resolution (`canonical_entity` / `canonical_predicate`):** Unifies name variations, corporate honorifics, or suffixes (*"John Smith Esq."*, *"Mr. Smith"* $\to$ `"John_Smith"`) and synonymous predicates (*"accrued_fees"*, *"professional_remuneration"* $\to$ `"amount"`), registered via `register_entity_alias` and `register_predicate_alias`.
   - **Concept Fingerprint (`concept_fingerprint`), Unit (`unit`), and Discursive Role (`speaker_role`):** Emits a semantic partition key (`concept_fingerprint`, e.g., `"invoice:A-01:Q1"` vs. `"contract_total"`), the ISO unit (`unit`: `"EUR"`, `"USD"`, `"DAYS"`, `"MG"`), and contextual attribution (`speaker_role`: `"COURT_FINDING"`, `"PARTY_ALLEGATION"`, `"WITNESS_CLAIM"`, `"MANAGEMENT_PROJECTION"`, `"PATIENT_SELF_REPORT"`, `"CONTRACT_CLAUSE"`).
   - Explicitly type each claim under 4 canonical domain categories: `fact` (established facts, events, physical states), `petitum` (claims, requested damages, prayer for relief), `grounds` (statutes, clauses, governing articles), and `evidence` (expert reports, notarized records, depositions).
   - At ingestion, `ClaimConsolidator` prunes layout artifacts (headers, page numbers) and merges intra-paragraph lexical variations only if spatial coordinates (`page`, `paragraph_id`) match and values satisfy quantitative/temporal compatibility ($\text{CanSubsume}$), preserving atomic mentions in `instances`.

2. **Explicit-Premise Inference Engine + Decoupled Epistemic Judge (`EpistemicJudge`) + Non-Monotonic Truth Maintenance (JTMS):**
   - **No Unrestricted LLM Self-Labeling:** The inference-generating LLM **never decides** whether its inference is accepted or its final weight; it is compelled to explicitly declare premise antecedent IDs (`"premises": ["c1", "c2"]`).
   - The deterministic Python classifier `EpistemicJudge` audits the statement, verbatim `quote`, and `speaker_role`:
     - Detects **unilateral party allegations or unverified projections** via lexical markers (*"the defense alleges"*, *"management projects"*) and structural section attribution (`speaker_role in {"PARTY_ALLEGATION", "WITNESS_CLAIM", "DEFENSE_CLAIM", "MANAGEMENT_PROJECTION", "PATIENT_SELF_REPORT"}`) lacking judicial ratifications (*"Proven Fact"*, *"auditor certifies"*), degrading them to `abductive` and blocking them.
     - Verifies that all declared premises exist in the verified ledger ($P \subseteq V_{\text{verified}}$) and enforces the **Transitive Monotonic Epistemic Closure Rule** over the premise DAG:
       $$\mathcal{E}^*(c_{\text{der}}) = \min\left(\mathcal{E}_{\text{lex}}(c_{\text{der}}), \min_{p \in \text{ancestors}(c_{\text{der}})} \mathcal{E}^*(p)\right)$$
   - **Non-Monotonic Truth Maintenance (JTMS — Pollock's *Undercutting Defeaters*):** When a foundational premise is revoked, expires (`valid_until`), or is superseded by a subsequent amendment (`is_state_supersession`), every derived conclusion depending on it in `premises` is automatically retracted in cascade (`retracted_by_jtms` / `undercut_by_inactive_premise`).

3. **Semantic Embeddings + Dual Confidence Decomposition:**
   - Vectorize each verified evidence unit and record formal confidence decomposition $\kappa = (\kappa_{\text{extraction}}, \kappa_{\text{structuring}})$, penalizing generic predicates relative to explicit ontological relationships.

4. **Deterministic Resolution in `ClaimLayer` v2.0 (`resolve_truth` + `OriginTier` + Provenance Semirings + Allen's Temporal Algebra + `AggregationEngine`):**
   - **Bounded Contradiction Attenuation (Dynamic Normalized Noisy-OR):** Opposing mass is bounded via $S_{\text{opp}} = 1 - \prod (1 - \tilde{w}(g_i))$, preserving confidence dynamic range (`0.55–0.99`) without collapsing to $1/N$.
   - **Origin Precedence Hierarchy (`OriginTier`):** `PRIMARY_DOCUMENT (100) > SECONDARY_ANNEX (50) > EXTERNAL_INJECTED (10)`. Primary governing instruments strictly prevail over informal notes or subordinate markups.
   - **Allen's Interval Algebra (`allen_interval_precedes`) & Point-in-Time Queries (`as_of`):** Disjoint validity intervals ($[f_1, u_1] \prec [f_2, u_2]$ where $u_1 \le f_2$) or explicit state supersessions (`is_state_supersession`) are archived in `superseded_states` without penalizing the active state as a contradiction, supporting historical queries (`as_of="YYYY-MM-DD"` or natural language: *"in June 2023"*).
   - **Multihop Reasoning with Provenance Semirings ($\bigoplus, \bigotimes$) & Dijkstra Max-Min Search:** `DependencyGraph` traverses 2- and 3-hop relational chains using **Dijkstra Max-Min Best-First Search** over **Attenuated Gödel's T-Norm** ($\bigotimes = \min(s_i) \times 0.95^{k-1}$), merges parallel disjoint paths via **Noisy-OR** ($\bigoplus$), and flags multi-hop contradictions.
   - **Deterministic Algebraic Aggregation with Unit Isolation (`AggregationEngine`):** Aggregation queries (`SUM`, `COUNT`, `LIST`, `AVG`, `MIN`, `MAX`) execute purely in code over canonical projection $\mathcal{C}(L) = L_{\text{top}} / {\sim_{\phi}}$, operating on `canonical_value`, strictly isolating incompatible units (`unit="EUR"` vs `"USD"` or `"DAYS"`), and preserving periodic payments (`Q1`, `Q2`, `Q3`) via their conceptual fingerprint $\phi(c)$ (`concept_fingerprint`).

5. **Verifiable Last-Mile with Mandatory Citations (100% Coverage), Jøsang Subjective Logic $\omega=(b,d,u)$, and Merkle SHA-256 Certificates:**
   - The final output includes structured citations `cl_result["formatted_citations"]` (`[doc, Page X, Paragraph Y]`), subjective opinion $\omega = (b, d, u, a)$ on the simplex $b + d + u = 1$ (`subjective_opinion`, separating evidential conflict $d$ from epistemic vacuity $u$), and the cryptographic custody certificate `epistemic_certificate` (`DELTORYX-MERKLE-SHA256-v2`, verified offline via `ClaimLayer.verify_response_integrity(cl_result)`).

---

## ⚡ Initialization Checklist (Ask the user before generating code)

When invoked, offer two setup paths:

**Option A (Quickstart / Default):** *"I can set up the default Evidence Intelligence v2.0 configuration (OpenAI `gpt-4o-mini` for typed extraction and premise proposals, local deterministic hash provider for zero-overhead vectorization, SQLite ClaimLayer v2.0, `EpistemicJudge`, `DependencyGraph`, and `AggregationEngine`). Shall we proceed with defaults?"*

**Option B (Custom / Enterprise):** If customization is preferred, ask:
1. **LLM Engine (Phases 1 & 2):** Which model for typed ontological extraction and inference proposal? (e.g., GPT-4.1, Gemini 3.5 Flash, Claude Opus 5, gpt-4o-mini).
2. **Embeddings (Phase 3):** Which provider for evidence vectorization? (e.g., OpenAI `text-embedding-3-small`, `all-MiniLM-L6-v2`, or `SimpleHashEmbeddingProvider`).
3. **Storage (Phase 4):** In-memory SQLite (clean per test run) or persistent database?
4. **Generative LLM (Phase 5):** Which provider for final synthesis drafting?
5. **Domain Ontology:** What document types (legal agreements, medical protocols, financial statements) and `OriginTier` precedence rules apply?

> 🔒 **SECURITY DIRECTIVE:** Never hardcode API keys into generated code. Always retrieve credentials dynamically from environment variables (`os.environ.get("OPENAI_API_KEY")`).

---

## Epistemic Hierarchy & Monotonic Closure (Phase 2 — `EpistemicJudge`)

Acceptance and weights are enforced deterministically by `EpistemicJudge`:

| Inference Type (`inference_type`) | Epistemic Rank | Accepted in Strict Grounding? | Structural Weight (`INFERENCE_WEIGHTS`) |
| :--- | :---: | :---: | :---: |
| **`deductive` / `arithmetic` / `logical` / `syntactic`** | `90 – 100` | Yes (verified premises required) | `1.00` |
| **`semantic` / `spatial`** | `85` | Yes | `0.90` |
| **`inductive`** | `70` | With caution | `0.55` |
| **`common_sense` / `temporal` / `causal` / `multi_hop`** | `50 – 65` | Verified | `0.50 – 0.65` |
| **`probabilistic`** | `40` | Estimation only | `0.40` |
| **`abductive` (unverified allegations / `PARTY_ALLEGATION`)** | `50` | **BLOCKED (`Reason.BLOCKED_INFERENCE`)** | `0.10` (Blocked) |
| **`heuristic`** | `30` | **BLOCKED (`Reason.BLOCKED_INFERENCE`)** | `0.10` (Blocked) |
| **`narrative` / `counterfactual`** | `10` | **BLOCKED (`Reason.BLOCKED_INFERENCE`)** | `0.00` (Blocked) |

---

## Reference Prompts (v2.0)

### Prompt 1: Structured Ontological Extractor with Universal Semantics
```text
You are a high-precision Epistemological & Ontological Extractor.
Decompose the text into atomic Evidence Units structured as (entity, predicate, value).

MANDATORY ONTOLOGICAL CATEGORIES (claim_type):
1. "fact": Established facts, objective temporal events, completed payments, corporate titles.
2. "petitum": Party claims, requested damages, prayer for relief.
3. "grounds": Statutory articles, contractual provisions, agreed covenants.
4. "evidence": Proven exhibits, expert reports, notarized instruments.

RULES:
- Assign a unique ID ("c1", "c2", ...), page number ("page"), and paragraph ("paragraph_id").
- Include the exact verbatim quote in "quote".
- Normalize canonical entity in "canonical_entity" and canonical predicate in "canonical_predicate".
- In "canonical_value", normalize numbers, currencies, durations, or dates in ANY language to standard scalar/ISO format.
- Set "concept_fingerprint" (e.g., "invoice:A-01:Q1" vs "contract_total") and "unit" ("EUR", "USD", "DAYS").
- Set "speaker_role" based on document context: "COURT_FINDING", "PARTY_ALLEGATION", "WITNESS_CLAIM", "CONTRACT_CLAUSE", or "AUTHORITATIVE_FACT".
- Do NOT merge distinct payment installments or periods into a single claim.

Return EXCLUSIVELY JSON:
{
  "claims": [
    {
      "id": "c1",
      "entity": "Entity_Name",
      "canonical_entity": "Canonical_Entity",
      "predicate": "attribute_or_relation",
      "canonical_predicate": "amount",
      "value": "original_text_value",
      "canonical_value": 142000.0,
      "concept_fingerprint": "contract_total",
      "unit": "EUR",
      "speaker_role": "COURT_FINDING | PARTY_ALLEGATION | WITNESS_CLAIM | CONTRACT_CLAUSE | AUTHORITATIVE_FACT",
      "claim_type": "fact | petitum | grounds | evidence",
      "quote": "verbatim text quote",
      "page": 1,
      "paragraph_id": "p1",
      "origin_tier": "PRIMARY_DOCUMENT"
    }
  ],
  "question": "extracted question if present"
}
```

### Prompt 2: Formal Inference Engine with Explicit Premise Linkage
```text
You are a Formal Inference Engine.
Given verified Evidence Units (with IDs "c1", "c2", ...) and a Question, propose a structured conclusion.
You MUST declare in "premises" the exact list of foundational claim IDs supporting your deduction.

AUDIT RULE:
- You DO NOT decide if your inference is accepted. EpistemicJudge deterministically verifies premises and audits language.
- If a premise is an unverified party allegation, or if verified premises fail to entail the conclusion, the inference will be blocked.

Return EXCLUSIVELY JSON:
{
  "id": "inf_1",
  "entity": "Subject_Entity",
  "predicate": "deduced_relation",
  "value": "deduced_value",
  "inferred_fact": "Complete conclusion statement",
  "inference_type": "deductive | arithmetic | syntactic | semantic | spatial | common_sense | causal | inductive | multi_hop | probabilistic | abductive | heuristic | narrative",
  "premises": ["c1", "c2"]
}
```

---

## Reference Code

See `examples/complete_pipeline.py` within this skill for an end-to-end runnable reference implementation connecting structured extraction, `ClaimConsolidator`, `EpistemicJudge`, `DependencyGraph` with Gödel T-Norm, deterministic `AggregationEngine`, and verified citations.
