"""
Evidence Intelligence v2.0 — End-to-End Reference Pipeline (ClaimLayer + Deltoryx Core)

PROPRIETARY & CONFIDENTIALITY NOTICE
(c) Francisco Hernandez de Blas - Deltoryx / ClaimLayer. All rights reserved.
Licensed under Business Source License 1.1 (BSL 1.1).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure repository root and claim-layer/src are importable
_HERE = Path(__file__).resolve()
for parent in _HERE.parents:
    if (parent / "core").is_dir() and (parent / "claim-layer" / "src").is_dir():
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        if str(parent / "claim-layer" / "src") not in sys.path:
            sys.path.insert(0, str(parent / "claim-layer" / "src"))
        break
    if (parent / "src" / "core").is_dir() and (parent / "src").is_dir():
        if str(parent / "src") not in sys.path:
            sys.path.insert(0, str(parent / "src"))
        break

from claimlayer import ClaimLayer, LLMQueryRouter, LLMValueNormalizer
from core.epistemic_judge import EpistemicJudge
from core.interfaces import BLOCKED_INFERENCE_TYPES, INFERENCE_WEIGHTS, Claim, SourceRef

# --- Epistemic Hierarchy v2.0 (Deterministic Ground Truth) ---
EPISTEMIC_TABLE = {
    "Deductive": ("deductive", 0.95),
    "deductive": ("deductive", 0.95),
    "Syntactic": ("syntactic", 0.95),
    "syntactic": ("syntactic", 0.95),
    "Arithmetic": ("arithmetic", 0.95),
    "arithmetic": ("arithmetic", 0.95),
    "Logical": ("logical", 0.95),
    "logical": ("logical", 0.95),
    "Semantic": ("semantic", 0.90),
    "semantic": ("semantic", 0.90),
    "Spatial": ("spatial", 0.90),
    "spatial": ("spatial", 0.90),
    "Common Sense": ("common_sense", 0.65),
    "common_sense": ("common_sense", 0.65),
    "Causal": ("causal", 0.55),
    "causal": ("causal", 0.55),
    "Inductive": ("inductive", 0.55),
    "inductive": ("inductive", 0.55),
    "Multi-hop": ("multi_hop", 0.50),
    "multi_hop": ("multi_hop", 0.50),
    "Probabilistic": ("probabilistic", 0.40),
    "probabilistic": ("probabilistic", 0.40),
}
BLOCKED_TYPES = {
    "abductive": 0.10,
    "Abductive": 0.10,
    "heuristic": 0.10,
    "Heuristic": 0.10,
    "narrative": 0.00,
    "Narrative": 0.00,
    "counterfactual": 0.00,
}

# Backward compatibility alias
TABLA_EPISTEMICA = EPISTEMIC_TABLE
TIPOS_BLOQUEADOS = BLOCKED_TYPES


class OpenAIEmbeddingProvider:
    """Wrapper for OpenAI text-embedding-3-small."""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        self.api_key = api_key
        self.model = model

    def embed_text(self, text: str) -> list[float]:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        resp = client.embeddings.create(input=[text], model=self.model)
        return resp.data[0].embedding


def extract_claims_and_question(user_text: str, api_key: str) -> dict[str, Any]:
    """Phase 1: Structured Ontological Extraction."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    system_prompt = (
        "You are an Epistemological and Ontological Extractor. "
        "Decompose input into atomic Evidence Units (entity, predicate, value). "
        "Assign unique IDs (c1, c2, ...), quote, page, and paragraph_id. "
        "Return EXCLUSIVELY valid JSON: {'claims': [...], 'question': '...'}"
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content or "{}")


def infer_facts(claims: list[dict[str, Any]], question: str, api_key: str) -> dict[str, Any]:
    """Phase 2a: Inference proposal (subject to EpistemicJudge review)."""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    system_prompt = (
        "You are an Inference Proposal Engine. "
        "Given verified facts and a question, propose an inference. "
        "You MUST list premise IDs in 'premises'. "
        "Return EXCLUSIVELY valid JSON: "
        "{'id': 'inf_1', 'entity': '...', 'predicate': '...', 'value': '...', "
        "'inferred_fact': '...', 'inference_type': '...', 'premises': ['c1']}"
    )
    user_payload = f"Facts: {json.dumps(claims, ensure_ascii=False)}\nQuestion: {question}"
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content or "{}")


def apply_epistemic_rules(
    inf_data: dict[str, Any],
    verified_ids: set[str],
    ledger_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 2b: Decoupled Epistemic Judge review & monotonic closure."""
    judge = EpistemicJudge()
    raw_type = inf_data.get("inference_type", "abductive")
    inferred_text = inf_data.get("inferred_fact") or inf_data.get("value") or ""
    premises = [str(p) for p in inf_data.get("premises", [])]
    speaker_role = inf_data.get("speaker_role")

    audit = judge.audit_candidate(
        text=inferred_text,
        inferred_type=raw_type,
        premises=premises,
        verified_ledger_ids=verified_ids,
        ledger_map=ledger_map or {},
        speaker_role=speaker_role,
    )

    inf_data["canonical_type"] = audit.epistemic_type
    inf_data["confidence"] = round(audit.effective_confidence, 4)
    inf_data["effective_weight"] = audit.effective_weight
    inf_data["accepted"] = audit.accepted
    inf_data["audit_reason"] = audit.reason
    return inf_data


def format_response_with_citations(cl_result: dict[str, Any]) -> str:
    """Phase 5: Formatted verifiable response with citations."""
    results = cl_result.get("results", [])
    if not results:
        return f"Conclusion: {cl_result.get('answer', 'Insufficient verified evidence.')}\n[No verified citations]"

    lines: list[str] = []
    for r in results:
        val = r.get("canonical_value") if r.get("canonical_value") is not None else r.get("value")
        cits = r.get("formatted_citations") or ""
        lines.append(f"- {val} (Confidence: {r.get('confidence', 0.0):.4f}) {cits}".strip())

    citations = cl_result.get("formatted_citations") or ""
    return "\n".join(lines) + (f"\n\nVerified citations: {citations}" if citations else "")


# Compatibility aliases
extraer_hechos_y_pregunta = extract_claims_and_question
inferir_hechos = infer_facts
aplicar_reglas_epistemicas = apply_epistemic_rules
formatear_respuesta_con_citas = format_response_with_citations


def run_offline_verification_demo() -> ClaimLayer:
    """Deterministic offline demo of all Evidence Intelligence v2.0 modules."""
    print("==================================================================")
    print("OFFLINE DETERMINISTIC DEMO — EVIDENCE INTELLIGENCE v2.0")
    print("==================================================================\n")

    cl = ClaimLayer()

    case_claims: list[dict[str, Any] | str] = [
        # Periodic invoice 1
        {"id": "c1", "entity": "ACME", "canonical_entity": "ACME", "predicate": "invoice_q1", "canonical_predicate": "amount",
         "value": "25.000 €", "canonical_value": 25000.0, "concept_fingerprint": "invoice:A-01:Q1", "unit": "EUR",
         "speaker_role": "COURT_FINDING", "claim_type": "fact",
         "quote": "Proven Fact 1: Invoice A-01 for Q1 unpaid in the amount of 25,000 EUR.", "page": 2, "paragraph_id": "p1", "origin_tier": "PRIMARY_DOCUMENT"},
        # Periodic invoice 2
        {"id": "c2", "entity": "ACME", "canonical_entity": "ACME", "predicate": "invoice_q2", "canonical_predicate": "amount",
         "value": "25.000 €", "canonical_value": 25000.0, "concept_fingerprint": "invoice:A-02:Q2", "unit": "EUR",
         "speaker_role": "COURT_FINDING", "claim_type": "fact",
         "quote": "Proven Fact 2: Invoice A-02 for Q2 unpaid in the amount of 25,000 EUR.", "page": 5, "paragraph_id": "p3", "origin_tier": "PRIMARY_DOCUMENT"},
        # Periodic invoice 3
        {"id": "c3", "entity": "ACME", "canonical_entity": "ACME", "predicate": "amount",
         "value": "25.000 €", "canonical_value": 25000.0, "concept_fingerprint": "invoice:A-03:Q3", "unit": "EUR",
         "speaker_role": "COURT_FINDING", "claim_type": "fact",
         "quote": "Proven Fact 3: Invoice A-03 for Q3 unpaid in the amount of 25,000 EUR.", "page": 8, "paragraph_id": "p2", "origin_tier": "PRIMARY_DOCUMENT"},
        # Contradictory external claim (OriginTier = EXTERNAL_INJECTED -> superseded by PRIMARY_DOCUMENT)
        {"id": "c4", "entity": "ACME", "predicate": "amount", "value": "5.000 €", "claim_type": "fact",
         "quote": "External press report states that debt amounts to 5,000 EUR.", "page": 1, "paragraph_id": "p9", "origin_tier": "EXTERNAL_INJECTED"},
        # 3-Hop Multihop Chain
        {"id": "c5", "entity": "Grupo_Alfa", "predicate": "parent_company", "value": "Filial_Sur", "claim_type": "fact",
         "quote": "Proven Fact 4: Grupo_Alfa is the parent entity of Filial_Sur.", "page": 3, "paragraph_id": "p2", "origin_tier": "PRIMARY_DOCUMENT"},
        {"id": "c6", "entity": "Filial_Sur", "predicate": "sole_director", "value": "Juan_Perez", "claim_type": "fact",
         "quote": "Proven Fact 5: Filial_Sur has Juan_Perez as sole director.", "page": 4, "paragraph_id": "p1", "origin_tier": "PRIMARY_DOCUMENT"},
        {"id": "c7", "entity": "Juan_Perez", "predicate": "offense", "value": "fraud", "claim_type": "petitum",
         "quote": "Prayer: Juan_Perez is charged with continuous fraud.", "page": 9, "paragraph_id": "p4", "origin_tier": "PRIMARY_DOCUMENT"},
        # Unratified Party Allegation (must be blocked by EpistemicJudge)
        {"id": "c8", "entity": "Juan_Perez", "predicate": "affirmative_defense", "value": "statute_of_limitations", "claim_type": "fact",
         "quote": "The defense alleges that statute of limitations applies without documentary support.", "page": 10, "paragraph_id": "p2",
         "inference_type": "Deductive", "premises": ["c7"]},
        # Layout Noise (must be pruned by ClaimConsolidator)
        "Page 10 of 45",
    ]

    cl.ingest(case_claims)
    print(f"Verified claims in ledger: {len(cl._core_claims)}")
    print(f"Blocked / pruned claims: {len(cl.blocked_claims)}")
    for b in cl.blocked_claims:
        print(f"  [BLOCKED] reason={b.get('reason')} | text='{b.get('text')}'")

    print("\n--- Query 1: Deterministic Aggregation (Sum of 3 quarterly invoices Q1+Q2+Q3 of 25,000 EUR) ---")
    r_sum = cl.ask("What is the total amount of invoices for ACME?")
    print(format_response_with_citations(r_sum))
    print(f"Jøsang Subjective Opinion w=(b,d,u): {r_sum.get('subjective_opinion')}")
    print(f"Merkle SHA-256 Certificate Verified: {cl.verify_response_integrity(r_sum)} (root={r_sum.get('epistemic_certificate', {}).get('merkle_root', '')[:16]}...)")

    print("\n--- Query 2: 3-Hop Multihop Reasoning (Gödel T-Norm + Dijkstra Max-Min) ---")
    r_mh = cl.ask("What offense is linked to Grupo_Alfa?")
    print(format_response_with_citations(r_mh))
    print(f"Merkle SHA-256 Certificate Verified: {cl.verify_response_integrity(r_mh)} (root={r_mh.get('epistemic_certificate', {}).get('merkle_root', '')[:16]}...)")
    return cl


demo_determinista_offline = run_offline_verification_demo


def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or "--demo" in sys.argv:
        run_offline_verification_demo()
        return

    user_input = "I want to wash my car, the car wash is 50 meters away, should I walk or drive?"
    print("==================================================")
    print(f"USER INPUT: '{user_input}'")
    print("==================================================\n")

    print("--- STEP 1: Structured Ontological Extraction (v2.0) ---")
    extraction = extract_claims_and_question(user_input, api_key)
    base_claims = extraction.get("claims", [])
    question = extraction.get("question", "")
    print(f"Extracted claims ({len(base_claims)}): {json.dumps(base_claims, ensure_ascii=False, indent=2)}")
    print(f"Extracted question: '{question}'\n")

    print("--- STEPS 2 & 3: Consolidation & Ingestion in ClaimLayer v2.0 ---")
    provider = OpenAIEmbeddingProvider(api_key=api_key)
    cl = ClaimLayer(embedding_provider=provider)
    cl.ingest(base_claims)
    print(f"Base claims verified in ledger: {len(cl._core_claims)}")

    print("\n--- STEP 2b: Inference Engine + External Epistemic Judge (EpistemicJudge) ---")
    inference_data = infer_facts(base_claims, question, api_key)
    inference_data = apply_epistemic_rules(
        inference_data,
        verified_ids=cl._verified_ids,
        ledger_map=cl._ledger_map,
    )
    print("Epistemic audit result on candidate inference:")
    print(json.dumps(inference_data, indent=2, ensure_ascii=False) + "\n")

    if inference_data.get("accepted", False):
        cl.ingest([inference_data])
        print(f"Inference verified and injected (Audited confidence: {inference_data['confidence']}).")
    else:
        print(f"Inference blocked by EpistemicJudge: {inference_data.get('audit_reason')}")

    print("\n--- STEP 4: Deterministic Resolution in ClaimLayer v2.0 ---")
    cl_result = cl.ask(question)
    for res in cl_result.get("results", []):
        print(
            f"Retrieved: [{res['entity']}.{res['predicate']}] = '{res['value']}' "
            f"(Confidence: {res['confidence']:.4f}) {res.get('formatted_citations', '')}"
        )

    print("\n--- STEP 5: Verifiable Last-Mile Output with Mandatory Citations ---")
    print(format_response_with_citations(cl_result))


if __name__ == "__main__":
    main()
