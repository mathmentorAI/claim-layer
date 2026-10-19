from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
from typing import Any

# Ensure repo root is importable so core.* modules (Sprints 1-4) are always available
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import claim_layer.semantic.embeddings as _emb_module
from claim_layer import (
    ClaimLayerStore,
    IngestedClaim,
    IngestedDocument,
    IngestedEntity,
    IngestedFact,
    IngestedSource,
)
from claim_layer.api.query import ask as _ask
from claim_layer.semantic.normalization import (
    LLMValueNormalizer,
    normalize_entity_name,
    normalize_predicate_name,
    normalize_value,
    register_canonical_value,
    register_entity_alias,
    register_predicate_alias,
)
from claim_layer.semantic.truth import aggregate_support

from claimlayer.embeddings.simple import SimpleHashEmbeddingProvider

from core.aggregation_engine import AggregationEngine
from core.claim_adapter import decompose_confidence
from core.claim_consolidator import ClaimConsolidator
from core.claim_extractor import ExtractedClaim
from core.epistemic_judge import EpistemicJudge
from core.graph_traverser import DependencyGraph
from core.interfaces import BLOCKED_INFERENCE_TYPES, INFERENCE_WEIGHTS, Claim, SourceRef
from core.query_layer import LLMQueryRouter, QueryLayer, _extract_entity
from core.source_precedence import OriginTier, get_origin_rank

# shared sentinel — one instance is sufficient
_DEFAULT_PROVIDER = SimpleHashEmbeddingProvider()
_DEFAULT_DB = None  # resolved lazily per instance when db_path is not supplied


# ---------------------------------------------------------------------------
# Deterministic Statement-to-(Entity, Predicate, Value) Deconstruction
# ---------------------------------------------------------------------------

_PAGE_PARA_PREFIX = re.compile(
    r"^\s*[\[\(]\s*(?:P[aá]g(?:ina)?\.?\s*(\d+))?(?:[\s,;]+P[aá]rrafo\s*([a-zA-Z0-9_\-]+))?\s*[\]\)]\s*",
    re.IGNORECASE,
)
_ORIGIN_PREFIX = re.compile(
    r"^\s*[\[\(]\s*(PRIMARY_DOCUMENT|SECONDARY_ANNEX|ANNEX|EXTERNAL_INJECTED|EXTERNAL|NOTA\s+EXTERNA|ANEXO)\s*[\]\)]\s*",
    re.IGNORECASE,
)
_CATEGORY_PREFIX = re.compile(
    r"^\s*(?:Categor[ií]a\s*:\s*)?(Hecho(?:\s+de\s+[\w\s/]+|\s+Probado|\s+Temporal|\s+Normativo|\s+Descriptivo)?(?:\s+\d+)?|Petitum|Suplico|Fundamento(?:\s+de\s+Derecho|\s+Jur[ií]dico)?(?:\s+\d+)?|Prueba(?:\s+\d+)?|Fallo)\s*:\s*",
    re.IGNORECASE,
)
_LAYOUT_NOISE_REGEX = re.compile(
    r"^\s*(?:p[aá]gina\s+\d+(?:\s+de\s+\d+)?|page\s+\d+(?:\s+of\s+\d+)?|folio\s+\d+|rollo\s+de\s+sala\s*\d*)\s*$",
    re.IGNORECASE,
)

# Payment terms pattern (Multilingual: EN, ES, FR, DE, PT, IT):
_PAYMENT_TERMS_PATTERN = re.compile(
    r"(?:payment\s+terms?\s+(?:are|is|:)|paid\s+within|payment\s+is\s+due\s+within|plazo\s+de\s+pago\s*(?:es(?:\s+de)?|:)|d[ée]lai\s+de\s+paiement\s*(?:est(?:\s+de)?|:)|zahlungsziel\s*(?:ist|von|:)|prazo\s+de\s+pagamento\s*(?:[ée](?:\s+de)?|:))\s*"
    r"([a-zA-Z0-9áéíóúñàèêëïîôùûüçäöß\s\-]+?\s*(?:days?|d[ií]as?|jours?|tage?n?|giorni))\b",
    re.IGNORECASE,
)

# Monetary amount pattern (EUR / € / $)
_MONETARY_AMOUNT_PATTERN = re.compile(
    r"(\d{1,3}(?:[\.,]\d{3})+(?:[\.,]\d{1,2})?\s*(?:€|EUR|euros?|\$|USD)|\d+(?:[\.,]\d{1,2})?\s*(?:€|EUR|euros?))",
    re.IGNORECASE,
)

# English functional attribute: "ACME payment terms are 30 days"
_EN_ATTR_PATTERN = re.compile(
    r"^([A-Z][\w\.\-&]*(?:\s+[A-Z][\w\.\-&]*){0,3})\s+"
    r"(payment\s+terms?|payment\s+days?|governing\s+law|jurisdiction|amount|price|penalty|"
    r"status|role|nationality|director|administrator|subsidiary|offense|crime|contract|deadline)\s+"
    r"(?:are|is|was|were|equals?|=|:)\s+(.+?)\.?$",
    re.IGNORECASE,
)

# Spanish functional attribute: "El plazo de pago de ACME es 30 días" / "El importe de Contrato_1 asciende a 142.000 €"
_ES_OF_ATTR_PATTERN = re.compile(
    r"^(?:El|La|Los|Las)\s+([a-záéíóúñ][a-záéíóúñ_\s]{2,35}?)\s+(?:de|del|para)\s+"
    r"([A-ZÁÉÍÓÚÑ][\wáéíóúñÁÉÍÓÚÑ\.\-&]*(?:\s+[A-ZÁÉÍÓÚÑa-záéíóúñ][\wáéíóúñÁÉÍÓÚÑ\.\-&]*){0,3}?)\s+"
    r"(?:es(?:\s+de)?|son(?:\s+de)?|fue(?:\s+de)?|asciende\s+a|alcanza|suma|consiste\s+en)\s+(.+?)\.?$"
)

# Spanish subject-first attribute: "ACME tiene un plazo de pago de 30 días" / "Filial_Sur tiene como administrador a Juan Pérez"
_ES_SUBJ_ATTR_PATTERN = re.compile(
    r"^(?:El|La)?\s*([A-ZÁÉÍÓÚÑ][\wáéíóúñÁÉÍÓÚÑ\.\-&]*(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñÁÉÍÓÚÑ\.\-&]*){0,3})\s+"
    r"(?:tiene|tienen|establece|fija|presenta|reclama|imputa|designa)\s+"
    r"(?:como\s+|un\s+|una\s+|el\s+|la\s+)?([a-záéíóúñ][a-záéíóúñ_\s]{2,30}?)\s+"
    r"(?:a|de|por|en|:)\s+(.+?)\.?$"
)


def _normalize_predicate_slug(raw_pred: str) -> str:
    slug = re.sub(r"\s+", "_", raw_pred.strip().lower())
    aliases = {
        "payment_terms": "payment_terms",
        "payment_term": "payment_terms",
        "plazo_de_pago": "payment_days",
        "plazo_pago": "payment_days",
        "importe": "amount",
        "importe_total": "amount",
        "importe_del_contrato": "amount",
        "cuantia": "amount",
        "cuantía": "amount",
        "monto": "amount",
        "precio": "amount",
        "factura": "amount",
        "delito_imputado": "delito",
        "cargo": "delito",
    }
    return aliases.get(slug, slug)


def _map_claim_type(raw_cat: str) -> str:
    low = (raw_cat or "").lower()
    if any(
        k in low
        for k in (
            "petitum", "suplico", "súplica", "fallo", "obligation", "obligación",
            "prescription", "prescripción", "treatment_plan", "dosage_order",
            "guidance", "target", "forecast", "requirement", "requisito",
        )
    ):
        return "petitum"
    if any(
        k in low
        for k in (
            "fundamento", "normativo", "condition", "prohibition", "definition",
            "clinical_guideline", "protocol", "protocolo", "contraindication",
            "covenant", "ifrs", "policy", "sla", "specification", "iso_standard",
        )
    ):
        return "fundamento"
    if any(
        k in low
        for k in (
            "prueba", "pericial", "testifical", "evidence",
            "lab_result", "biopsy", "biopsia", "analítica", "analitica", "imaging", "biomarker",
            "audit_report", "bank_statement", "benchmark", "test_report", "telemetry_log",
        )
    ):
        return "prueba"
    return "hecho"


def _map_inference_type(raw_inf: str | None) -> str:
    if not raw_inf:
        return "deductive"
    low = str(raw_inf).strip().lower()
    mapping = {
        "deductiva": "deductive",
        "deductive": "deductive",
        "sintáctica": "syntactic",
        "sintactica": "syntactic",
        "syntactic": "syntactic",
        "aritmética": "arithmetic",
        "aritmetica": "arithmetic",
        "arithmetic": "arithmetic",
        "lógica": "logical",
        "logica": "logical",
        "logical": "logical",
        "semántica": "semantic",
        "semantica": "semantic",
        "semantic": "semantic",
        "espacial": "spatial",
        "spatial": "spatial",
        "sentido común": "common_sense",
        "sentido comun": "common_sense",
        "common_sense": "common_sense",
        "causal": "causal",
        "inductiva": "inductive",
        "inductive": "inductive",
        "multi-hop": "multi_hop",
        "multihop": "multi_hop",
        "multi_hop": "multi_hop",
        "probabilística": "probabilistic",
        "probabilistica": "probabilistic",
        "probabilistic": "probabilistic",
        "narrativa": "narrative",
        "narrative": "narrative",
        "abductiva": "abductive",
        "abductive": "abductive",
        "heurística": "heuristic",
        "heuristica": "heuristic",
        "heuristic": "heuristic",
    }
    return mapping.get(low, low)


def _map_origin_tier(raw_tier: str | None) -> str:
    if not raw_tier:
        return OriginTier.PRIMARY_DOCUMENT
    up = str(raw_tier).strip().upper()
    if "ANNEX" in up or "ANEXO" in up or "SECONDARY" in up:
        return OriginTier.SECONDARY_ANNEX
    if "EXTERNAL" in up or "INJECTED" in up or "EXTERNA" in up:
        return OriginTier.EXTERNAL_INJECTED
    return OriginTier.PRIMARY_DOCUMENT


def _parse_statement_to_structured(text: str, idx: int) -> dict[str, Any]:
    """
    Deterministically decomposes a plain text statement into a structured
    evidence unit dictionary with (entity, predicate, value, claim_type, page,
    paragraph_id, origin_tier, quote).

    Prevents the v1.0 ('document', 'statement') single-bucket collision where
    all statements in a document were treated as mutually exclusive contradictions.
    """
    raw_text = (text or "").strip()
    working = raw_text
    page: int = 1
    paragraph_id: str = f"p{idx + 1}"
    origin_tier: str = OriginTier.PRIMARY_DOCUMENT
    claim_type: str = "hecho"

    # 1. Extract optional origin tier prefix: [ANEXO], [EXTERNAL], etc.
    m_orig = _ORIGIN_PREFIX.match(working)
    if m_orig:
        origin_tier = _map_origin_tier(m_orig.group(1))
        working = working[m_orig.end():].strip()

    # 2. Extract optional [Pág. X, Párrafo Y] prefix
    m_coord = _PAGE_PARA_PREFIX.match(working)
    if m_coord:
        if m_coord.group(1):
            page = int(m_coord.group(1))
        if m_coord.group(2):
            paragraph_id = m_coord.group(2)
        working = working[m_coord.end():].strip()

    # 3. Extract optional category prefix ("Hecho Probado 1: ...", "Petitum: ...", "Categoría: ...")
    m_cat = _CATEGORY_PREFIX.match(working)
    if m_cat:
        claim_type = _map_claim_type(m_cat.group(1))
        working = working[m_cat.end():].strip()

    # 3b. Check general payment terms pattern (EN & ES) before generic _EN_ATTR_PATTERN
    m_pay = _PAYMENT_TERMS_PATTERN.search(working)
    if m_pay:
        val_days = m_pay.group(1).strip()
        is_es = "plazo" in working.lower() or "días" in val_days.lower() or "dias" in val_days.lower()
        ent_match = _EN_ATTR_PATTERN.match(working)
        ent_name = ent_match.group(1).strip() if ent_match and ent_match.group(1).lower() not in {"payment", "updated", "invoices"} else ("Contrato" if is_es else "Contract")
        return {
            "entity": ent_name,
            "predicate": "payment_days" if is_es else "payment_terms",
            "value": val_days,
            "claim_type": claim_type,
            "page": page,
            "paragraph_id": paragraph_id,
            "origin_tier": origin_tier,
            "quote": raw_text,
        }

    # 4. Try functional attribute extraction (EN & ES)
    m_en = _EN_ATTR_PATTERN.match(working)
    if m_en:
        entity = m_en.group(1).strip()
        predicate = _normalize_predicate_slug(m_en.group(2))
        value = m_en.group(3).strip().rstrip(".")
        return {
            "entity": entity,
            "predicate": predicate,
            "value": value,
            "claim_type": claim_type,
            "page": page,
            "paragraph_id": paragraph_id,
            "origin_tier": origin_tier,
            "quote": raw_text,
        }

    m_es_of = _ES_OF_ATTR_PATTERN.match(working)
    if m_es_of:
        predicate = _normalize_predicate_slug(m_es_of.group(1))
        entity = m_es_of.group(2).strip()
        value = m_es_of.group(3).strip().rstrip(".")
        return {
            "entity": entity,
            "predicate": predicate,
            "value": value,
            "claim_type": claim_type,
            "page": page,
            "paragraph_id": paragraph_id,
            "origin_tier": origin_tier,
            "quote": raw_text,
        }

    m_es_subj = _ES_SUBJ_ATTR_PATTERN.match(working)
    if m_es_subj:
        entity = m_es_subj.group(1).strip()
        predicate = _normalize_predicate_slug(m_es_subj.group(2))
        value = m_es_subj.group(3).strip().rstrip(".")
        return {
            "entity": entity,
            "predicate": predicate,
            "value": value,
            "claim_type": claim_type,
            "page": page,
            "paragraph_id": paragraph_id,
            "origin_tier": origin_tier,
            "quote": raw_text,
        }

    # 4b. Check monetary amount in financial/invoice/damage statements
    m_amt = _MONETARY_AMOUNT_PATTERN.search(working)
    if m_amt:
        extracted_ent = _extract_entity(working) or "Expediente"
        return {
            "entity": extracted_ent,
            "predicate": "amount",
            "value": m_amt.group(1).strip(),
            "claim_type": claim_type,
            "page": page,
            "paragraph_id": paragraph_id,
            "origin_tier": origin_tier,
            "quote": raw_text,
        }

    # 5. Open statement: assign distinct predicate so complementary atomic facts
    # from the same document are NOT pitted against each other as mutually exclusive
    # values of a single ("document", "statement") slot.
    extracted_ent = _extract_entity(working) or "Expediente"
    return {
        "entity": extracted_ent,
        "predicate": f"{claim_type}_{idx}",
        "value": working,
        "claim_type": claim_type,
        "page": page,
        "paragraph_id": paragraph_id,
        "origin_tier": origin_tier,
        "quote": raw_text,
    }


class ClaimLayer:
    """Public API for the ClaimLayer v2.0 Evidence Intelligence engine.

    Unifies the SQLite/vector store (`claim_layer`) with the v2.0 deterministic
    modules (`ClaimConsolidator`, `EpistemicJudge`, `SourcePrecedence`,
    `DependencyGraph` with Attenuated Gödel T-Norm, and `AggregationEngine`
    with periodic payment disambiguation).
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        embedding_provider=None,
        project_id: str = "default",
        block_unproven_inferences: bool = True,
        normalizer_fn=None,
        query_parser_fn=None,
    ) -> None:
        self._provider = embedding_provider or _DEFAULT_PROVIDER
        self._project_id = project_id
        self._block_unproven_inferences = block_unproven_inferences
        self._normalizer_fn = normalizer_fn
        self._query_parser_fn = query_parser_fn

        if db_path is None:
            self._tmpdir = tempfile.TemporaryDirectory()
            db_path = Path(self._tmpdir.name) / "evidence.db"
        else:
            self._tmpdir = None

        self._store = ClaimLayerStore(Path(db_path), enable_semantic=True)

        # Sprint 1-6 v2.0 Deterministic & Hybrid Engines
        self._consolidator = ClaimConsolidator()
        self._epistemic_judge = EpistemicJudge()
        self._aggregation_engine = AggregationEngine()
        self._query_layer = QueryLayer(query_parser_fn=query_parser_fn)

        # Verified structured ledger & audit state
        self._core_claims: list[Claim] = []
        self._verified_ids: set[str] = set()
        self._ledger_map: dict[str, Claim] = {}
        self.blocked_claims: list[dict[str, Any]] = []
        self._ingest_counter: int = 0

        if self._tmpdir is None:
            self._rehydrate_from_store()

    def _rehydrate_from_store(self) -> None:
        """Rehydrate in-memory _core_claims ledger when opening an existing persistent SQLite database."""
        try:
            with self._store._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        c.external_id,
                        e.name AS entity_name,
                        f.fact_type,
                        f.value,
                        d.filename,
                        c.page,
                        c.paragraph_id,
                        c.confidence,
                        f.inference_type,
                        f.valid_from,
                        f.valid_until,
                        c.text AS quote
                    FROM facts f
                    JOIN claims c ON f.claim_id = c.id
                    JOIN entities e ON f.entity_id = e.id
                    JOIN documents d ON c.document_id = d.id
                    WHERE d.project_id = ?
                    ORDER BY f.id ASC
                    """,
                    (self._project_id,),
                ).fetchall()
            for idx, r in enumerate(rows):
                cid = str(r["external_id"] or f"rehydrated_{idx}")
                origin_tier = _map_origin_tier(r["filename"])
                claim_obj = Claim(
                    id=cid,
                    entity=r["entity_name"],
                    predicate=r["fact_type"],
                    value=r["value"],
                    source=SourceRef(
                        document_id=r["filename"],
                        page=int(r["page"] or 1),
                        paragraph_id=str(r["paragraph_id"] or f"p{idx + 1}"),
                        origin_tier=origin_tier,
                    ),
                    confidence=float(r["confidence"] or 1.0),
                    inference_type=str(r["inference_type"] or "deductive"),
                    valid_from=r["valid_from"],
                    valid_until=r["valid_until"],
                    origin_tier=origin_tier,
                    quote=r["quote"],
                    instances=[cid],
                )
                self._core_claims.append(claim_obj)
                self._verified_ids.add(cid)
                self._ledger_map[cid] = claim_obj
                self._ingest_counter += 1
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    @staticmethod
    def _string_to_document(text: str, idx: int, project_id: str) -> IngestedDocument:
        """Wrap a plain string into a structured IngestedDocument."""
        parsed = _parse_statement_to_structured(text, idx)
        cid = f"c{idx}"
        ent_id = f"e_{re.sub(r'[^a-zA-Z0-9_]', '_', parsed['entity'])}"
        return IngestedDocument(
            project_id=project_id,
            filename=f"input_{idx}.txt",
            entities=[IngestedEntity(ent_id, parsed["entity"])],
            claims=[
                IngestedClaim(
                    cid,
                    parsed["quote"],
                    confidence=1.0,
                    page=parsed["page"],
                    paragraph_id=parsed["paragraph_id"],
                )
            ],
            facts=[
                IngestedFact(
                    cid,
                    ent_id,
                    parsed["predicate"],
                    parsed["value"],
                    sources=[
                        IngestedSource(
                            page=parsed["page"],
                            paragraph_id=parsed["paragraph_id"],
                            text=parsed["quote"],
                        )
                    ],
                )
            ],
        )

    def _normalize_input_item(
        self, item: Any, seq_idx: int
    ) -> tuple[list[ExtractedClaim], list[dict[str, Any]]]:
        """
        Convert a raw input item (str, dict, Claim, or IngestedDocument) into
        ExtractedClaim objects for consolidation/epistemic auditing alongside metadata.
        """
        if isinstance(item, IngestedDocument):
            extracted_list: list[ExtractedClaim] = []
            meta_list: list[dict[str, Any]] = []
            claim_lookup = {
                (c.claim_id if isinstance(c, IngestedClaim) else c["claim_id"]): c
                for c in item.claims
            }
            ent_lookup = {
                (e.entity_id if isinstance(e, IngestedEntity) else e["entity_id"]): (
                    e.name if isinstance(e, IngestedEntity) else e["name"]
                )
                for e in item.entities
            }
            for f_idx, f in enumerate(item.facts):
                c_ref = f.claim_ref if isinstance(f, IngestedFact) else f["claim_ref"]
                e_ref = f.entity_ref if isinstance(f, IngestedFact) else f["entity_ref"]
                f_type = f.fact_type if isinstance(f, IngestedFact) else f["fact_type"]
                f_val = f.value if isinstance(f, IngestedFact) else f["value"]
                inf_type = (
                    f.inference_type if isinstance(f, IngestedFact) else f.get("inference_type")
                )
                c_obj = claim_lookup.get(c_ref)
                c_text = (
                    (c_obj.text if isinstance(c_obj, IngestedClaim) else c_obj.get("text", f_val))
                    if c_obj
                    else f_val
                )
                c_conf = (
                    (c_obj.confidence if isinstance(c_obj, IngestedClaim) else c_obj.get("confidence", 1.0))
                    if c_obj
                    else 1.0
                )
                c_page = (
                    (c_obj.page if isinstance(c_obj, IngestedClaim) else c_obj.get("page"))
                    if c_obj
                    else None
                ) or 1
                c_para = (
                    (c_obj.paragraph_id if isinstance(c_obj, IngestedClaim) else c_obj.get("paragraph_id"))
                    if c_obj
                    else None
                ) or f"p{seq_idx + 1}"

                ent_name = ent_lookup.get(e_ref, e_ref)
                if ent_name in ("document", "e_doc") and f_type == "statement":
                    parsed = _parse_statement_to_structured(f_val, seq_idx + f_idx)
                    ent_name = parsed["entity"]
                    f_type = parsed["predicate"]
                    f_val = parsed["value"]

                is_inferred = c_conf < 1.0 or inf_type is not None or "inferencia" in (item.filename or "").lower()
                mapped_inf = _map_inference_type(inf_type)
                extracted_list.append(
                    ExtractedClaim(
                        entity=ent_name,
                        predicate=f_type,
                        value=str(f_val),
                        quote=c_text,
                        page_number=c_page,
                        paragraph_id=c_para,
                        confidence=float(c_conf),
                        claim_type="hecho",
                        knowledge_level="L2_INFERRED" if is_inferred else "L1_EXPLICIT",
                        inference_type=mapped_inf,
                    )
                )
                meta_list.append(
                    {
                        "id": str(c_ref),
                        "filename": item.filename or f"doc_{seq_idx}.txt",
                        "origin_tier": _map_origin_tier(item.filename),
                        "premises": [],
                        "require_explicit_premises": False,
                    }
                )
            return extracted_list, meta_list

        if isinstance(item, Claim):
            ext = ExtractedClaim(
                entity=item.entity or "Expediente",
                predicate=item.predicate,
                value=str(item.value),
                quote=item.quote or str(item.value),
                page_number=item.source.page if item.source else 1,
                paragraph_id=(
                    item.source.paragraph_id
                    if item.source and item.source.paragraph_id
                    else f"p{seq_idx + 1}"
                ),
                confidence=item.confidence,
                claim_type=getattr(item, "claim_type", "hecho") or "hecho",
                knowledge_level="L2_INFERRED" if item.premises else "L1_EXPLICIT",
                inference_type=_map_inference_type(item.inference_type),
                valid_from=item.valid_from,
                valid_until=item.valid_until,
                instances=list(item.instances) if item.instances else [],
                canonical_value=getattr(item, "canonical_value", None),
                canonical_entity=getattr(item, "canonical_entity", None),
                canonical_predicate=getattr(item, "canonical_predicate", None),
                concept_fingerprint=getattr(item, "concept_fingerprint", None),
                unit=getattr(item, "unit", None),
                speaker_role=getattr(item, "speaker_role", None),
            )
            meta = {
                "id": item.id or f"c{seq_idx}",
                "filename": item.source.document_id if item.source else f"input_{seq_idx}.txt",
                "origin_tier": _map_origin_tier(
                    item.origin_tier or (item.source.origin_tier if item.source else None)
                ),
                "premises": list(item.premises) if item.premises else [],
                "require_explicit_premises": bool(item.premises),
            }
            return [ext], [meta]

        if isinstance(item, dict):
            if "claims" in item and "facts" in item:
                doc_obj = IngestedDocument(
                    project_id=item.get("project_id", self._project_id),
                    filename=item.get("filename", f"doc_{seq_idx}.txt"),
                    entities=item.get("entities", []),
                    claims=item.get("claims", []),
                    facts=item.get("facts", []),
                )
                return self._normalize_input_item(doc_obj, seq_idx)

            raw_text = (
                item.get("quote")
                or item.get("text")
                or item.get("inferred_fact")
                or item.get("value")
                or ""
            )
            if _LAYOUT_NOISE_REGEX.match(str(raw_text)):
                self.blocked_claims.append({"text": str(raw_text), "reason": "layout_noise"})
                return [], []

            parsed = _parse_statement_to_structured(str(raw_text), seq_idx)
            entity = item.get("entity") or parsed["entity"]
            predicate = (
                _normalize_predicate_slug(item["predicate"])
                if item.get("predicate")
                else parsed["predicate"]
            )
            value = str(item.get("value") if item.get("value") is not None else parsed["value"])
            quote = str(item.get("quote") or item.get("text") or raw_text or value)
            page = int(item.get("page") or item.get("page_number") or parsed["page"])
            paragraph_id = str(item.get("paragraph_id") or parsed["paragraph_id"])
            claim_type = _map_claim_type(item.get("claim_type") or parsed["claim_type"])
            origin_tier = _map_origin_tier(item.get("origin_tier") or parsed["origin_tier"])
            conf = float(item.get("confidence", 1.0))
            raw_inf = item.get("inference_type")
            mapped_inf = _map_inference_type(raw_inf)
            premises = item.get("premises")
            is_inferred = (
                item.get("knowledge_level") in ("inferred", "L2_INFERRED")
                or raw_inf is not None
                or premises is not None
                or conf < 1.0
            )
            ext = ExtractedClaim(
                entity=entity,
                predicate=predicate,
                value=value,
                quote=quote,
                page_number=page,
                paragraph_id=paragraph_id,
                confidence=conf,
                claim_type=claim_type,
                knowledge_level="L2_INFERRED" if is_inferred else "L1_EXPLICIT",
                inference_type=mapped_inf,
                valid_from=item.get("valid_from"),
                valid_until=item.get("valid_until"),
                canonical_value=item.get("canonical_value"),
                canonical_entity=item.get("canonical_entity"),
                canonical_predicate=(
                    _normalize_predicate_slug(item["canonical_predicate"])
                    if item.get("canonical_predicate")
                    else None
                ),
                concept_fingerprint=item.get("concept_fingerprint"),
                unit=item.get("unit"),
                speaker_role=item.get("speaker_role"),
            )
            meta = {
                "id": str(item.get("id") or f"c{seq_idx}"),
                "filename": str(
                    item.get("document_id") or item.get("filename") or f"input_{seq_idx}.txt"
                ),
                "origin_tier": origin_tier,
                "premises": list(premises) if premises is not None else [],
                "require_explicit_premises": bool(
                    item.get("require_explicit_premises", False) or ("premises" in item)
                ),
            }
            return [ext], [meta]

        # Plain string
        raw_str = str(item).strip()
        if not raw_str or _LAYOUT_NOISE_REGEX.match(raw_str):
            self.blocked_claims.append({"text": raw_str, "reason": "layout_noise"})
            return [], []

        parsed = _parse_statement_to_structured(raw_str, seq_idx)
        ext = ExtractedClaim(
            entity=parsed["entity"],
            predicate=parsed["predicate"],
            value=parsed["value"],
            quote=parsed["quote"],
            page_number=parsed["page"],
            paragraph_id=parsed["paragraph_id"],
            confidence=1.0,
            claim_type=parsed["claim_type"],
            knowledge_level="L1_EXPLICIT",
            inference_type="deductive",
        )
        meta = {
            "id": f"c{seq_idx}",
            "filename": f"input_{seq_idx}.txt",
            "origin_tier": parsed["origin_tier"],
            "premises": [],
            "require_explicit_premises": False,
        }
        return [ext], [meta]

    @property
    def core_claims(self) -> list[Claim]:
        return self._core_claims

    @property
    def rejected_claims(self) -> list[dict[str, Any]]:
        return self.blocked_claims

    def ingest(
        self,
        documents: list[Any],
        consolidate: bool = True,
        enforce_epistemic_judge: bool = True,
    ) -> dict[str, Any]:
        """Ingest one or more evidence items into ClaimLayer v2.0."""
        batch_extracted: list[ExtractedClaim] = []
        blocked_before = len(self.blocked_claims)
        extracted_before = len(self._core_claims)

        for item in documents:
            seq_idx = self._ingest_counter
            self._ingest_counter += 1
            ext_list, meta_list = self._normalize_input_item(item, seq_idx)
            for ext, meta in zip(ext_list, meta_list):
                if self._consolidator._is_noise(ext):
                    self.blocked_claims.append({"text": ext.quote, "reason": "layout_noise"})
                    continue
                # Apply LLM-driven / custom canonical value, entity & predicate normalizers at ingestion time
                if ext.canonical_value is None and self._normalizer_fn is not None:
                    ext.canonical_value = self._normalizer_fn(ext.value)
                if ext.canonical_value is not None:
                    ext.canonical_value = register_canonical_value(ext.value, ext.canonical_value)
                if ext.canonical_entity:
                    register_entity_alias(ext.entity, ext.canonical_entity)
                if ext.canonical_predicate:
                    register_predicate_alias(ext.predicate, ext.canonical_predicate)
                    ext.predicate = ext.canonical_predicate
                setattr(ext, "_meta", meta)
                batch_extracted.append(ext)

        if not batch_extracted:
            new_rejected = self.blocked_claims[blocked_before:]
            return {
                "claims_extracted": 0,
                "claims_rejected": len(new_rejected),
                "rejected_details": new_rejected,
            }

        if consolidate and len(batch_extracted) > 1:
            batch_extracted = self._consolidator.consolidate(batch_extracted)

        original_embed = _emb_module.embed
        _emb_module.embed = self._provider.embed
        touched_filenames: set[str] = set()
        try:
            for idx, ext in enumerate(batch_extracted):
                meta = getattr(
                    ext,
                    "_meta",
                    {
                        "id": f"c{self._ingest_counter + idx}",
                        "filename": f"input_{self._ingest_counter + idx}.txt",
                        "origin_tier": OriginTier.PRIMARY_DOCUMENT,
                        "premises": [],
                        "require_explicit_premises": False,
                    },
                )
                cid = meta["id"]
                origin_tier = meta["origin_tier"]
                premises = meta["premises"]
                effective_entity = ext.canonical_entity or ext.entity
                effective_predicate = ext.canonical_predicate or ext.predicate

                core_claim = Claim(
                    id=cid,
                    entity=effective_entity,
                    predicate=effective_predicate,
                    value=ext.value,
                    source=SourceRef(
                        document_id=meta["filename"],
                        page=ext.page_number,
                        paragraph_id=ext.paragraph_id,
                        origin_tier=origin_tier,
                    ),
                    confidence=ext.confidence,
                    inference_type=ext.inference_type,
                    valid_from=ext.valid_from,
                    valid_until=ext.valid_until,
                    premises=premises,
                    origin_tier=origin_tier,
                    quote=ext.quote,
                    instances=list(ext.instances) if ext.instances else [cid],
                    canonical_value=ext.canonical_value,
                    canonical_entity=ext.canonical_entity,
                    canonical_predicate=ext.canonical_predicate,
                    concept_fingerprint=ext.concept_fingerprint,
                    unit=ext.unit,
                    speaker_role=ext.speaker_role,
                )

                # Epistemic Judge Verification & Monotonic Closure
                if enforce_epistemic_judge:
                    audit_res = self._epistemic_judge.audit_claim(
                        core_claim,
                        verified_premise_ids=self._verified_ids,
                        require_declared_premises=meta.get("require_explicit_premises", False),
                        premise_lookup=self._ledger_map,
                    )
                    if audit_res.is_overridden:
                        core_claim.inference_type = audit_res.audited_type

                    if (
                        self._block_unproven_inferences
                        and core_claim.inference_type in BLOCKED_INFERENCE_TYPES
                    ):
                        self.blocked_claims.append(
                            {
                                "id": cid,
                                "text": ext.quote,
                                "original_type": audit_res.original_type,
                                "audited_type": audit_res.audited_type,
                                "speaker_role": ext.speaker_role,
                                "reason": audit_res.override_reason or "blocked_epistemic_type",
                            }
                        )
                        continue

                    # Apply deterministic epistemic weight from INFERENCE_WEIGHTS for inferred claims
                    if ext.knowledge_level == "L2_INFERRED":
                        epistemic_w = INFERENCE_WEIGHTS.get(core_claim.inference_type, 0.5)
                        core_claim.confidence = round(min(core_claim.confidence, epistemic_w), 4)

                # Register in verified ledger
                self._core_claims.append(core_claim)
                self._verified_ids.add(cid)
                self._ledger_map[cid] = core_claim
                touched_filenames.add(meta["filename"])

            # Persist in SQLite ClaimLayerStore grouped by filename (1 atomic transaction per document)
            for fname in sorted(touched_filenames):
                doc_claims = [c for c in self._core_claims if c.source.document_id == fname]
                seen_ent_ids: set[str] = set()
                ing_entities: list[IngestedEntity] = []
                seen_claim_ids: set[str] = set()
                ing_claims: list[IngestedClaim] = []
                ing_facts: list[IngestedFact] = []

                for dc_idx, dc in enumerate(doc_claims):
                    ent_name = dc.entity or "Expediente"
                    ent_id = f"e_{re.sub(r'[^a-zA-Z0-9_]', '_', ent_name)}"
                    if ent_id not in seen_ent_ids:
                        seen_ent_ids.add(ent_id)
                        ing_entities.append(IngestedEntity(ent_id, ent_name))

                    c_ref = dc.id or f"c_{fname}_{dc_idx}"
                    if c_ref in seen_claim_ids:
                        c_ref = f"{c_ref}__f{dc_idx}"
                    seen_claim_ids.add(c_ref)

                    ing_claims.append(
                        IngestedClaim(
                            claim_id=c_ref,
                            text=dc.quote or str(dc.value),
                            confidence=dc.confidence,
                            page=dc.source.page,
                            paragraph_id=dc.source.paragraph_id,
                        )
                    )
                    ing_facts.append(
                        IngestedFact(
                            claim_ref=c_ref,
                            entity_ref=ent_id,
                            fact_type=dc.predicate,
                            value=str(dc.value),
                            sources=[
                                IngestedSource(
                                    page=dc.source.page,
                                    paragraph_id=dc.source.paragraph_id,
                                    text=dc.quote or str(dc.value),
                                )
                            ],
                            valid_from=dc.valid_from,
                            valid_until=dc.valid_until,
                            inference_type=dc.inference_type,
                        )
                    )

                ing_doc = IngestedDocument(
                    project_id=self._project_id,
                    filename=fname,
                    entities=ing_entities,
                    claims=ing_claims,
                    facts=ing_facts,
                )
                self._store.ingest_document(ing_doc)
        finally:
            _emb_module.embed = original_embed

        new_rejected = self.blocked_claims[blocked_before:]
        return {
            "claims_extracted": len(self._core_claims) - extracted_before,
            "claims_rejected": len(new_rejected),
            "rejected_details": new_rejected,
        }

    # ------------------------------------------------------------------
    # Query & Resolution
    # ------------------------------------------------------------------

    def _find_core_claims(self, entity: str, predicate: str, value: str | None = None) -> list[Claim]:
        norm_ent = normalize_entity_name(entity)
        norm_pred = normalize_predicate_name(predicate)
        matches = [
            c
            for c in self._core_claims
            if (
                (c.entity or "").lower() == entity.lower()
                or normalize_entity_name(c.entity) == norm_ent
            )
            and (
                c.predicate.lower() == predicate.lower()
                or normalize_predicate_name(c.predicate) == norm_pred
            )
        ]
        if value is not None:
            norm_target = normalize_value(str(value))
            val_matches = [
                c
                for c in matches
                if normalize_value(str(c.value)) == norm_target or str(c.value) == str(value)
            ]
            if val_matches:
                return val_matches
        return matches

    def _compute_jtms_retracted_claims(self, eval_time) -> dict[str, dict[str, Any]]:
        """
        Non-Monotonic Truth Maintenance System (JTMS — Pollock's Undercutting & Rebutting Defeaters):
        Identifies claims in the ledger that are:
          1. Blocked at ingestion (`self.blocked_claims`)
          2. Outside their temporal validity window at `eval_time` (when `eval_time` is specified)
          3. Superseded by a newer state update or Allen-disjoint interval
          4. Defeated by a higher-authority `OriginTier` on the same `(entity, predicate)`
        and propagates retraction transitively in cascade to any derived conclusion (`c.premises`)
        that relies on a retracted premise.
        """
        from datetime import datetime, timezone
        from core.aggregation_engine import is_state_supersession
        from core.inference_engine import _is_active, allen_interval_precedes

        retracted: dict[str, dict[str, Any]] = {}
        now_dt = eval_time or datetime.now(timezone.utc)

        # 1. Blocked claims at ingestion
        for bc in self.blocked_claims:
            if bc.get("id"):
                retracted[str(bc["id"])] = {
                    "claim_id": str(bc["id"]),
                    "reason": "blocked_premise",
                }

        # Group core claims by canonical (entity, predicate)
        by_ep: dict[tuple[str, str], list[Claim]] = {}
        for c in self._core_claims:
            key = (
                normalize_entity_name(c.canonical_entity or c.entity or "").lower(),
                normalize_predicate_name(c.canonical_predicate or c.predicate or "").lower(),
            )
            by_ep.setdefault(key, []).append(c)

        for _, ep_claims in by_ep.items():
            max_origin = max((get_origin_rank(c) for c in ep_claims), default=100)
            for c in ep_claims:
                if not c.id:
                    continue
                ok, why = _is_active(c, now_dt)
                if not ok:
                    retracted[str(c.id)] = {
                        "claim_id": str(c.id),
                        "entity": c.entity,
                        "predicate": c.predicate,
                        "value": c.value,
                        "reason": why,
                    }
                    continue
                if any(is_state_supersession(c, other) for other in ep_claims if other is not c):
                    retracted[str(c.id)] = {
                        "claim_id": str(c.id),
                        "entity": c.entity,
                        "predicate": c.predicate,
                        "value": c.value,
                        "reason": "superseded_state",
                    }
                    continue
                if eval_time is None and any(
                    allen_interval_precedes(c, other) for other in ep_claims if other is not c
                ):
                    retracted[str(c.id)] = {
                        "claim_id": str(c.id),
                        "entity": c.entity,
                        "predicate": c.predicate,
                        "value": c.value,
                        "reason": "allen_precedes_disjoint_interval",
                    }
                    continue
                if get_origin_rank(c) < max_origin and any(
                    get_origin_rank(other) == max_origin
                    and normalize_value(str(other.value)) != normalize_value(str(c.value))
                    for other in ep_claims
                ):
                    retracted[str(c.id)] = {
                        "claim_id": str(c.id),
                        "entity": c.entity,
                        "predicate": c.predicate,
                        "value": c.value,
                        "reason": "defeated_by_higher_origin_tier",
                    }

        # Cascading fixed-point JTMS propagation over premise DAG
        changed = True
        while changed:
            changed = False
            for c in self._core_claims:
                if not c.id or str(c.id) in retracted:
                    continue
                c_premises = getattr(c, "premises", []) or []
                failed = [str(p) for p in c_premises if str(p) in retracted]
                if failed:
                    retracted[str(c.id)] = {
                        "claim_id": str(c.id),
                        "entity": c.entity,
                        "predicate": c.predicate,
                        "value": c.value,
                        "reason": "undercut_by_retracted_premise",
                        "undercut_by": failed,
                    }
                    changed = True

        return retracted

    def ask(self, query: str, top_k: int = 20, as_of: str | None = None) -> dict[str, Any]:
        """Resolve truth, multi-hop chains, point-in-time (`as_of`) intervals, JTMS retractions,
        Jøsang Subjective Logic opinions, and Merkle certificates for *query*.
        """
        from core.epistemic_certificate import (
            compute_subjective_opinion,
            generate_epistemic_certificate,
        )
        from core.inference_engine import (
            _is_active,
            _parse_instant,
            allen_interval_precedes,
            extract_temporal_as_of,
        )

        effective_as_of = _parse_instant(as_of) if as_of else extract_temporal_as_of(query)
        jtms_retracted = self._compute_jtms_retracted_claims(effective_as_of)
        retracted_conclusions = [
            info
            for info in jtms_retracted.values()
            if info.get("reason") == "undercut_by_retracted_premise"
        ]

        base_response = _ask(
            self._store,
            self._project_id,
            query,
            top_k,
            embed_fn=self._provider.embed,
        )
        results: list[dict[str, Any]] = list(base_response.get("results") or [])
        # Filter out unrelated entity stop-word hits if query targets a known entity in the ledger
        q_ent = _extract_entity(query)
        q_norm_text = normalize_entity_name(query)
        for c in self._core_claims:
            for cand_e in (c.canonical_entity, c.entity):
                norm_ce = normalize_entity_name(cand_e)
                if norm_ce and len(norm_ce) >= 3 and norm_ce in q_norm_text:
                    q_ent = cand_e
                    break
        if not q_ent and self._query_parser_fn is not None:
            try:
                parsed_q = self._query_parser_fn(query)
                if isinstance(parsed_q, dict) and parsed_q.get("entity"):
                    q_ent = str(parsed_q["entity"]).strip()
            except Exception:
                pass
        if q_ent:
            norm_q_ent = normalize_entity_name(q_ent)
            if any(
                (c.entity or "").lower() == q_ent.lower()
                or normalize_entity_name(c.entity) == norm_q_ent
                for c in self._core_claims
            ):
                ent_filtered_results = [
                    r
                    for r in results
                    if (r.get("entity") or "").lower() == q_ent.lower()
                    or normalize_entity_name(r.get("entity")) == norm_q_ent
                ]
                if ent_filtered_results:
                    results = ent_filtered_results

        if len(results) > 1:
            q_flat = query.lower().replace("_", " ")
            pred_filtered_results = [
                r
                for r in results
                if (r.get("predicate") or "").lower().replace("_", " ") in q_flat
                or normalize_predicate_name(r.get("predicate") or "").lower().replace("_", " ") in q_flat
            ]
            if pred_filtered_results:
                results = pred_filtered_results

        # Enrich results with OriginTier precedence, Allen Interval Algebra, JTMS retraction,
        # Point-in-Time (`as_of`) filtering, Jøsang Subjective Logic, and Merkle certificates
        all_citations: list[dict[str, Any]] = []
        seen_cit_keys: set[tuple[Any, Any, Any]] = set()
        active_results: list[dict[str, Any]] = []

        for res in results:
            ent = res.get("entity", "")
            pred = res.get("predicate", "")
            val = res.get("value", "")

            all_cand_claims = self._find_core_claims(ent, pred)

            # Filter out claims undercut by JTMS or inactive at Point-in-Time `effective_as_of`
            if all_cand_claims:
                valid_cand_claims = [
                    c
                    for c in all_cand_claims
                    if str(c.id) not in jtms_retracted
                    and (effective_as_of is None or _is_active(c, effective_as_of)[0])
                ]
                if not valid_cand_claims and any(
                    str(c.id) in jtms_retracted for c in all_cand_claims
                ):
                    # All claims for this (entity, predicate) were retracted/expired/undercut
                    continue
                if effective_as_of is not None and valid_cand_claims:
                    # Point-in-Time (`as_of`) resolution: elect the active claim at `effective_as_of`
                    as_of_claim = max(
                        valid_cand_claims,
                        key=lambda c: (get_origin_rank(c), c.confidence),
                    )
                    as_of_val = str(as_of_claim.value)
                    res["value"] = as_of_val
                    res["canonical_value"] = normalize_value(as_of_val)
                    res["as_of"] = effective_as_of.isoformat()
                    res["contradictions"] = [
                        c
                        for c in (res.get("contradictions") or [])
                        if any(
                            str(vc.value) == str(c.get("value")) and str(vc.value) != as_of_val
                            for vc in valid_cand_claims
                        )
                    ]
                    res["confidence"] = round(
                        aggregate_support(
                            [c.confidence for c in valid_cand_claims if str(c.value) == as_of_val]
                        ),
                        6,
                    )
                    val = as_of_val

            # Enforce OriginTier source precedence, Temporal State Supersession & Allen Interval Algebra
            if res.get("contradictions"):
                if all_cand_claims:
                    from core.aggregation_engine import is_state_supersession

                    # 1. Temporal State Supersession & Allen's Interval Algebra (Precedes/Meets)
                    superseded_map: dict[str, str] = {}
                    for cand in all_cand_claims:
                        if any(
                            is_state_supersession(cand, other)
                            for other in all_cand_claims
                            if other is not cand
                        ):
                            superseded_map[str(cand.value)] = "superseded_by_newer_state"
                        elif effective_as_of is None and any(
                            allen_interval_precedes(cand, other)
                            for other in all_cand_claims
                            if other is not cand
                        ):
                            superseded_map[str(cand.value)] = "allen_precedes_disjoint_interval"

                    active_state_claims = [
                        cand
                        for cand in all_cand_claims
                        if str(cand.value) not in superseded_map
                        and str(cand.id) not in jtms_retracted
                    ]
                    if superseded_map and active_state_claims:
                        latest_claim = max(
                            active_state_claims,
                            key=lambda c: (str(c.valid_from or ""), get_origin_rank(c), c.confidence),
                        )
                        latest_val = str(latest_claim.value)
                        res["superseded_states"] = [
                            {"value": sv, "reason": r_why}
                            for sv, r_why in sorted(superseded_map.items())
                        ]
                        res["contradictions"] = [
                            c
                            for c in res["contradictions"]
                            if str(c.get("value")) not in superseded_map
                            and str(c.get("value")) != latest_val
                        ]
                        res["value"] = latest_val
                        res["canonical_value"] = normalize_value(latest_val)
                        res["confidence"] = round(
                            aggregate_support(
                                [c.confidence for c in active_state_claims if str(c.value) == latest_val]
                            ),
                            6,
                        )
                        val = latest_val

                if res.get("contradictions") and all_cand_claims:
                    best_tier_rank = max(get_origin_rank(c) for c in all_cand_claims)
                    winner_claims = self._find_core_claims(ent, pred, val)
                    winner_rank = (
                        max(get_origin_rank(c) for c in winner_claims)
                        if winner_claims
                        else best_tier_rank
                    )
                    if winner_rank < best_tier_rank:
                        top_tier_claims = [
                            c for c in all_cand_claims if get_origin_rank(c) == best_tier_rank
                        ]
                        top_val = str(top_tier_claims[0].value)
                        old_winner = {
                            "value": res["value"],
                            "canonical_value": res["canonical_value"],
                            "confidence": round(res["confidence"] * (winner_rank / best_tier_rank), 6),
                        }
                        res["contradictions"] = [
                            c for c in res["contradictions"] if str(c["value"]) != top_val
                        ] + [old_winner]
                        res["value"] = top_val
                        res["canonical_value"] = normalize_value(top_val)
                        res["confidence"] = round(
                            aggregate_support([c.confidence for c in top_tier_claims]), 6
                        )
                        val = top_val

            matched_claims = self._find_core_claims(ent, pred, val)
            winner_support = 0.0
            contra_support = 0.0
            contra_claim_objs: list[Claim] = []
            if matched_claims:
                # Calibrate epistemic confidence using Sprint 1 dynamic_normalized model
                # so offline hash-embedding similarity does not artificially depress verified facts
                winner_support = aggregate_support([min(0.95, mc.confidence) for mc in matched_claims])
                if not res.get("contradictions"):
                    res["confidence"] = round(
                        max(
                            float(res.get("confidence", 0.0)),
                            aggregate_support([mc.confidence for mc in matched_claims]),
                        ),
                        6,
                    )
                else:
                    for contra in res["contradictions"]:
                        c_claims = self._find_core_claims(ent, pred, str(contra.get("value", "")))
                        if c_claims:
                            contra_claim_objs.extend(c_claims)
                            contra_support += aggregate_support(
                                [min(0.95, cc.confidence) for cc in c_claims]
                            )
                        else:
                            contra_support += float(contra.get("confidence", 0.5))
                    total_support = winner_support + contra_support
                    if total_support > 0:
                        res["confidence"] = round(winner_support / total_support, 6)

            res_citations: list[dict[str, Any]] = []
            for mc in matched_claims:
                cit = {
                    "document_id": mc.source.document_id,
                    "page": mc.source.page,
                    "paragraph_id": mc.source.paragraph_id,
                    "origin_tier": mc.origin_tier,
                    "quote": mc.quote or str(mc.value),
                }
                res_citations.append(cit)
                cit_key = (cit["document_id"], cit["page"], cit["paragraph_id"])
                if cit_key not in seen_cit_keys:
                    seen_cit_keys.add(cit_key)
                    all_citations.append(cit)

            res["citations"] = res_citations
            res["formatted_citations"] = " ".join(
                f"[{c['document_id']}, Pág. {c['page']}, Párrafo {c['paragraph_id']}]"
                if c.get("paragraph_id")
                else f"[{c['document_id']}, Pág. {c['page']}]"
                for c in res_citations
            )
            k_ext, k_struct = decompose_confidence(
                res.get("confidence", 0.0),
                ent,
                pred,
                str(val),
                res_citations[0]["quote"] if res_citations else "",
            )
            res["confidence_decomposition"] = {
                "extraction": k_ext,
                "structuring": k_struct,
                "kappa_extraction": k_ext,
                "kappa_structuring": k_struct,
                "effective_confidence": round(k_ext * k_struct, 4),
            }

            # Attach Jøsang Subjective Logic Opinion & Cryptographic Merkle Certificate
            subj_op = compute_subjective_opinion(
                winner_support or float(res.get("confidence", 0.0)),
                contra_support,
            )
            res["subjective_opinion"] = subj_op.to_dict()
            res["epistemic_certificate"] = generate_epistemic_certificate(
                value=val,
                confidence=float(res.get("confidence", 0.0)),
                reason="contradiction" if res.get("contradictions") else "resolved",
                supporting_claims=matched_claims,
                contradictions=contra_claim_objs,
                subjective_opinion=subj_op,
            )
            active_results.append(res)

        results = active_results

        # Zero-Config: dynamically discover known entities & predicates from ledger
        ledger_entities = [
            e
            for c in self._core_claims
            for e in (c.entity, c.canonical_entity)
            if e
        ]
        ledger_predicates = [
            p
            for c in self._core_claims
            for p in (c.predicate, c.canonical_predicate)
            if p
        ]

        # Check Deterministic Aggregation (SUM, COUNT, LIST, AVG, MIN, MAX)
        agg_intent = self._aggregation_engine.detect_intent(
            query, query_parser_fn=self._query_parser_fn
        )
        aggregation_payload: dict[str, Any] | None = None
        if agg_intent and self._core_claims:
            try:
                q_cands = self._query_layer.parse(
                    query,
                    query_parser_fn=self._query_parser_fn,
                    known_entities=ledger_entities,
                    known_predicates=ledger_predicates,
                )
            except ValueError:
                q_cands = []

            target_claims = [
                c for c in self._core_claims if str(c.id) not in jtms_retracted
            ]
            eff_ent = q_ent or agg_intent.target_entity
            if eff_ent:
                norm_q_ent = normalize_entity_name(eff_ent).lower()
                ent_filtered = [
                    c
                    for c in target_claims
                    if normalize_entity_name(c.canonical_entity or c.entity or "").lower() == norm_q_ent
                    or (c.entity or "").lower() == eff_ent.lower()
                ]
                if ent_filtered:
                    target_claims = ent_filtered
            cand_preds = {
                normalize_predicate_name(c.predicate).lower() for c in q_cands
            } | {c.predicate.lower() for c in q_cands}
            if agg_intent.target_predicate:
                cand_preds.add(normalize_predicate_name(agg_intent.target_predicate).lower())
                cand_preds.add(agg_intent.target_predicate.lower())
            if cand_preds:
                pred_filtered = [
                    c
                    for c in target_claims
                    if normalize_predicate_name(c.canonical_predicate or c.predicate).lower() in cand_preds
                    or c.predicate.lower() in cand_preds
                ]
                if pred_filtered:
                    target_claims = pred_filtered

            agg_res = self._aggregation_engine.aggregate(target_claims, agg_intent)
            if agg_res.value is not None:
                fmt_cit = agg_res.formatted_citations()
                op_upper = agg_intent.agg_type.value.upper()
                agg_subj = compute_subjective_opinion(agg_res.confidence, 0.0)
                agg_cert = generate_epistemic_certificate(
                    value=agg_res.value,
                    confidence=agg_res.confidence,
                    reason=agg_res.reason,
                    supporting_claims=agg_res.supporting_claims,
                    contradictions=agg_res.contradictions or [],
                    subjective_opinion=agg_subj,
                )
                aggregation_payload = {
                    "operation": op_upper,
                    "value": agg_res.value,
                    "result": agg_res.value,
                    "confidence": agg_res.confidence,
                    "answer": agg_res.answer,
                    "citations": agg_res.citations,
                    "formatted_citations": fmt_cit,
                    "subjective_opinion": agg_subj.to_dict(),
                    "epistemic_certificate": agg_cert,
                }
                all_citations = list(agg_res.citations)
                if op_upper == "LIST" and agg_res.supporting_claims:
                    results = [
                        {
                            "entity": sc.entity or eff_ent or "Expediente",
                            "predicate": sc.predicate,
                            "value": str(sc.value),
                            "canonical_value": normalize_value(str(sc.value)),
                            "confidence": sc.confidence,
                            "confidence_explanation": {
                                "aggregation_method": "AggregationEngine(LIST)",
                                "summary": "Verified canonical fact in list enumeration",
                            },
                            "contradictions": [],
                            "supporting_evidence": [
                                {"claim_id": sc.id, "score": sc.confidence, "selected": True}
                            ],
                            "alternative_evidence": [],
                            "citations": [
                                {
                                    "document_id": sc.source.document_id,
                                    "page": sc.source.page,
                                    "paragraph_id": sc.source.paragraph_id,
                                    "origin_tier": sc.origin_tier,
                                    "quote": sc.quote or str(sc.value),
                                }
                            ],
                            "formatted_citations": (
                                f"[{sc.source.document_id}, Pág. {sc.source.page}, Párrafo {sc.source.paragraph_id}]"
                                if sc.source.paragraph_id
                                else f"[{sc.source.document_id}, Pág. {sc.source.page}]"
                            ),
                            "subjective_opinion": compute_subjective_opinion(sc.confidence, 0.0).to_dict(),
                            "epistemic_certificate": agg_cert,
                        }
                        for sc in agg_res.supporting_claims
                    ]
                else:
                    results = [
                        {
                            "entity": eff_ent or "aggregation",
                            "predicate": f"aggregation_{agg_intent.agg_type.value}",
                            "value": str(agg_res.value),
                            "canonical_value": agg_res.value,
                            "confidence": agg_res.confidence,
                            "confidence_explanation": {
                                "aggregation_method": f"AggregationEngine({op_upper})",
                                "summary": f"Deterministic {op_upper} over {len(agg_res.supporting_claims)} canonical claims",
                            },
                            "contradictions": [
                                {"value": str(c.value), "confidence": c.confidence, "claim_id": c.id}
                                for c in (agg_res.contradictions or [])
                            ],
                            "supporting_evidence": [
                                {"claim_id": c.id, "score": c.confidence, "selected": True}
                                for c in agg_res.supporting_claims
                            ],
                            "alternative_evidence": [],
                            "citations": agg_res.citations,
                            "formatted_citations": fmt_cit,
                            "subjective_opinion": agg_subj.to_dict(),
                            "epistemic_certificate": agg_cert,
                        }
                    ]

        # Check Multi-Hop Relational Traversal (Provenance Semiring K = ([0,1], ⊕, ⊗))
        multihop_payload: dict[str, Any] | None = None
        if self._core_claims and aggregation_payload is None:
            try:
                q_cands = self._query_layer.parse(
                    query,
                    query_parser_fn=self._query_parser_fn,
                    known_entities=ledger_entities,
                    known_predicates=ledger_predicates,
                )
            except ValueError:
                q_cands = []

            start_ent = q_ent or (q_cands[0].entity if q_cands else None)
            if start_ent:
                from core.query_layer import QueryCandidate
                q_lower = query.lower()
                existing_preds = {c.predicate.lower() for c in q_cands}
                for c in self._core_claims:
                    for cp in (c.predicate, c.canonical_predicate):
                        if cp and cp.lower() in q_lower and cp.lower() not in existing_preds:
                            q_cands.insert(0, QueryCandidate(entity=start_ent, predicate=cp, score=1.0))
                            existing_preds.add(cp.lower())

            if q_cands and start_ent:
                norm_start_ent = normalize_entity_name(start_ent).lower()
                active_graph_claims = [
                    c for c in self._core_claims if str(c.id) not in jtms_retracted
                ]
                graph = DependencyGraph(active_graph_claims)
                best_mh_res = None
                best_cand = None
                for cand in q_cands:
                    norm_cand_pred = normalize_predicate_name(cand.predicate).lower()
                    cand_direct_hit = any(
                        (
                            normalize_entity_name(c.canonical_entity or c.entity or "").lower() == norm_start_ent
                            or (c.entity or "").lower() == start_ent.lower()
                        )
                        and (
                            normalize_predicate_name(c.canonical_predicate or c.predicate).lower() == norm_cand_pred
                            or c.predicate.lower() == cand.predicate.lower()
                        )
                        for c in active_graph_claims
                    )
                    if cand_direct_hit:
                        continue
                    mh_res = graph.resolve_multihop(start_ent, cand.predicate)
                    if (
                        mh_res
                        and mh_res.value is not None
                        and len(mh_res.supporting_claims) >= 2
                    ):
                        if best_mh_res is None or len(mh_res.supporting_claims) > len(best_mh_res.supporting_claims):
                            best_mh_res = mh_res
                            best_cand = cand

                if best_mh_res is not None and best_cand is not None:
                    fmt_cit = best_mh_res.formatted_citations()
                    mh_contradictions = [
                        {"value": str(c.value), "confidence": c.confidence, "claim_id": c.id}
                        for c in (best_mh_res.contradictions or [])
                    ]
                    mh_subj_dict = (
                        best_mh_res.subjective_opinion.to_dict()
                        if best_mh_res.subjective_opinion
                        else compute_subjective_opinion(best_mh_res.confidence, 0.0).to_dict()
                    )
                    multihop_payload = {
                        "entity": start_ent,
                        "predicate": best_cand.predicate,
                        "value": best_mh_res.value,
                        "hops": len(best_mh_res.supporting_claims),
                        "confidence": best_mh_res.confidence,
                        "contradictions": mh_contradictions,
                        "answer": best_mh_res.answer,
                        "citations": best_mh_res.citations,
                        "formatted_citations": fmt_cit,
                        "subjective_opinion": mh_subj_dict,
                        "epistemic_certificate": best_mh_res.epistemic_certificate,
                    }
                    all_citations = list(best_mh_res.citations)
                    results = [
                        {
                            "entity": start_ent,
                            "predicate": best_cand.predicate,
                            "value": str(best_mh_res.value),
                            "canonical_value": normalize_value(str(best_mh_res.value)),
                            "confidence": best_mh_res.confidence,
                            "confidence_explanation": {
                                "aggregation_method": "Provenance Semiring (Gödel ⊗ + Noisy-OR ⊕)",
                                "summary": f"{len(best_mh_res.supporting_claims)}-hop verified relational path",
                            },
                            "contradictions": mh_contradictions,
                            "supporting_evidence": [
                                {"claim_id": c.id, "score": c.confidence, "selected": True}
                                for c in best_mh_res.supporting_claims
                            ],
                            "alternative_evidence": [],
                            "citations": best_mh_res.citations,
                            "formatted_citations": fmt_cit,
                            "subjective_opinion": mh_subj_dict,
                            "epistemic_certificate": best_mh_res.epistemic_certificate,
                        }
                    ]

        formatted_all = " ".join(
            f"[{c['document_id']}, Pág. {c['page']}, Párrafo {c['paragraph_id']}]"
            if c.get("paragraph_id")
            else f"[{c['document_id']}, Pág. {c['page']}]"
            for c in all_citations
        )

        out: dict[str, Any] = {
            "query": query,
            "results": results,
            "citations": all_citations,
            "formatted_citations": formatted_all,
            "abstain": len(results) == 0,
        }
        if effective_as_of is not None:
            out["as_of"] = effective_as_of.isoformat()
        if retracted_conclusions:
            out["retracted_conclusions"] = retracted_conclusions
        if results and results[0].get("subjective_opinion"):
            out["subjective_opinion"] = results[0]["subjective_opinion"]
        if results and results[0].get("epistemic_certificate"):
            out["epistemic_certificate"] = results[0]["epistemic_certificate"]
        if aggregation_payload is not None:
            out["aggregation"] = aggregation_payload
        if multihop_payload is not None:
            out["multihop"] = multihop_payload
        return out

    def verify_response_integrity(self, response: dict[str, Any]) -> bool:
        """
        Cryptographically verify that an `ask()` response's value, confidence,
        and underlying claims match its Merkle epistemic certificate.
        """
        from core.epistemic_certificate import (
            SubjectiveOpinion,
            verify_epistemic_certificate,
        )

        results = response.get("results") or []
        if not results:
            return False
        top = results[0]
        cert = top.get("epistemic_certificate") or response.get("epistemic_certificate")
        if not cert:
            return False

        # Reconstruct supporting and contradicting claims from ledger
        ent = top.get("entity", "")
        pred = top.get("predicate", "")
        val = top.get("value", "")

        if response.get("multihop") or response.get("aggregation"):
            sup_ids = [ev.get("claim_id") for ev in (top.get("supporting_evidence") or [])]
            sup_claims = [self._ledger_map[cid] for cid in sup_ids if cid in self._ledger_map]
            con_ids = [c.get("claim_id") for c in (top.get("contradictions") or []) if c.get("claim_id")]
            con_claims = [self._ledger_map[cid] for cid in con_ids if cid in self._ledger_map]
        else:
            sup_claims = self._find_core_claims(ent, pred, str(val))
            con_claims = []
            for contra in top.get("contradictions") or []:
                con_claims.extend(self._find_core_claims(ent, pred, str(contra.get("value", ""))))

        op_dict = top.get("subjective_opinion") or {}
        subj_op = (
            SubjectiveOpinion(
                belief=float(op_dict.get("belief", 0.0)),
                disbelief=float(op_dict.get("disbelief", 0.0)),
                uncertainty=float(op_dict.get("uncertainty", 1.0)),
                base_rate=float(op_dict.get("base_rate", 0.5)),
                projected_probability=float(op_dict.get("projected_probability", 0.5)),
                epistemic_regime=str(op_dict.get("epistemic_regime", "VACUOUS_IGNORANCE")),
            )
            if op_dict
            else None
        )
        reason = cert.get("reason") or ("contradiction" if top.get("contradictions") else "resolved")
        return verify_epistemic_certificate(
            cert,
            value=val,
            confidence=float(top.get("confidence", 0.0)),
            reason=reason,
            supporting_claims=sup_claims,
            contradictions=con_claims,
            subjective_opinion=subj_op,
        )
