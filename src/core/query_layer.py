from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QueryCandidate:
    entity: str
    predicate: str
    score: float        # 0.0–1.0; higher = stronger signal this predicate was intended


# ---------------------------------------------------------------------------
# Predicate rules
# Each tuple: (keyword_set, predicate, score)
# A predicate's final score = max score across all matching rules.
# ---------------------------------------------------------------------------

PREDICATE_RULES: List[tuple] = [
    # payment_days — strong signals
    ({"payment", "days", "plazo", "pago", "pay", "pagos", "vencimiento", "abono"},   "payment_days",  1.0),
    # payment_days — related/conversational signals
    ({"long", "take", "how", "tiempo"},              "payment_days",  0.7),
    # payment_terms — strong signals
    ({"terms", "payment_terms", "condiciones"},      "payment_terms", 0.8),
    # payment_terms — weak/shared signals
    ({"pay", "payment", "agreement", "contract"},    "payment_terms", 0.5),
    # amount / facturas / invoices / perjuicio patrimonial / daño / cuantía / deuda / quebranto / pasivo / honorarios
    ({"amount", "monto", "montante", "cuantia", "cuantía", "importe", "invoices", "facturas", "factura",
      "precio", "perjuicio", "patrimonial", "patrimonio", "daño", "daños", "deuda", "deudas",
      "quebranto", "pasivo", "concursal", "contingente", "indemnización", "indemnizacion",
      "honorarios", "retribución", "retribucion", "devengado", "devengados", "salario",
      "saldo", "partidas", "partida", "fondos", "dinero", "cobro", "montant", "somme", "betrag"}, "amount", 1.0),
    # crimes / delitos
    ({"delito", "delitos", "crimen", "cargos", "imputaciones", "condena", "pena", "acusación", "imputación", "ilícito", "ilicito"}, "delito", 1.0),
    # contracts / contratos
    ({"contrato", "contratos", "contracts", "acuerdo", "convenio", "escritura"}, "contract", 1.0),
    # legal petitum / fundamento / prueba / administrador / filial
    ({"petitum", "suplico", "súplica", "pretensión", "pretension", "solicita", "reclama"}, "petitum", 0.95),
    ({"fundamento", "fundamentos", "jurídico", "juridico", "artículo", "articulo", "norma", "ley"}, "fundamento", 0.90),
    ({"prueba", "pruebas", "pericial", "perito", "testigo", "testifical", "documental"}, "prueba", 0.90),
    ({"administrador", "director", "representante", "apoderado", "gerente", "ceo"}, "administrador", 0.95),
    ({"filial", "subsidiaria", "matriz", "sociedad", "empresa", "compañía"}, "filial", 0.90),
    # Clinical / Medical / Pharma
    ({"dosis", "dosage", "dose", "posología", "posologia", "pauta", "miligramos", "mg"}, "dosage", 0.95),
    ({"diagnóstico", "diagnostico", "diagnosis", "patología", "patologia", "enfermedad"}, "diagnosis", 0.95),
    ({"tratamiento", "treatment", "terapia", "fármaco", "farmaco", "medicamento", "medication"}, "treatment", 0.90),
    ({"tensión", "tension", "presión", "presion", "frecuencia", "glucosa", "saturación", "biomarcador"}, "vital_sign", 0.90),
    # Financial / Corporate / M&A
    ({"ebitda", "beneficio", "margen", "margin", "ingresos", "revenue", "facturación", "facturacion"}, "financial_metric", 0.95),
    ({"covenant", "ratio", "apalancamiento", "leverage", "liquidez", "solvencia"}, "covenant", 0.90),
    # Engineering / Industrial / Cybersecurity
    ({"latencia", "latency", "sla", "disponibilidad", "uptime", "rendimiento", "throughput", "capacidad"}, "sla_metric", 0.95),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ENTITY_STOP_WORDS = {
    "qué", "que", "cuál", "cual", "cuáles", "cuales", "cuánto", "cuanto",
    "cuánta", "cuanta", "cuántos", "cuantos", "cuántas", "cuantas",
    "cómo", "como", "dónde", "donde", "quién", "quien", "quiénes", "quienes",
    "cuándo", "cuando", "por", "para", "con", "sin",
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
    "a", "al", "en", "es", "son", "fue", "fueron", "se", "su", "sus",
    "desglose", "desglosar", "detalle", "detallar", "enumere", "enumerar",
    "indique", "indicar", "explique", "explicar", "señale", "señalar",
    "mencione", "mencionar", "calcule", "calcular", "determine", "determinar",
    "cuantifique", "cuantificar", "relacione", "relacionar", "liste", "listar",
    "según", "segun", "respecto", "conforme", "existe", "existen", "hay", "hubo",
    "suma", "total", "importe", "cuantía", "cuantia", "perjuicio", "partidas",
    "quebranto", "pasivo", "montante", "honorarios", "dosis", "diagnóstico",
    "diagnostico", "pauta", "actual", "vigente",
    "what", "which", "how", "why", "who", "where", "when", "the",
    "is", "are", "was", "were", "to", "of", "in", "for", "on", "with", "list",
}

def _extract_entity(text: str, known_entities: Optional[List[str]] = None) -> Optional[str]:
    """
    Return a matching entity from *known_entities* if present in *text*,
    otherwise the first all-caps token (≥2 chars) from *text*,
    or fall back to the first capitalized named entity token (not in stop words).
    """
    if known_entities:
        text_low = re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]+", " ", text.lower()).strip()
        # Sort by length DESC so multi-word entities ('Paciente Juan', 'Filial Sur') match first
        for ke in sorted(set(known_entities), key=lambda s: len(str(s)), reverse=True):
            if not ke:
                continue
            ke_norm = re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]+", " ", str(ke).lower()).strip()
            if ke_norm and len(ke_norm) >= 2 and re.search(rf"\b{re.escape(ke_norm)}\b", text_low):
                return ke

    matches = [m for m in re.findall(r'\b[A-Z][A-Z0-9_]+\b', text) if m.lower() not in _ENTITY_STOP_WORDS]
    if matches:
        return matches[0]

    cap_words = re.findall(r'\b[A-ZÁÉÍÓÚÑ][a-záéíóúñA-Z0-9_-]+\b', text)
    filtered = [w for w in cap_words if w.lower() not in _ENTITY_STOP_WORDS]
    return filtered[0] if filtered else None


def _extract_candidates(
    tokens: set,
    entity: str,
    raw_text: str = "",
    known_predicates: Optional[List[str]] = None,
) -> List[QueryCandidate]:
    """
    Score every predicate against *tokens* (plus dynamically discovered *known_predicates*
    from the ledger for Zero-Config cross-domain readiness), deduplicate by keeping the
    maximum score per predicate, and return all matches sorted score DESC.
    """
    best: dict[str, float] = {}

    # 1. Static cross-domain rules
    for keywords, predicate, score in PREDICATE_RULES:
        if tokens & keywords:
            if score > best.get(predicate, 0.0):
                best[predicate] = score

    # 2. Dynamic Zero-Config Ledger Schema Auto-Discovery
    if known_predicates:
        expanded_tokens = set(tokens)
        for t in list(tokens):
            expanded_tokens.update(p for p in t.split("_") if len(p) >= 3)
        raw_norm = re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]+", " ", raw_text.lower()).strip()
        for kp in set(known_predicates):
            if not kp:
                continue
            kp_str = str(kp).strip()
            kp_low = kp_str.lower()
            kp_space = re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]+", " ", kp_low).strip()
            # Full exact match of the ledger predicate in the query
            if kp_low in tokens or (kp_space and re.search(rf"\b{re.escape(kp_space)}\b", raw_norm)):
                best[kp_str] = max(best.get(kp_str, 0.0), 1.0)
                continue
            # Partial token overlap only if no static/exact predicate matched yet
            if not best:
                kp_parts = [p for p in re.split(r"[_\s\-]+", kp_low) if len(p) >= 3 and p not in _ENTITY_STOP_WORDS]
                if kp_parts:
                    overlap = sum(1 for p in kp_parts if p in expanded_tokens)
                    if overlap > 0:
                        score = round(0.85 + 0.15 * (overlap / len(kp_parts)), 4)
                        if score > best.get(kp_str, 0.0):
                            best[kp_str] = score

    return sorted(
        [QueryCandidate(entity=entity, predicate=p, score=s) for p, s in best.items()],
        key=lambda c: c.score,
        reverse=True,
    )


class LLMQueryRouter:
    """
    LLM-backed semantic query router with deterministic in-memory caching.
    Translates any natural-language query in any language into structured
    `{entity, predicate, aggregation_op}` aligned with the ledger's schema.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        llm_callable=None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._llm_callable = llm_callable
        self._cache: dict[str, dict] = {}

    @property
    def cache(self) -> dict[str, dict]:
        return self._cache

    def __call__(
        self,
        query: str,
        available_entities: Optional[List[str]] = None,
        available_predicates: Optional[List[str]] = None,
    ) -> dict:
        key = query.strip().lower()
        if key in self._cache:
            return self._cache[key]

        result: dict = {}
        if self._llm_callable is not None:
            try:
                result = self._llm_callable(
                    query,
                    available_entities=available_entities,
                    available_predicates=available_predicates,
                )
            except TypeError:
                result = self._llm_callable(query)
        elif self._api_key:
            import json
            from openai import OpenAI

            client = OpenAI(api_key=self._api_key)
            ent_hint = f"Known entities in ledger: {available_entities}\n" if available_entities else ""
            pred_hint = f"Known predicates in ledger: {available_predicates}\n" if available_predicates else ""
            resp = client.chat.completions.create(
                model=self._model,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a deterministic semantic query router for an Evidence Intelligence ledger.\n"
                            f"{ent_hint}{pred_hint}"
                            "Given a user query in ANY language and ANY domain (legal, clinical, financial, engineering), identify:\n"
                            '- "entity": target entity name (aligned with known entities if applicable, or null)\n'
                            '- "predicate": target attribute/relation name (aligned with known predicates in the ledger)\n'
                            '- "aggregation_op": one of "sum", "count", "list", "average", "min", "max", or null.\n'
                            'Return ONLY JSON: {"entity": str|null, "predicate": str|null, "aggregation_op": str|null}'
                        ),
                    },
                    {"role": "user", "content": query},
                ],
            )
            result = json.loads(resp.choices[0].message.content)

        if not isinstance(result, dict):
            result = {}
        self._cache[key] = result
        return result


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class QueryLayer:
    def __init__(
        self,
        query_parser_fn=None,
        known_entities: Optional[List[str]] = None,
        known_predicates: Optional[List[str]] = None,
    ) -> None:
        self._query_parser_fn = query_parser_fn
        self._known_entities: List[str] = list(known_entities or [])
        self._known_predicates: List[str] = list(known_predicates or [])

    def register_schema(
        self,
        entities: Optional[List[str]] = None,
        predicates: Optional[List[str]] = None,
    ) -> None:
        """Dynamically register entities and predicates discovered in the ledger (Zero-Config)."""
        if entities:
            for e in entities:
                if e and e not in self._known_entities:
                    self._known_entities.append(e)
        if predicates:
            for p in predicates:
                if p and p not in self._known_predicates:
                    self._known_predicates.append(p)

    def parse(
        self,
        text: str,
        query_parser_fn=None,
        known_entities: Optional[List[str]] = None,
        known_predicates: Optional[List[str]] = None,
    ) -> List[QueryCandidate]:
        """
        Parse *text* into one or more QueryCandidate objects.

        Returns candidates sorted by score DESC; the first entry is the
        most likely intended predicate.

        Raises ValueError if entity or predicate cannot be extracted.
        """
        tokens = set(re.findall(r'\w+', text.lower()))
        parser_fn = query_parser_fn or self._query_parser_fn
        eff_entities = list(self._known_entities) + list(known_entities or [])
        eff_predicates = list(self._known_predicates) + list(known_predicates or [])

        entity = _extract_entity(text, known_entities=eff_entities if eff_entities else None)
        candidates = (
            _extract_candidates(tokens, entity, raw_text=text, known_predicates=eff_predicates if eff_predicates else None)
            if entity
            else []
        )

        if parser_fn is not None and (entity is None or not candidates):
            try:
                try:
                    parsed = parser_fn(
                        text,
                        available_entities=eff_entities or None,
                        available_predicates=eff_predicates or None,
                    )
                except TypeError:
                    parsed = parser_fn(text)
                if isinstance(parsed, dict):
                    if entity is None and parsed.get("entity"):
                        entity = str(parsed["entity"]).strip()
                        candidates = _extract_candidates(
                            tokens,
                            entity,
                            raw_text=text,
                            known_predicates=eff_predicates if eff_predicates else None,
                        )
                    llm_pred = parsed.get("predicate")
                    if entity and llm_pred:
                        pred_str = str(llm_pred).strip()
                        if all(c.predicate != pred_str for c in candidates):
                            candidates.insert(0, QueryCandidate(entity=entity, predicate=pred_str, score=1.0))
            except Exception:
                pass

        if entity is None:
            raise ValueError(f"Could not extract entity from: {text!r}")

        # No matching predicate → return empty list.
        # The engine interprets this as "no evidence found" and returns
        # Result(value=None, confidence=0.0) without raising.
        return candidates

