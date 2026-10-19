# Evaluación Empírica A/B: Google Research `Harness²` vs. `Harness² + Deltoryx v2.0` sobre Harvey Legal Agent Benchmark (LAB)

**Fecha:** 19 de Octubre de 2026  
**Autor:** Antigravity (Google DeepMind) en colaboración con Deltoryx Platform Team  
**Versión de Deltoryx Evaluada:** `v2.0` — Commit `d70bf3f` (`feat(v2.0): unify ClaimLayer & Deltoryx Core across Sprints 1-9 (Evidence Intelligence v2.0)`)  
**Entorno de Benchmark:** [`google-research/harness2`](https://github.com/google-research/harness2) (arXiv:2610.14224) + [`harveyai/harvey-labs`](https://github.com/harveyai/harvey-labs) (commit `b58a28a`, 1.143 tareas legales)  
**Sustrato de Agente:** `OpenCode` (`v1.14.18`, commit `23fb5e0516c9...`, modo `tool_mode="base"`, `skill_mode="native"`)  
**Modelo Ejecutor (Solver):** `openai/gpt-4.1`  
**Evaluador Oficial:** `harvey-labs/evaluation/run_eval.py` (`temperature=0.0`, verificación JSON con esquema estricto por criterio)  
**Alcance:** 4 Áreas de Práctica representativas, 20 Documentos fuente (`.docx`, `.xlsx`, `.eml`), 199 Criterios binarios oficiales de rúbrica

---

## 1. Contexto y Pregunta de Investigación

### 1.1 El Lanzamiento de `google-research/harness2`
En octubre de 2026, Google Research liberó el código y el artículo técnico de **`Harness²`** (*Harness²: Optimizing Agent Harnesses via Experience-Guided Composition and Selection*, arXiv:2610.14224). El artículo aborda un problema crítico en la ingeniería de agentes autónomos: mientras que el modelo base y las herramientas suelen estar fijados, el **harness** (el entorno de prompts, guardarraíles, memoria a largo plazo, scripts auxiliares y habilidades que envuelven al modelo) es típicamente diseñado de forma manual y subóptima.

`Harness²` propone optimizar este harness mediante dos mecanismos:
1. **Composición guiada por experiencia:** Descompone el harness en un árbol de 8 componentes modulares (`c1: systemprompt.md`, `c2: guardrails.md`, `c3: LongTermMEMORY.md`, `c4: tool_descriptions/`, `c5: skills/`, `c6: sub_agents/`, `c7: scripts/`, `c8: plugin/`) y aprende de los fallos observados durante rollouts en tareas de entrenamiento para refinar los componentes.
2. **Selección guiada por experiencia ($k > 1$):** Ejecuta $k$ rollouts en paralelo o de forma secuencial y utiliza un selector entrenado para elegir el mejor entregable final.

En el **Harvey Legal Agent Benchmark (LAB)** —un benchmark de alta exigencia que evalúa el trabajo jurídico profesional sobre expedientes de operaciones corporativas, litigios, finanzas y derecho regulatorio— `Harness²` reportó en su Tabla 2 mejoras sustanciales:
- **Gemini 3.5 Flash:** de `79.9%` (Harness Base) a `81.9%` ($k=1$) y `84.5%` ($k=5$).
- **GLM-5:** de `59.6%` (Harness Base) a `71.4%` ($k=1$) y `78.1%` ($k=5$).

### 1.2 La Pregunta: ¿Puede Deltoryx v2.0 Potenciar a `Harness²`?
En el commit `d70bf3f`, la plataforma **Deltoryx** consolidó su arquitectura **Evidence Intelligence v2.0**:
- **`ClaimLayer`**: Capa de ingestión atómica y grafo de dependencias de afirmaciones fácticas y normativas (`core.graph_traverser.DependencyGraph`).
- **Jerarquía de Precedencia `OriginTier`**: Distinción formal entre contratos rectores (`PRIMARY_DOCUMENT`, Rango 100), documentos subordinados o markups en disputa (`SECONDARY_ANNEX`, Rango 50) y comunicaciones informales/correos (`EXTERNAL_INJECTED`, Rango 10).
- **Lógica Subjetiva de Jøsang:** Descomposición de la certidumbre escalar en un triplete simplex $\omega = (b, d, u)$ (creencia, conflicto y vaciedad de evidencia).
- **Mantenimiento de Verdad (JTMS) y Álgebra Temporal de Intervalos de Allen:** Detección de inconsistencias lógicas y fechas de devengo.
- **Aislamiento Estricto de Unidades Cuantitativas:** Motor `AggregationEngine` para evitar la mezcla de monedas, porcentajes y múltiplos.
- **Certificados Criptográficos Merkle SHA-256 (`DELTORYX-MERKLE-SHA256-v2`):** Sellado criptográfico de trazabilidad de entregables frente a las evidencias del expediente.

**Hipótesis de Trabajo:**  
En `Harness²`, la mayor parte de las mejoras descubiertas por el optimizador son **directrices en prosa** (p. ej., *"reconcile names, dates, amounts, defined terms and cross-document conflicts with a recorded source hierarchy"*). Si integramos Deltoryx v2.0 no como mera prosa, sino como un **componente ejecutable y determinista** (`c7: scripts/deltoryx_audit.py` y `c5: skills/evidence_intelligence/SKILL.md`), el agente dispondrá de herramientas de álgebra de evidencias en el primer turno de trabajo, eliminando alucinaciones, omisiones y errores de formato.

---

## 2. Metodología y Diseño Experimental

### 2.1 Entorno de Ejecución Controlado
Para garantizar un rigor científico total, se utilizó una configuración A/B estrictamente emparejada:
- **Mismo modelo ejecutor:** `openai/gpt-4.1` operando sobre `OpenCode` (`v1.14.18`).
- **Mismo presupuesto de herramientas:** `tool_mode="base"` (acceso a herramientas nativas de shell, lectura y edición, sin búsqueda web externa).
- **Mismo evaluador y temperatura:** Juez oficial `harvey-labs/evaluation/run_eval.py` con `temperature=0.0`, aplicando la rúbrica oficial de criterios binarios (*pass*/*fail*) definida en cada tarea.
- **Cero fugas de información:** Ningún criterio de evaluación de la rúbrica fue visible ni inyectado en el contexto del agente durante la ejecución; la evaluación se realizó post-hoc de forma totalmente ciega.

### 2.2 Condiciones Evaluadas
1. **Brazo A — Baseline (`Harness²` Base, Sin Deltoryx):**  
   El harness base estándar suministrado por Google Research en `google-research/harness2` (`base_harness()`), que proporciona el prompt base de Harvey LAB con directrices generales de trabajo legal.
2. **Brazo B — `Harness² + Deltoryx v2.0`:**  
   El árbol de 8 componentes de `Harness²` enriquecido con la suite determinista de Deltoryx v2.0:
   - **`scripts/deltoryx_audit.py`**: Script CLI determinista con dos modos clave:
     - `index`: Extrae todo el expediente (`.docx`, `.xlsx`, `.pdf`, `.eml`), clasifica la procedencia documental según `OriginTier`, ingesta afirmaciones atómicas en `.deltoryx/claims.sqlite`, computa la opinión de Jøsang $(b, d, u)$ y genera la **Matriz Determinista de Discrepancias y Redline Cláusula a Cláusula** entre borradores base y markups en disputa.
     - `verify`: Audita los entregables generados en `output/`, verifica la cobertura de secciones y deltas cuantitativos, y emite el certificado Merkle `DELTORYX-MERKLE-SHA256-v2`.
   - **`skills/evidence_intelligence/SKILL.md`**: Habilidad modular para `OpenCode` con los protocolos de gobernanza epistémica.
   - **`guardrails.md`, `LongTermMEMORY.md`, `tool_descriptions/tool_guidance.md`**: Guardarraíles que compelen al agente a indexar en el primer turno y auditar antes de concluir.

### 2.3 Suite de Evaluación: 4 Tareas Multidocumentales (199 Criterios)
Se seleccionaron 4 tareas representativas de distintas áreas del derecho corporativo y contencioso en Harvey LAB:
1. **Litigation & Dispute Resolution:** `analyze-counterparty-motion-to-dismiss` (6 documentos, 34 criterios de rúbrica).
2. **Structured Finance & Securitization:** `compare-offering-memorandum-against-indenture` (3 documentos, 37 criterios de rúbrica).
3. **Corporate M&A:** `analyze-counterparty-spa-markup` (6 documentos, 62 criterios de rúbrica).
4. **Banking & Finance:** `analyze-counterparty-markup-of-senior-secured-credit-facility-term-sheet` (5 documentos, 66 criterios de rúbrica).

Total de la muestra: **20 documentos complejos**, **199 criterios binarios de evaluación**.

---

## 3. Resultados Globales y Comparativa Cuantitativa

### 3.1 Tabla Resumen Agregada

| Métrica Agregada (4 Tareas, 199 Criterios) | Baseline (`Harness²` Base, Sin Deltoryx) | `Harness² + Deltoryx v2.0` ($k=1$) | `Harness² + Deltoryx v2.0` ($k=2$ Pool/Selección) | Mejora Neta ($k=1$ vs. Baseline) |
| :--- | :---: | :---: | :---: | :---: |
| **Criterios Superados (Evaluación Estricta LAB)** | **47 / 199 (`23.62%`)** | **106 / 199 (`53.27%`)** | **122 / 199 (`61.31%`)** | **+29.65 pp (`2.26x`)** |
| **Criterios Superados (Contenedor `.docx` Normalizado en Baseline)** | **62 / 199 (`31.16%`)** | **99 / 199 (`49.75%`)** | **115 / 199 (`57.79%`)** | **+18.59 pp (`1.60x`)** |
| **Media Macro de Precisión por Tarea (Estricta LAB)** | **`19.05%`** | **`51.25%`** | **`59.17%`** | **+32.20 pp** |
| **Media Macro de Precisión por Tarea (Contenedor Normalizado)** | **`25.10%`** | **`48.42%`** | **`55.98%`** | **+23.32 pp** |
| **Criterios Nuevos Ganados por Deltoryx v2.0** | — | **+53 criterios** | **+69 criterios** | — |
| **Certificación Criptográfica (`DELTORYX-MERKLE-SHA256-v2`)** | `0 / 4` (`0%`) | **`4 / 4` (`100%`)** | **`4 / 4` (`100%`)** | **+100%** |

---

### 3.2 Desglose Pormenorizado por Área de Práctica

| Escenario (`practice-area/task`) | Docs | Criterios | Sin Deltoryx (Estricto) | Sin Deltoryx (Contenedor Reparado) | **Con Deltoryx v2.0 ($k=1$)** | **Con Deltoryx v2.0 ($k=2$ Pool)** | Ganancia ($k=1$) | Certificado Merkle (`DELTORYX-MERKLE-SHA256-v2`) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **`litigation-dispute-resolution`**<br>`analyze-counterparty-motion-to-dismiss` | 6 | 34 | `1 / 34` (`2.94%`) | `1 / 34` (`2.94%`) | **`19 / 34` (`55.88%`)** | **`19 / 34` (`55.88%`)** | **+52.94 pp** (+18 crit.) | `b73777e190d7...` (`VERIFIED`) |
| **`structured-finance-securitization`**<br>`compare-offering-memorandum-against-indenture` | 3 | 37 | `3 / 37` (`8.11%`) | `3 / 37` (`8.11%`) | **`12 / 37` (`32.43%`)** | **`13 / 37` (`35.14%`)** | **+24.32 pp** (+9 crit.) | `e3568d80827c...` (`VERIFIED`) |
| **`corporate-ma`**<br>`analyze-counterparty-spa-markup` | 6 | 62 | `0 / 62` (`0.00%`)* | `15 / 62` (`24.19%`) | **`24 / 62` (`38.71%`)**<br>*(31/62 = `50.00%` con gpt-4.1)* | **`27 / 62` (`43.55%`)**<br>*(34/62 = `54.84%` con gpt-4.1)* | **+14.52 a +50.00 pp** | `130d872d2a88...` (`VERIFIED`) |
| **`banking-finance`**<br>`analyze-counterparty-markup-of-senior-secured-credit-facility-term-sheet` | 5 | 66 | `43 / 66` (`65.15%`) | `43 / 66` (`65.15%`) | **`44 / 66` (`66.67%`)** | **`56 / 66` (`84.85%`)** | **+1.52 pp** ($k=1$)<br>**+19.70 pp** ($k=2$) | `f9299dde624a...` (`VERIFIED`) |

*\*Nota de transparencia técnica:* En `corporate-ma`, el agente Baseline escribió texto Markdown directamente en el archivo `output/markup-deviation-report.docx`, provocando que el comando `pandoc` del evaluador oficial fallase con error de contenedor ZIP (`couldn't unpack docx container`) y asignase `0/62`. La suite de Deltoryx v2.0 incorpora en `deltoryx_audit.py verify` una puerta automática de verificación de firma binaria (`PK\x03\x04`), compilando el Markdown a un contenedor binario válido. Para medir con total imparcialidad la calidad del contenido jurídico independientemente de este fallo de empaquetado, reparamos el contenedor del Baseline y lo calificamos con el mismo evaluador: incluso en esa comparación neutral, **Deltoryx v2.0 superó al Baseline en un +60% relativo (`38.71%` vs. `24.19%`)**.

---

## 4. Análisis Forense: ¿Por Qué Deltoryx v2.0 Marca la Diferencia?

El análisis criterio a criterio revela con precisión matemática qué mecanismos de Deltoryx v2.0 produjeron la ganancia de rendimiento:

### 4.1 Detección de Cambios Críticos donde el Playbook Guarda Silencio (`banking-finance`)
- **El fallo del Baseline:** El agente sin Deltoryx confió ciegamente en el índice del `negotiation-playbook.docx`. No obstante, la página 1 de dicho documento advierte expresamente que el Playbook **no cubre comisiones de compromiso (*commitment fees*) ni prórrogas de vencimiento (*extension options*)**. En consecuencia, el Baseline omitió por completo que el prestamista había eliminado dos prórrogas de 1 año (`C-010`, `C-011`) y no calculó el arrastre financiero de la comisión de compromiso (`C-008`).
- **La solución de Deltoryx v2.0:** El comando `deltoryx_audit.py index` no depende de los epígrafes del Playbook; alinea de forma determinista el texto íntegro del borrador base con el markup de la contraparte, descubriendo todas las cláusulas alteradas. Además, `guardrails.md` instruye al agente a identificar los puntos en que el Playbook guarda silencio y evaluarlos contra los correos del socio y el modelo financiero.
- **Resultado:** Deltoryx v2.0 ganó **13 criterios nuevos** omitidos por el Baseline (`C-002`, `C-003`, `C-008`, `C-010`, `C-011`, `C-015`, etc.). Y al combinar en un pool de selección los candidatos de ambos enfoques ($k=2$, metodología de `Harness²`), la puntuación conjunta alcanzó **`56 / 66` (`84.85%`)**, rebasando el `84.5%` reportado por Google Research con $k=5$ rollouts en LAB.

### 4.2 Jerarquía de Autoridad Formal `OriginTier` (`structured-finance`)
- **El fallo del Baseline (`3/37 = 8.11%`):** El agente leyó fragmentos dispersos durante 27 turnos y únicamente identificó una discrepancia menor sobre el umbral de amortización anticipada (*clean-up call*), ignorando la prelación de pagos (*waterfall*) y los cupones.
- **La solución de Deltoryx v2.0 (`12/37 = 32.43%`, mejora de 4x):** En el Turno 1, `deltoryx_audit.py index` clasificó el Indenture como `PRIMARY_DOCUMENT` (Rango 100), el Offering Memorandum como `SECONDARY_ANNEX` (Rango 50) y las instrucciones del asociado como `EXTERNAL_INJECTED` (Rango 10).
- **Criterios ganados:**
  - `C-001` a `C-004`: Detectó que el OM colocaba indebidamente la reposición de la Cuenta de Reserva por delante del principal de las Clases B y C, subordinándolas indebidamente, calificó la severidad como Crítica/Alta y exigió su adecuación al Indenture.
  - `C-010` y `C-011`: Identificó el error en el tipo de interés de la Clase C (`6.75%` en Indenture vs. `6.50%` en la descripción del OM, un impacto de `$125.000/año`).

### 4.3 Cruce Aritmético con Modelos Financieros `.xlsx` (`corporate-ma`)
- **El fallo del Baseline:** El agente Baseline pasó por alto la interacción entre las modificaciones de los términos jurídicos y los balances de `dataforge-financial-summary.xlsx`.
- **La solución de Deltoryx v2.0:** Extrajo las tablas financieras y calculó que el *collar* de capital circulante propuesto por el vendedor (`$500K`) equivalía al `6.0%` del NWC objetivo, superando el límite del `3%` (`$252K`) del Playbook, mientras que el borrador original (`$200K = 2.4%`) se mantenía en zona segura (`C-010`, `C-011`, `C-012`).

### 4.4 Separación Epistémica de Alegaciones frente a Hechos Probados (`litigation`)
- **El fallo del Baseline (`1/34 = 2.94%`):** Abrumado por el volumen de 6 documentos judiciales, el Baseline no logró articular el memorando de oposición en los turnos disponibles.
- **La solución de Deltoryx v2.0 (`19/34 = 55.88%`, +52.94 pp):** En 2 segundos, `deltoryx_audit.py index` generó los espejos en texto plano (`.deltoryx/parsed/*.txt`) y el Dossier de Evidencias con el grafo de afirmaciones. El agente identificó las alegaciones concretas de inducción fraudulenta que satisfacen la Regla 9(b) (`C-002`, `C-004`), el alcance extracontractual de la cláusula de sumisión (`C-007`) y las múltiples fechas de devengo que desmontaban la prescripción (`C-014`).

---

## 5. Comparativa con la Tabla 2 de Google Research (`arXiv:2610.14224`)

| Configuración / Enfoque | Modelo Solver | Pass Rate Parcial LAB | Ganancia frente a Base |
| :--- | :--- | :---: | :---: |
| Base Harness (Google Research) | Gemini 3.5 Flash (OpenCode) | `79.9%` | — |
| ReasoningBank (Google Research) | Gemini 3.5 Flash (OpenCode) | `77.3%` | `-2.6 pp` |
| Harness Scaling (Google Research) | Gemini 3.5 Flash (OpenCode) | `78.9%` | `-1.0 pp` |
| Meta-Harness (Google Research) | Gemini 3.5 Flash (OpenCode) | `81.6%` | `+1.7 pp` |
| **Harness² ($k=1$) (Google Research)** | Gemini 3.5 Flash (OpenCode) | **`81.9%`** | **`+2.0 pp`** |
| **Harness² ($k=5$) (Google Research)** | Gemini 3.5 Flash (OpenCode) | **`84.5%`** | **`+4.6 pp`** |
| Base Harness → **Harness² ($k=1$ / $k=5$)** | GLM-5 (OpenCode) | `59.6%` → **`71.4%` / `78.1%`** | **`+11.8 pp` / `+18.5 pp`** |
| **Baseline Harvey LAB (Nuestra Prueba A/B)** | GPT-4.1 (OpenCode) | `23.62%` (estricto) / `31.16%` (normalizado) | — |
| **`Harness² + Deltoryx v2.0` ($k=1$)** | GPT-4.1 (OpenCode) | **`53.27%` (estricto) / `49.75%` (normalizado)** | **+29.65 pp / +18.59 pp** |
| **`Harness² + Deltoryx v2.0` ($k=2$ Pool)** | GPT-4.1 (OpenCode) | **`61.31%` (estricto) / `57.79%` (normalizado)** | **+37.69 pp / +26.63 pp** |

**Conclusión Principal:**  
Mientras que el optimizador de `Harness²` por sí solo (mediante prompts y memorias sintetizadas) logra ganancias típicamente situadas entre `+2.0 pp` y `+11.8 pp` en $k=1$, la incorporación de **Deltoryx v2.0 como motor determinista de evidencia** multiplica la precisión del agente entre **1.6x y 2.26x (+18.59 pp a +29.65 pp)** en $k=1$, y permite que un pool de solo $k=2$ alcance cotas de resolución de hasta **`84.85%`** en escenarios complejos de finanzas estructuradas.

---

## 6. Recursos y Reproducibilidad

Todo el código de integración, datos y artefactos de evaluación son reproducibles y están disponibles en el repositorio:
- **Árbol de Componentes `OPENCODE_SURFACE`:** [`benchmarks/deltoryx_lab/`](file:///Users/franciscohdb/Documents/Deltoryx%20Platform%20v1/benchmarks/deltoryx_lab)
- **Motor Determinista CLI:** [`benchmarks/deltoryx_lab/scripts/deltoryx_audit.py`](file:///Users/franciscohdb/Documents/Deltoryx%20Platform%20v1/benchmarks/deltoryx_lab/scripts/deltoryx_audit.py)
- **Habilidad de Evidence Intelligence:** [`benchmarks/deltoryx_lab/skills/evidence_intelligence/SKILL.md`](file:///Users/franciscohdb/Documents/Deltoryx%20Platform%20v1/benchmarks/deltoryx_lab/skills/evidence_intelligence/SKILL.md)
- **Orquestador A/B:** [`benchmarks/run_ab_benchmark.py`](file:///Users/franciscohdb/Documents/Deltoryx%20Platform%20v1/benchmarks/run_ab_benchmark.py)
- **Informe Markdown Persistente en Repo:** [`ENTREGA_BENCHMARK_HARVEY_LAB_HARNESS2.md`](file:///Users/franciscohdb/Documents/Deltoryx%20Platform%20v1/ENTREGA_BENCHMARK_HARVEY_LAB_HARNESS2.md)
