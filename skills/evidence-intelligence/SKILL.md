---
name: evidence-intelligence
description: Implementa una arquitectura Enterprise RAG determinista v2.0 utilizando ClaimLayer, Extracción Ontológica Tipada, Consolidación Contextual, Juez Epistémico Desacoplado con Clausura Monótona, Semianillos de Proveniencia Multihop (Norma T de Gödel + Dijkstra Max-Min), Mantenimiento de Verdad No-Monótono (JTMS), Álgebra Temporal de Intervalos de Allen, Lógica Subjetiva de Jøsang, Certificados Criptográficos de Merkle SHA-256 y Motor de Agregación Determinista.
---

# Skill: Evidence Intelligence (v2.0)

> **AVISO DE TITULARIDAD Y CONFIDENCIALIDAD**
> © Francisco Hernández de Blas — Deltoryx. Todos los derechos reservados.
> Material confidencial entregado en régimen de licencia de evaluación temporal, gratuita, no
> exclusiva y sin derecho de uso comercial, conforme al Acuerdo de Confidencialidad y Licencia de
> Evaluación suscrito con ZC TECH PARTNERS SL. Prohibida su copia, distribución, publicación,
> modificación, ingeniería inversa o uso fuera del alcance del Anexo I de dicho Acuerdo.
> Prohibida la eliminación de este aviso.

Esta skill guía la construcción e integración de un sistema de **Inteligencia de Evidencia (Evidence Intelligence v2.0)**, diseñado para eliminar alucinaciones y garantizar la trazabilidad formal sobre corpora complejos (jurídicos, clínicos, financieros y de cumplimiento). El núcleo de este paradigma es que el estado de conocimiento $K_t = F(E_t)$ no se asume desde texto libre, sino que se computa matemáticamente a partir de unidades de evidencia estructuradas $e = (c, s, \gamma, \kappa)$, donde $c = (\text{entity}, \text{predicate}, \text{value})$ y $\kappa = (\kappa_{\text{extraction}}, \kappa_{\text{structuring}})$.

## Arquitectura de 5 Fases (v2.0)

Cuando se te pida aplicar esta arquitectura a un proyecto (auditoría jurídica, análisis contractual, historiales clínicos), debes seguir siempre este pipeline de 5 fases:

1. **Extracción Ontológica Tipada + Normalización Semántica Universal Asistida por LLM + Consolidación Contextual (`ClaimConsolidator`):**
   - Extraer unidades de evidencia estructuradas con `(id, entity, canonical_entity, predicate, canonical_predicate, value, canonical_value, concept_fingerprint, unit, speaker_role, claim_type, quote, page, paragraph_id, origin_tier, valid_from, valid_until)`.
   - **Normalización Canónica Multilingüe de Valores (`canonical_value` + `LLMValueNormalizer`):** El LLM extractor emite en `canonical_value` la forma escalar canónica de cualquier cifra en letra, importe monetario, plazo o fecha en **cualquier idioma soportado por el LLM** (ej. *"ciento cuarenta y dos mil euros"* $\to 142000.0$, *"trente jours"* / *"dreißig Tage"* / *"trinta dias"* $\to \text{"30 days"} \to 30$, *"15 de enero de 2026"* $\to \text{"2026-01-15"}$). Para entradas de texto plano sin estructurar, `ClaimLayer(normalizer_fn=LLMValueNormalizer(...))` normaliza en ingesta y registra el resultado en caché determinista (`register_canonical_value`) con **0 ms de latencia y 0 llamadas adicionales durante `ask()`**.
   - **Resolución de Correferencia y Alias de Entidades (`canonical_entity`) y Predicados (`canonical_predicate`):** El LLM unifica variantes de nombres propios, cargos o sufijos societarios (*"D. Juan Pérez García"*, *"El Sr. Pérez"* $\to$ `"Juan_Perez"`; *"Filial Sur S.A."* $\to$ `"Filial_Sur"`) y sinónimos de predicados (*"honorarios_devengados"*, *"retribución_profesional"* $\to$ `"amount"`), registrándolos mediante `register_entity_alias` y `register_predicate_alias`.
   - **Huella Conceptual (`concept_fingerprint`), Unidad (`unit`) y Rol Discursivo (`speaker_role`):** El LLM emite `concept_fingerprint` (ej. `"invoice:A-01:Q1"` vs `"contract_total"`), la moneda o unidad ISO (`unit`: `"EUR"`, `"USD"`, `"DAYS"`, `"MG"`) y la atribución discursiva contextual (`speaker_role`: `"COURT_FINDING"`, `"PARTY_ALLEGATION"`, `"WITNESS_CLAIM"`, `"MANAGEMENT_PROJECTION"`, `"PATIENT_SELF_REPORT"`, `"CONTRACT_CLAUSE"`).
   - Tipar explícitamente cada extracción bajo las 4 categorías canónicas del dominio jurídico/documental: `hecho` (hechos probados, eventos temporales, estados físicos), `petitum` (pretensiones, súplicas, cuantías reclamadas), `fundamento` (normas, cláusulas, artículos aplicables) y `prueba` (periciales, testificales, documental).
   - Al ingerir en `ClaimLayer`, el módulo `ClaimConsolidator` poda automáticamente el ruido de maquetación (cabeceras, números de página/folio) y fusiona variantes léxicas intra-párrafo únicamente si cumplen identidad de coordenadas (`page`, `paragraph_id`) y compatibilidad cuantitativa/temporal ($\text{CanSubsume}$), conservando las instancias atómicas en `instances`.
2. **Motor de Inferencia con Premisas Explícitas + Juez Epistémico Desacoplado (`EpistemicJudge`) + Mantenimiento de Verdad No-Monótono (JTMS):**
   - **Prohibido el auto-etiquetado libre del LLM:** El LLM generador de inferencias **no decide** si su inferencia se acepta ni su peso final, y está obligado a declarar explícitamente los identificadores de las premisas antecedente (`"premises": ["c1", "c2"]`).
   - El clasificador determinista `EpistemicJudge` en Python audita el enunciado, su cita textual (`quote`) y su rol discursivo (`speaker_role`):
     - Detecta **alegaciones unilaterales de parte o proyecciones no verificadas** tanto por marcadores léxicos (*"la defensa sostiene"*, *"la dirección proyecta"*) como por atribución estructural de sección (`speaker_role in {"PARTY_ALLEGATION", "WITNESS_CLAIM", "DEFENSE_CLAIM", "MANAGEMENT_PROJECTION", "PATIENT_SELF_REPORT"}`) que carezcan de ratificación oficial (*"Hecho Probado"*, *"informe de auditoría certifica"*), degradándolas automáticamente a `abductive` y bloqueándolas.
     - Verifica que todas las premisas declaradas existan en el ledger verificado ($P \subseteq V_{\text{verified}}$) y aplica la **Regla de Clausura Epistémica Monótona Transitiva** sobre el DAG de premisas:
       $$\mathcal{E}^*(c_{\text{der}}) = \min\left(\mathcal{E}_{\text{lex}}(c_{\text{der}}), \min_{p \in \text{ancestros}(c_{\text{der}})} \mathcal{E}^*(p)\right)$$
   - **Mantenimiento de Verdad No-Monótono (JTMS — *Undercutting Defeaters* de Pollock):** Si una premisa base es revocada, expira (`valid_until`) o es reemplazada temporalmente por una adenda posterior (`is_state_supersession`), toda conclusión derivada que dependa de ella en `premises` queda retractada automáticamente en cascada (`retracted_by_jtms` / `undercut_by_inactive_premise`).
3. **Embeddings Semánticos + Descomposición Dual de Confianza:**
   - Vectorizar cada unidad de evidencia verificada y registrar la descomposición formal $\kappa = (\kappa_{\text{extraction}}, \kappa_{\text{structuring}})$, penalizando predicados genéricos frente a relaciones ontológicas específicas.
4. **Resolución Determinista en `ClaimLayer` v2.0 (`resolve_truth` + `OriginTier` + Semianillos de Proveniencia + Álgebra Temporal de Allen + `AggregationEngine`):**
   - **Atenuación Acotada de Contradicciones (Dynamic Normalized Noisy-OR):** La masa opositora se acota mediante $S_{\text{opp}} = 1 - \prod (1 - \tilde{w}(g_i))$, preservando el rango dinámico de confianza (`0.55–0.99`) sin colapsar a $1/N$.
   - **Jerarquía de Precedencia de Origen (`OriginTier`):** `PRIMARY_DOCUMENT (100) > SECONDARY_ANNEX (50) > EXTERNAL_INJECTED (10)`. Un documento principal prevalece siempre sobre notas externas o anexos secundarios.
   - **Álgebra Temporal de Intervalos de Allen (`allen_interval_precedes`) y Consultas *Point-in-Time* (`as_of`):** Dos estados con intervalos de validez disjuntos ($[f_1, u_1] \prec [f_2, u_2]$ con $u_1 \le f_2$) o actualizaciones explícitas (`is_state_supersession`) se archivan en `superseded_states` sin penalizar al estado vigente como contradicción, permitiendo además consultas históricas por fecha (`as_of="YYYY-MM-DD"` o en lenguaje natural: *"en junio de 2023"*).
   - **Razonamiento Multihop con Semianillos de Proveniencia ($\bigoplus, \bigotimes$) y Búsqueda Dijkstra Max-Min:** `DependencyGraph` explora cadenas relacionales de 2 y 3 saltos mediante **Dijkstra Max-Min Best-First Search** sobre la **Norma T de Gödel Atenuada** ($\bigotimes = \min(s_i) \times 0.95^{k-1}$), fusiona caminos paralelos disjuntos con **Noisy-OR** ($\bigoplus$) y detecta contradicciones multi-salto.
   - **Agregación Algebraica Determinista con Aislamiento de Unidades (`AggregationEngine`):** Las consultas de conteo, suma o desglose (`SUM`, `COUNT`, `LIST`, `AVG`, `MIN`, `MAX`) —detectadas por auto-descubrimiento de esquema o `LLMQueryRouter`— se ejecutan en código sobre la proyección canónica $\mathcal{C}(L) = L_{\text{top}} / {\sim_{\phi}}$, operando sobre `canonical_value`, aislando unidades incompatibles (`unit="EUR"` vs `"USD"` o `"DAYS"`) y preservando pagos periódicos simétricos (`Q1`, `Q2`, `Q3`) mediante su huella conceptual $\phi(c)$ (`concept_fingerprint`).
5. **Última Milla Híbrida con Citas Obligatorias (100% Cobertura), Lógica Subjetiva de Jøsang $\omega=(b,d,u)$ y Certificados Criptográficos de Merkle SHA-256:**
   - El generador final adjunta siempre las citas estructuradas `cl_result["formatted_citations"]` (`[doc, Pág. X, Párrafo Y]`), la opinión subjetiva $\omega = (b, d, u, a)$ en el símplex $b + d + u = 1$ (`subjective_opinion`, separando conflicto probatorio $d$ de vacuidad epistémica $u$) y el certificado criptográfico de custodia `epistemic_certificate` (`DELTORYX-MERKLE-SHA256-v2`, verificable offline mediante `ClaimLayer.verify_response_integrity(cl_result)`).

---

## ⚡ Checklist de Inicialización (¡Preguntar siempre al usuario!)

Cuando el usuario te pida invocar esta skill, ANTES de escribir el código de la arquitectura, ofrécele dos opciones de configuración:

**Opción A (Quickstart / Por defecto):** *"Veo que quieres implementar Evidence Intelligence v2.0. Si estás empezando, puedo montarte la configuración por defecto (OpenAI `gpt-4o-mini` para extracción ontológica tipada y propuesta de inferencias con premisas, `text-embedding-3-small` o proveedor determinista local para vectorización, SQLite con `ClaimLayer` v2.0, `EpistemicJudge`, `DependencyGraph` y `AggregationEngine`). ¿Te monto esto directamente?"*

**Opción B (Personalizada / Enterprise):** Si el usuario prefiere personalizarlo, hazle estas 5 preguntas:
1. **Sobre el Motor LLM (Fases 1 y 2):** *"¿Qué LLM usaremos para la Extracción Ontológica Tipada y propuesta de inferencias? (Ej: GPT-4.1, Gemini 3.5 Flash, Claude Opus 5, gpt-4o-mini)"*
2. **Sobre los Embeddings (Fase 3):** *"¿Qué proveedor de embeddings quieres usar para vectorizar las unidades de evidencia? (Ej: OpenAI `text-embedding-3-small`, `SentenceTransformer('all-MiniLM-L6-v2')`, o `SimpleHashEmbeddingProvider`)"*
3. **Sobre el Almacenamiento (Fase 4):** *"¿Cómo quieres persistir la base de datos de ClaimLayer? ¿SQLite temporal limpia por ejecución (recomendado para benchmarks sin contaminación de caché) o archivo persistente?"*
4. **Sobre el LLM Generativo (Fase 5):** *"¿A qué LLM final conectamos la última milla híbrida para redactar la síntesis con citas? (Ej: API de OpenAI/Anthropic/Google o LM Studio local)"*
5. **Sobre el Caso de Uso (Ontología y Precedencia):** *"¿Qué tipo de documentos vas a procesar (sentencias/contratos con `hecho`, `petitum`, `fundamento`, `prueba`, informes clínicos, etc.) y qué jerarquía `OriginTier` aplicamos entre documento principal y anexos?"*

> 🔒 **REGLA ESTRICTA DE SEGURIDAD:** BAJO NINGÚN CONCEPTO debes quemar (hardcode) claves de API en el código que generes. El código siempre debe extraerlas del entorno (`os.environ.get("OPENAI_API_KEY")`).

---

## Tabla Epistemológica y Clausura Monótona (Paso 2 — `EpistemicJudge`)

El peso numérico y la aceptación **NUNCA** se toman del auto-etiquetado del LLM; los impone `EpistemicJudge` en Python tras verificar:
1. Ausencia de marcadores heurísticos/abductivos y ausencia de **alegaciones unilaterales de parte sin ratificación judicial** (tanto léxicas como estructurales vía `speaker_role`).
2. Existencia de todas las premisas declaradas (`premises: ["c1", "c2"]`) en el conjunto de hechos verificados.
3. **Clausura Epistémica Monótona:** $\text{Rank}(\text{Conclusión}) \le \min_{p \in P} \text{Rank}(p)$.

| Tipo (`inference_type`) | Rango Epistémico | ¿Aceptada en Grounding Estricto? | Peso Estructural (`INFERENCE_WEIGHTS`) |
| :--- | :---: | :---: | :---: |
| **`deductive` / `arithmetic` / `logical` / `syntactic`** | `90 – 100` | Sí (requiere premisas verificadas) | `1.00` |
| **`semantic` / `spatial`** | `85` | Sí | `0.90` |
| **`inductive`** | `70` | Con precaución | `0.55` |
| **`common_sense` / `temporal` / `causal` / `multi_hop`** | `50 – 65` | Con verificación | `0.50 – 0.65` |
| **`probabilistic`** | `40` | Solo como estimación | `0.40` |
| **`abductive` (incluye alegaciones de parte no probadas / `PARTY_ALLEGATION`)** | `50` | **BLOQUEADA (`Reason.BLOCKED_INFERENCE`)** | `0.10` (Bloqueada) |
| **`heuristic`** | `30` | **BLOQUEADA (`Reason.BLOCKED_INFERENCE`)** | `0.10` (Bloqueada) |
| **`narrative` / `counterfactual`** | `10` | **BLOQUEADA (`Reason.BLOCKED_INFERENCE`)** | `0.00` (Bloqueada) |

---

## Prompts de Referencia (v2.0)

### Prompt 1: Extractor Ontológico Estructurado con Semántica Universal Asistida por LLM (`hecho | petitum | fundamento | prueba`)
```text
Eres un Extractor Epistemológico y Ontológico de alta precisión.
Analiza el texto proporcionado y descomponlo en Unidades de Evidencia atómicas estructuradas como tuplas (entity, predicate, value).

CATEGORÍAS ONTOLÓGICAS OBLIGATORIAS (claim_type):
1. "hecho": Hechos probados, eventos temporales, estados objetivos, importes o pagos ejecutados, relaciones societarias o cargos (ej. entity="Filial Sur S.A.", canonical_entity="Filial_Sur", predicate="administrador", value="D. Juan Pérez García").
2. "petitum": Pretensiones de las partes, súplicas, cuantías reclamadas, penas solicitadas o indemnizaciones pedidas (ej. entity="Demanda", predicate="petitum", canonical_predicate="amount", value="142.000 €", canonical_value=142000.0, unit="EUR").
3. "fundamento": Normas jurídicas, artículos legales, cláusulas contractuales o plazos pactados (ej. entity="ACME", predicate="payment_days", value="treinta días", canonical_value="30 days", unit="DAYS").
4. "prueba": Medios de prueba acreditados (informes periciales, documentos notariales, testificales ratificadas).

REGLAS ESTRICTAS:
- Asigna a cada hecho un identificador único ("c1", "c2", ...), su página ("page") y párrafo ("paragraph_id", ej. "p1", "p2").
- Incluye en "quote" la cita literal exacta del texto (conservando menciones a trimestres Q1-Q4, números de factura, fechas o si es una alegación de parte vs. Hecho Probado).
- En "canonical_entity", normaliza el identificador canónico de la entidad resolviendo pronombres, cargos o variantes societarias ("D. Juan Pérez García", "El Sr. Pérez" -> "Juan_Perez").
- En "canonical_predicate", mapea sinónimos al predicado canónico ("honorarios_devengados", "retribucion_profesional" -> "amount").
- En "canonical_value", incluye la normalización canónica universal del valor ("value") en CUALQUIER idioma soportado por el LLM (números escritos en letra o importes -> float/int puro como 142000.0; plazos o duraciones en cualquier idioma -> "30 days"; fechas -> ISO-8601 "YYYY-MM-DD").
- En "concept_fingerprint", asigna una huella semántica corta del concepto o partida ("invoice:A-01:Q1" vs "contract_total") y en "unit" la moneda o unidad ("EUR", "USD", "DAYS").
- En "speaker_role", clasifica el origen discursivo según la sección del documento: "COURT_FINDING" (Hecho Probado/Fallo), "PARTY_ALLEGATION" (alegación de parte no ratificada), "WITNESS_CLAIM" (testigo no corroborado), "CONTRACT_CLAUSE" o "AUTHORITATIVE_FACT".
- NO fusiones en un solo ítem importes de facturas o periodos distintos (ej. Q1, Q2, Q3).
- Ignora cabeceras, pies de página, números de folio o ruido de maquetación.

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
      "canonical_value": 142000.0,
      "concept_fingerprint": "contract_total",
      "unit": "EUR",
      "speaker_role": "COURT_FINDING | PARTY_ALLEGATION | WITNESS_CLAIM | CONTRACT_CLAUSE | AUTHORITATIVE_FACT",
      "claim_type": "hecho | petitum | fundamento | prueba",
      "quote": "cita textual exacta del documento",
      "page": 1,
      "paragraph_id": "p1",
      "origin_tier": "PRIMARY_DOCUMENT"
    }
  ],
  "question": "pregunta extraída si existe en el texto"
}
```

### Prompt 2: Motor de Inferencia con Vinculación Formal de Premisas (Auditado por `EpistemicJudge`)
```text
Eres un Motor de Inferencia Formal.
Se te darán las Unidades de Evidencia verificadas (con sus IDs "c1", "c2", ...) y una Pregunta.
Si la respuesta requiere conectar hechos explícitos, propón una conclusión estructurada indicando OBLIGATORIAMENTE en "premises" la lista de IDs de los hechos base que la sustentan.

REGLA DE AUDITORÍA EXTERNA:
- Tú NO decides si la inferencia es aceptada ni su confianza final; el Juez Epistémico determinista (`EpistemicJudge`) verificará tus `premises` y auditará el lenguaje.
- Si una premisa es una mera alegación de parte ("la defensa alega...") no ratificada como Hecho Probado, o si no existen premisas verificadas que impliquen deductivamente la conclusión, la inferencia será degradada y bloqueada.

Devuelve EXCLUSIVAMENTE un JSON con esta estructura:
{
  "id": "inf_1",
  "entity": "Entidad_ Sujeto",
  "predicate": "relacion_deducida",
  "value": "valor_deducido",
  "inferred_fact": "Enunciado completo de la conclusión",
  "inference_type": "deductive | arithmetic | syntactic | semantic | spatial | common_sense | causal | inductive | multi_hop | probabilistic | abductive | heuristic | narrative",
  "premises": ["c1", "c2"]
}
```

---

## Código de Referencia

Dentro de la carpeta `examples/` de esta skill encontrarás `pipeline_completo.py`. Ese script ejecuta de extremo a extremo la arquitectura v2.0 conectando la extracción estructurada, el `ClaimConsolidator`, el `EpistemicJudge` con verificación de premisas y clausura epistémica, el `DependencyGraph` con Norma T de Gödel, el `AggregationEngine` determinista y la generación final con citas verificadas al 100%.
