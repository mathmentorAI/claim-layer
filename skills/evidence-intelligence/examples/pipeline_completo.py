"""
Evidence Intelligence v2.0 — pipeline de referencia end-to-end (ClaimLayer + Deltoryx Core)

AVISO DE TITULARIDAD Y CONFIDENCIALIDAD
(c) Francisco Hernandez de Blas - Deltoryx. Todos los derechos reservados.
Material confidencial entregado en regimen de licencia de evaluacion temporal, gratuita, no
exclusiva y sin derecho de uso comercial, conforme al Acuerdo de Confidencialidad y Licencia
de Evaluacion suscrito con ZC TECH PARTNERS SL. Prohibida su copia, distribucion, publicacion,
modificacion, ingenieria inversa o uso fuera del alcance del Anexo I de dicho Acuerdo.
Prohibida la eliminacion de este aviso.
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

from claimlayer import ClaimLayer, LLMQueryRouter, LLMValueNormalizer
from core.epistemic_judge import EpistemicJudge
from core.interfaces import BLOCKED_INFERENCE_TYPES, INFERENCE_WEIGHTS, Claim, SourceRef

# --- Tabla Epistemológica v2.0 (fuente de verdad determinista; ver SKILL.md) ---
TABLA_EPISTEMICA = {
    "Deductiva": ("deductive", 0.95),
    "deductive": ("deductive", 0.95),
    "Sintáctica": ("syntactic", 0.95),
    "syntactic": ("syntactic", 0.95),
    "Aritmética": ("arithmetic", 0.95),
    "arithmetic": ("arithmetic", 0.95),
    "Lógica": ("logical", 0.95),
    "logical": ("logical", 0.95),
    "Semántica": ("semantic", 0.90),
    "semantic": ("semantic", 0.90),
    "Espacial": ("spatial", 0.90),
    "spatial": ("spatial", 0.90),
    "Sentido Común": ("common_sense", 0.65),
    "common_sense": ("common_sense", 0.65),
    "Causal": ("causal", 0.55),
    "causal": ("causal", 0.55),
    "Inductiva": ("inductive", 0.55),
    "inductive": ("inductive", 0.55),
    "Multi-hop": ("multi_hop", 0.50),
    "multi_hop": ("multi_hop", 0.50),
    "Probabilística": ("probabilistic", 0.40),
    "probabilistic": ("probabilistic", 0.40),
}
TIPOS_BLOQUEADOS = {
    "Narrativa", "narrative",
    "Abductiva", "abductive",
    "Heurística", "Heuristica", "heuristic",
    "counterfactual",
}


def aplicar_reglas_epistemicas(
    inferencia: dict[str, Any],
    verified_ids: set[str] | None = None,
    ledger_map: dict[str, Claim] | None = None,
) -> dict[str, Any]:
    """
    Juez Epistémico Desacoplado (v2.0):
    1. Elimina el auto-etiquetado libre del LLM auditando el texto, las citas y el speaker_role mediante EpistemicJudge.
    2. Exige premisas explícitas verificadas ('premises') para aceptar una inferencia como Deductiva.
    3. Aplica la Regla de Clausura Epistémica Monótona: Rank(Conclusión) <= min(Rank(Premisas)).
    4. Detecta y bloquea alegaciones unilaterales de parte sin ratificación judicial ('Hecho Probado').
    """
    raw_tipo = (inferencia.get("inference_type") or "").strip()
    if raw_tipo in TIPOS_BLOQUEADOS:
        inferencia["accepted"] = False
        inferencia["confidence"] = 0.0
        inferencia["motivo_bloqueo"] = f"Tipo bloqueado por reglas epistémicas: {raw_tipo}"
        return inferencia

    if raw_tipo not in TABLA_EPISTEMICA:
        inferencia["accepted"] = False
        inferencia["confidence"] = 0.0
        inferencia["motivo_bloqueo"] = f"Tipo no reconocido en la tabla: '{raw_tipo}'"
        return inferencia

    canonical_type, base_weight = TABLA_EPISTEMICA[raw_tipo]
    premises = list(inferencia.get("premises") or [])
    fact_text = str(inferencia.get("inferred_fact") or inferencia.get("value") or "")

    judge = EpistemicJudge()
    temp_claim = Claim(
        id=str(inferencia.get("id") or "inf_001"),
        entity=str(inferencia.get("entity") or "Expediente"),
        predicate=str(inferencia.get("predicate") or "inferencia"),
        value=str(inferencia.get("value") or fact_text),
        source=SourceRef(document_id="motor_inferencia_v2", page=1, paragraph_id="p_inf"),
        confidence=base_weight,
        inference_type=canonical_type,
        premises=premises,
        quote=fact_text,
        speaker_role=inferencia.get("speaker_role"),
    )

    audit = judge.audit_claim(
        temp_claim,
        verified_premise_ids=verified_ids,
        require_declared_premises=(verified_ids is not None),
        premise_lookup=ledger_map,
    )

    audited_type = audit.audited_type
    inferencia["audited_inference_type"] = audited_type
    if audit.is_overridden:
        inferencia["override_reason"] = audit.override_reason

    if audited_type in BLOCKED_INFERENCE_TYPES or audited_type in TIPOS_BLOQUEADOS:
        inferencia["accepted"] = False
        inferencia["confidence"] = 0.0
        inferencia["motivo_bloqueo"] = (
            audit.override_reason or f"Bloqueado tras auditoría epistémica ({audited_type})"
        )
        return inferencia

    inferencia["confidence"] = INFERENCE_WEIGHTS.get(audited_type, base_weight)
    inferencia["accepted"] = True
    return inferencia


class OpenAIEmbeddingProvider:
    def __init__(self, api_key: str):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)

    def embed(self, text: str) -> list[float]:
        response = self.client.embeddings.create(
            input=text,
            model="text-embedding-3-small",
        )
        return response.data[0].embedding


def extraer_hechos_y_pregunta(texto_crudo: str, api_key: str, model: str = "gpt-4o-mini") -> dict[str, Any]:
    """Fase 1 (v2.0): Extrae Unidades de Evidencia estructuradas con semántica universal asistida por LLM."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    system_prompt = """Eres un Extractor Epistemológico y Ontológico de alta precisión (v2.0).
Analiza el texto crudo proporcionado y descomponlo en Unidades de Evidencia atómicas estructuradas como tuplas (entity, predicate, value).

CATEGORÍAS ONTOLÓGICAS OBLIGATORIAS (claim_type):
1. "hecho": Hechos probados, eventos temporales, estados físicos, importes o pagos ejecutados, relaciones societarias o cargos.
2. "petitum": Pretensiones de las partes, súplicas, cuantías reclamadas o penas solicitadas.
3. "fundamento": Normas jurídicas, artículos legales, cláusulas contractuales o plazos pactados.
4. "prueba": Medios de prueba acreditados (periciales, documentales, testificales).

REGLAS ESTRICTAS:
- Asigna a cada hecho un ID único ("c1", "c2", ...), su página ("page") y párrafo ("paragraph_id", ej. "p1", "p2").
- Incluye en "quote" la cita literal exacta del texto (conservando menciones a trimestres Q1-Q4, códigos de factura, fechas o si es una alegación de parte vs. Hecho Probado).
- En "canonical_entity", normaliza el nombre canónico de la entidad resolviendo cargos, títulos o variantes societarias ("D. Juan Pérez García", "El Sr. Pérez" -> "Juan_Perez").
- En "canonical_predicate", normaliza el predicado hacia la ontología canónica ("honorarios_devengados", "retribucion_profesional" -> "amount").
- En "canonical_value", incluye la normalización canónica universal del valor ("value") en CUALQUIER idioma soportado por el LLM:
  * Cantidades monetarias o cifras escritas en letra ("ciento cuarenta y dos mil euros", "25.000 €") -> número puro (142000.0, 25000.0).
  * Plazos o duraciones en cualquier idioma ("treinta días", "trente jours", "dreißig Tage", "trinta dias") -> forma canónica estándar ("30 days") o escalar numérico (30).
  * Fechas en cualquier idioma ("15 de enero de 2026") -> formato ISO-8601 ("2026-01-15").
- En "concept_fingerprint", asigna una huella semántica corta de la partida ("invoice:A-01:Q1" vs "contract_total") y en "unit" la unidad o divisa ("EUR", "USD", "DAYS").
- En "speaker_role", indica el rol discursivo ("COURT_FINDING", "PARTY_ALLEGATION", "WITNESS_CLAIM", "CONTRACT_CLAUSE", "AUTHORITATIVE_FACT").
- NO deduzcas ni asumas hechos no explícitos.
- Si el texto contiene una pregunta, extráela en "question".

Devuelve EXCLUSIVAMENTE un JSON con esta estructura:
{
  "claims": [
    {
      "id": "c1",
      "entity": "Nombre_Entidad",
      "canonical_entity": "Entidad_Canonica",
      "predicate": "atributo_o_relacion",
      "canonical_predicate": "amount",
      "value": "valor_atomico_original",
      "canonical_value": 25000.0,
      "concept_fingerprint": "invoice:A-01:Q1",
      "unit": "EUR",
      "speaker_role": "COURT_FINDING",
      "claim_type": "hecho | petitum | fundamento | prueba",
      "quote": "cita textual exacta",
      "page": 1,
      "paragraph_id": "p1",
      "origin_tier": "PRIMARY_DOCUMENT"
    }
  ],
  "question": "pregunta extraída"
}"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": texto_crudo},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    return json.loads(response.choices[0].message.content)


def inferir_hechos(
    hechos_estructurados: list[dict[str, Any]],
    pregunta: str,
    api_key: str,
    model: str = "gpt-4o-mini",
) -> dict[str, Any]:
    """Fase 2 (v2.0): Propone una inferencia vinculando obligatoriamente los IDs de sus premisas ('premises')."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    system_prompt = """Eres un Motor de Inferencia Formal (v2.0).
Se te darán las Unidades de Evidencia verificadas (con sus IDs "c1", "c2", ...) y una Pregunta.
Tu objetivo es proponer una conclusión estructurada que conecte los hechos base e indicar OBLIGATORIAMENTE en "premises" la lista de IDs de los hechos base empleados.

IMPORTANTE:
- Tú NO decides el peso final ni si la inferencia se acepta; el Juez Epistémico externo (`EpistemicJudge`) verificará tus `premises` y aplicará la Clausura Epistémica Monótona.
- Clasifica la inferencia propuesta en "inference_type" usando uno de:
  "Deductiva", "Sintáctica", "Aritmética", "Lógica", "Semántica", "Espacial", "Sentido Común", "Causal", "Inductiva", "Multi-hop", "Probabilística", "Narrativa", "Abductiva", "Heurística".

Devuelve EXCLUSIVAMENTE un JSON válido con esta estructura:
{
  "id": "inf_001",
  "entity": "Entidad_Sujeto",
  "predicate": "relacion_deducida",
  "value": "valor_deducido",
  "inferred_fact": "Enunciado completo de la conclusión",
  "inference_type": "Deductiva",
  "premises": ["c1", "c2"]
}"""

    user_prompt = (
        f"Hechos Base Verificados:\n{json.dumps(hechos_estructurados, ensure_ascii=False, indent=2)}\n\n"
        f"Pregunta a resolver:\n{pregunta}"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    return json.loads(response.choices[0].message.content)


def formatear_respuesta_con_citas(cl_result: dict[str, Any], texto_generado: str | None = None) -> str:
    """Fase 5 (v2.0): Garantiza 100% de cobertura de citas [doc, Pág. X, Párrafo Y] en la salida final."""
    if cl_result.get("abstain") or not cl_result.get("results"):
        return "ABSTENCIÓN DETERMINISTA: No existe evidencia verificada suficiente en el expediente para responder a la consulta."

    citas = cl_result.get("formatted_citations") or ""
    if texto_generado:
        if citas and citas not in texto_generado:
            return f"{texto_generado.strip()}\n\nCitas verificadas: {citas}"
        return texto_generado.strip()

    # Síntesis determinista directa si no hay LLM local levantado
    lineas = [f"- {r['value']} (Confianza: {r['confidence']:.4f}) {r.get('formatted_citations', '')}".strip() for r in cl_result["results"]]
    cuerpo = "\n".join(lineas)
    return f"{cuerpo}\n\nCitas verificadas: {citas}".strip()


def run_offline_verification_demo() -> None:
    """Demostración determinista completa (sin requerir API key) de las mejoras v2.0 (Sprints 1-8)."""
    print("==================================================================")
    print("DEMO DETERMINISTA OFFLINE — EVIDENCE INTELLIGENCE v2.0 (Sprints 1-8)")
    print("==================================================================\n")

    cl = ClaimLayer()

    # 1. Ingesta estructurada con coordenadas, OriginTier, facturas trimestrales y grafo multihop
    hechos_expediente = [
        # Pagos periódicos simétricos (Q1, Q2, Q3 de 25.000 €) vs mención repetida
        {"id": "c1", "entity": "ACME", "predicate": "amount", "value": "25.000 €", "claim_type": "hecho",
         "quote": "Hecho Probado 1: Factura A-01 del primer trimestre (Q1) impagada por 25.000 €.", "page": 2, "paragraph_id": "p1", "origin_tier": "PRIMARY_DOCUMENT"},
        {"id": "c2", "entity": "ACME", "predicate": "amount", "value": "25.000 €", "claim_type": "hecho",
         "quote": "Hecho Probado 2: Factura A-02 del segundo trimestre (Q2) impagada por 25.000 €.", "page": 5, "paragraph_id": "p3", "origin_tier": "PRIMARY_DOCUMENT"},
        {"id": "c3", "entity": "ACME", "predicate": "amount", "value": "25.000 €", "claim_type": "hecho",
         "quote": "Hecho Probado 3: Factura A-03 del tercer trimestre (Q3) impagada por 25.000 €.", "page": 8, "paragraph_id": "p2", "origin_tier": "PRIMARY_DOCUMENT"},
        # Nota externa contradictoria (OriginTier = EXTERNAL_INJECTED -> debe ser descartada frente a PRIMARY_DOCUMENT)
        {"id": "c4", "entity": "ACME", "predicate": "amount", "value": "5.000 €", "claim_type": "hecho",
         "quote": "Nota externa de prensa sugiere que la deuda sería de 5.000 €.", "page": 1, "paragraph_id": "p9", "origin_tier": "EXTERNAL_INJECTED"},
        # Cadena Multihop de 3 saltos: Grupo_Alfa -> Filial_Sur -> Juan_Perez -> estafa_continuada
        {"id": "c5", "entity": "Grupo_Alfa", "predicate": "filial", "value": "Filial_Sur", "claim_type": "hecho",
         "quote": "Hecho Probado 4: Grupo_Alfa es matriz de su filial Filial_Sur.", "page": 3, "paragraph_id": "p2", "origin_tier": "PRIMARY_DOCUMENT"},
        {"id": "c6", "entity": "Filial_Sur", "predicate": "administrador", "value": "Juan_Perez", "claim_type": "hecho",
         "quote": "Hecho Probado 5: Filial_Sur tiene como administrador único a Juan_Perez.", "page": 4, "paragraph_id": "p1", "origin_tier": "PRIMARY_DOCUMENT"},
        {"id": "c7", "entity": "Juan_Perez", "predicate": "delito", "value": "estafa continuada", "claim_type": "petitum",
         "quote": "Petitum: Se imputa a Juan_Perez un delito de estafa continuada.", "page": 9, "paragraph_id": "p4", "origin_tier": "PRIMARY_DOCUMENT"},
        # Alegación de parte no ratificada (debe ser bloqueada por EpistemicJudge)
        {"id": "c8", "entity": "Juan_Perez", "predicate": "eximente", "value": "prescripción", "claim_type": "hecho",
         "quote": "La defensa sostiene que concurre prescripción sin respaldo documental.", "page": 10, "paragraph_id": "p2",
         "inference_type": "Deductiva", "premises": ["c7"]},
        # Ruido de maquetación (debe ser podado por ClaimConsolidator)
        "Página 10 de 45",
    ]

    cl.ingest(hechos_expediente)
    print(f"Claims verificados en el ledger: {len(cl._core_claims)}")
    print(f"Claims bloqueados / podados por auditoría: {len(cl.blocked_claims)}")
    for b in cl.blocked_claims:
        print(f"  [BLOQUEADO] motivo={b.get('reason')} | texto='{b.get('text')}'")

    print("\n--- Consulta 1: Agregación Determinista (Suma de 3 facturas trimestrales Q1+Q2+Q3 de 25.000 €) ---")
    r_sum = cl.ask("¿A cuánto asciende el importe total de las facturas de ACME?")
    print(formatear_respuesta_con_citas(r_sum))
    print(f"Opinión Subjetiva de Jøsang w=(b,d,u): {r_sum.get('subjective_opinion')}")
    print(f"Certificado Merkle SHA-256 verificado: {cl.verify_response_integrity(r_sum)} (root={r_sum.get('epistemic_certificate', {}).get('merkle_root', '')[:16]}...)")

    print("\n--- Consulta 2: Razonamiento Multihop de 3 Saltos (Semianillo de Gödel + Dijkstra Max-Min) ---")
    r_mh = cl.ask("¿Qué delito se vincula a Grupo_Alfa?")
    print(formatear_respuesta_con_citas(r_mh))
    print(f"Certificado Merkle SHA-256 verificado: {cl.verify_response_integrity(r_mh)} (root={r_mh.get('epistemic_certificate', {}).get('merkle_root', '')[:16]}...)")
    return cl


demo_determinista_offline = run_offline_verification_demo


def main():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or "--demo" in sys.argv:
        run_offline_verification_demo()
        return

    input_usuario = "quiero lavar el coche, el lavadero está a 50 metros, ¿voy andando o en coche?"
    print("==================================================")
    print(f"TEXTO DEL USUARIO: '{input_usuario}'")
    print("==================================================\n")

    print("--- PASO 1: Extracción Ontológica Estructurada (v2.0) ---")
    extraccion = extraer_hechos_y_pregunta(input_usuario, api_key)
    hechos_base = extraccion.get("claims", [])
    pregunta = extraccion.get("question", "")
    print(f"Hechos extraídos ({len(hechos_base)}): {json.dumps(hechos_base, ensure_ascii=False, indent=2)}")
    print(f"Pregunta extraída: '{pregunta}'\n")

    print("--- PASO 2 y 3: Consolidación e Ingesta en ClaimLayer v2.0 ---")
    provider = OpenAIEmbeddingProvider(api_key=api_key)
    cl = ClaimLayer(embedding_provider=provider)
    cl.ingest(hechos_base)
    print(f"Hechos base verificados en el ledger: {len(cl._core_claims)}")

    print("\n--- PASO 2b: Motor de Inferencia + Juez Epistémico Externo (EpistemicJudge) ---")
    inferencia_data = inferir_hechos(hechos_base, pregunta, api_key)
    inferencia_data = aplicar_reglas_epistemicas(
        inferencia_data,
        verified_ids=cl._verified_ids,
        ledger_map=cl._ledger_map,
    )
    print("Resultado de la auditoría epistémica sobre la inferencia:")
    print(json.dumps(inferencia_data, indent=2, ensure_ascii=False) + "\n")

    if inferencia_data.get("accepted", False):
        cl.ingest([inferencia_data])
        print(f"Inferencia verificada e inyectada (Confianza auditada: {inferencia_data['confidence']}).")
    else:
        print(f"Inferencia bloqueada por EpistemicJudge: {inferencia_data.get('motivo_bloqueo')}")

    print("\n--- PASO 4: Resolución Determinista en ClaimLayer v2.0 ---")
    cl_result = cl.ask(pregunta)
    for res in cl_result.get("results", []):
        print(
            f"Recuperado: [{res['entity']}.{res['predicate']}] = '{res['value']}' "
            f"(Confianza: {res['confidence']:.4f}) {res.get('formatted_citations', '')}"
        )

    print("\n--- PASO 5: Última Milla Híbrida con Citas Obligatorias ---")
    print(formatear_respuesta_con_citas(cl_result))


if __name__ == "__main__":
    main()
