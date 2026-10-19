# Skill Deltoryx — Evidence Intelligence v2.0 (paquete de evaluación)

Material confidencial. Ver `AVISO_LEGAL.txt` antes de usar.

## 1. Contenido

```
evidence-intelligence/
├── SKILL.md                      Instrucciones v2.0, clausura epistémica y prompts estructurados
├── examples/
│   └── pipeline_completo.py      Pipeline de 5 fases de extremo a extremo (con modo demo determinista)
├── AVISO_LEGAL.txt               Titularidad, confidencialidad y alcance de la licencia
└── README_INSTALACION.md         Este archivo
```

## 2. Instalar la skill en tu agente

Copia la carpeta `evidence-intelligence` completa (sin renombrarla) en el directorio
de skills de tu agente:

- **Gemini CLI / Antigravity:** `~/.gemini/config/skills/`
- **Claude Code / Cowork:** `~/.claude/skills/`

Reinicia el agente. La skill se activa al pedir una implementación de Evidence
Intelligence: el propio `SKILL.md` arranca con un checklist de configuración
(Quickstart por defecto, o 5 preguntas para personalizar motor LLM, embeddings,
persistencia y ontología del caso de uso).

## 3. Ejecutar el pipeline de referencia (v2.0)

Requisitos: Python 3.10 o superior.

### Ejecución determinista inmediata (sin API Key)
El script incluye una demostración determinista completa de los módulos v2.0 (`ClaimConsolidator`, `EpistemicJudge`, `OriginTier`, `DependencyGraph` con Norma T de Gödel y `AggregationEngine` con desambiguación de pagos periódicos):

```bash
python examples/pipeline_completo.py --demo
```

### Ejecución completa con extracción e inferencia LLM
```bash
pip install openai
export OPENAI_API_KEY="tu-clave"       # nunca la escribas en el código
python examples/pipeline_completo.py
```

### Comprobación rápida de `ClaimLayer` v2.0

```python
from claimlayer import ClaimLayer
cl = ClaimLayer()
cl.ingest([
    "ACME payment terms are 30 days",
    "ACME payment terms are thirty days",
    "ACME payment terms are 45 days",
])
print(cl.ask("What are the payment terms for ACME?"))
```

Unifica `"30 days"` y `"thirty days"` (y cualquier idioma soportado por el LLM mediante `canonical_value` en extracción estructurada o `ClaimLayer(normalizer_fn=LLMValueNormalizer(api_key=...))` en texto plano, ej. francés `"trente jours"`, alemán `"dreißig Tage"`, portugués `"trinta dias"`, o importes complejos en letra como `"ciento cuarenta y dos mil euros"`) bajo el mismo valor canónico (`30` / `142000.0`), acumula su confianza mediante Noisy-OR con **0 ms de latencia en tiempo de consulta**, marca `"45 days"` como contradicción penalizada con explicación auditable y devuelve las citas formateadas (`[input_0.txt, Pág. 1, Párrafo p1]`) junto con la descomposición formal $\kappa = (\kappa_{\text{extraction}}, \kappa_{\text{structuring}})$.

> **Licencia de ClaimLayer:** Business Source License 1.1. El uso de evaluación y no
> productivo es libre; cualquier uso en producción —incluido el uso interno para operaciones
> reales de negocio— requiere licencia comercial expresa, y queda prohibido construir
> productos competidores en Evidence Intelligence, verificación de IA o auditoría de RAG.
> Convierte a MPL 2.0 el 31/03/2030. Consulta el `LICENSE` del repositorio.

## 4. Qué valida la arquitectura v2.0

1. **Extracción ontológica tipada, semántica universal asistida por LLM (`canonical_value`, `canonical_entity`, `canonical_predicate`, `concept_fingerprint`, `unit`, `speaker_role`) y consolidación contextual (`ClaimConsolidator`):** Descomposición bajo las categorías `hecho`, `petitum`, `fundamento` y `prueba`, normalizando cifras en letra, duraciones e importes en cualquier idioma soportado por el LLM, resolviendo correferencias de entidades y sinónimos de predicados durante la ingesta (con registro determinista en caché para resolución a 0 ms), podando ruido de maquetación y exigiendo identidad de coordenadas (`page`, `paragraph_id`) y compatibilidad cuantitativa/temporal antes de fusionar.
2. **Juez Epistémico Desacoplado (`EpistemicJudge`) y Clausura Monótona:** El LLM no se auto-aprueba. Toda inferencia requiere premisas verificadas (`premises: ["c1", "c2"]`), cumple $\text{Rank}(C) \le \min \text{Rank}(P)$ y bloquea alegaciones unilaterales de parte no ratificadas como Hecho Probado (tanto por marcadores léxicos como por atribución contextual `speaker_role="PARTY_ALLEGATION"`).
3. **Resolución de contradicciones con `OriginTier` y Noisy-OR acotado:** `PRIMARY_DOCUMENT (100) > SECONDARY_ANNEX (50) > EXTERNAL_INJECTED (10)`, evitando el colapso de confianza ante múltiples hechos extraídos.
4. **Razonamiento Multihop (Norma T de Gödel con Correferencia), Aislamiento de Unidades y Router Semántico (`AggregationEngine` + `LLMQueryRouter`):** Resolución de cadenas de 2 y 3 saltos ($\min(s_i) \times 0.95^{k-1}$) unificando alias de entidades, enrutamiento híbrido de consultas (`LLMQueryRouter` + regex rápidas) y cálculos exactos (`SUM`, `COUNT`, `LIST`, `AVG`, `MIN`, `MAX`) que operan sobre `canonical_value`, aíslan monedas/unidades incompatibles (`EUR` vs `USD` vs `DAYS`), colapsan menciones repetidas entre páginas y preservan facturas periódicas simétricas (`Q1`, `Q2`, `Q3`) vía `concept_fingerprint`.
5. **Trazabilidad y cobertura de citas al 100%:** Todas las salidas incluyen `citations` estructuradas y `formatted_citations` listas para auditoría.

## 5. Contacto

Francisco Hernández de Blas — francisco@deltoryx.com
