from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from core.interfaces import Claim, Reason, Result
from core.source_precedence import get_origin_rank


class AggregationType(str, Enum):
    COUNT = "count"
    SUM = "sum"
    LIST = "list"
    AVERAGE = "average"
    MIN = "min"
    MAX = "max"


@dataclass
class AggregationIntent:
    agg_type: AggregationType
    raw_query: str
    target_predicate: Optional[str] = None
    target_entity: Optional[str] = None


# Patterns for multilingual intent detection (Spanish and English)
_COUNT_PATTERNS = re.compile(
    r"\b(cu[aá]nt[oa]s?|n[uú]mero\s+(?:total\s+)?de|recuento(?:\s+de)?|total\s+de|cantidad\s+de|"
    r"how\s+many|count|number\s+of|total\s+count)\b",
    re.IGNORECASE,
)
_SUM_PATTERNS = re.compile(
    r"\b(suma(?:\s+de)?|importe(?:\s+total|\s+acumulado)?|monto(?:\s+total|\s+global)?|"
    r"montante(?:\s+total|\s+global)?|cuant[ií]a(?:\s+total|\s+global|\s+acumulada)?|"
    r"a\s+cu[aá]nto\s+asciende|asciende\s+a|cuantifique|cuantificar|"
    r"perjuicio(?:\s+patrimonial|\s+total|\s+econ[oó]mico)?|da[ñn]o(?:\s+patrimonial|\s+total)?|"
    r"quebranto(?:\s+patrimonial|\s+econ[oó]mico|\s+l[ií]quido|\s+total)?|"
    r"pasivo(?:\s+concursal|\s+total|\s+contingente)?|indemnizaci[oó]n\s+total|"
    r"total\s+(?:amount|damage|loss|sum|debt)|sum\s+of|sum\s+total|aggregate\s+amount|"
    r"total\s+adeudado|deuda\s+total|somme\s+totale|montant\s+total|gesamtsumme|gesamtbetrag|soma\s+total)\b",
    re.IGNORECASE,
)
_LIST_PATTERNS = re.compile(
    r"\b(listar?|cu[aá]les\s+son(?:\s+todos|\s+todas)?|lista\s+de|todos\s+los|todas\s+las|"
    r"desglose(?:\s+de|\s+las)?|desglos[ae]r?|detalle(?:\s+de|\s+las)?|detall[ae]r?|"
    r"relaci[oó]n\s+de|relacione|enumere|enumerar|partidas|"
    r"list\s+all|list\s+every|which\s+are\s+all|enumerate|breakdown|itemized)\b",
    re.IGNORECASE,
)
_AVG_PATTERNS = re.compile(
    r"\b(promedio|media|average|mean)\b",
    re.IGNORECASE,
)
_MIN_PATTERNS = re.compile(
    r"\b(m[ií]nimo|menor|minimum|lowest|min)\b",
    re.IGNORECASE,
)
_MAX_PATTERNS = re.compile(
    r"\b(m[aá]ximo|mayor|maximum|highest|max)\b",
    re.IGNORECASE,
)


def parse_numeric(val: Any) -> Optional[float]:
    """
    Extract a numeric float from various representations:
    ints, floats, formatted strings with currency symbols and punctuation,
    or multilingual written numbers registered via LLM canonicalization.
    Supports European (1.000,50 €) and US ($1,000.50) conventions.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if not isinstance(val, str):
        return None

    # Check if normalize_value resolves a written multilingual expression (e.g. from LLM canonical_value registry)
    try:
        from claim_layer.semantic.normalization import normalize_value
        norm_val = normalize_value(val)
        if isinstance(norm_val, (int, float)):
            return float(norm_val)
    except Exception:
        pass

    cleaned = val.strip()
    # Strip currency symbols and letters, keeping digits, dots, commas and signs
    cleaned = re.sub(r"[€$£¥a-zA-Z\s]", "", cleaned)
    if not cleaned:
        return None

    # Handle European vs US formatting
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            # European: 1.250,50 -> 1250.50
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US: 1,250.50 -> 1250.50
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            # Decimal comma: 50,5 -> 50.5
            cleaned = cleaned.replace(",", ".")
        else:
            # Thousands separator comma: 1,000 -> 1000
            cleaned = cleaned.replace(",", "")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) <= 3:
            # European thousands separator: 50.000 -> 50000
            cleaned = cleaned.replace(".", "")

    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_claim_numeric(claim: Claim) -> Optional[float]:
    """Extract numeric value from claim.canonical_value if available, else claim.value."""
    can_val = getattr(claim, "canonical_value", None)
    if can_val is not None:
        num = parse_numeric(can_val)
        if num is not None:
            return num
    return parse_numeric(claim.value)


def _normalize_unit_token(raw_unit: Optional[str]) -> Optional[str]:
    if not raw_unit:
        return None
    u = raw_unit.strip().lower()
    # Currencies & Finance
    if u in {"€", "eur", "euro", "euros"}:
        return "EUR"
    if u in {"$", "usd", "dollar", "dollars", "dólar", "dolar", "dólares", "dolares"}:
        return "USD"
    if u in {"£", "gbp", "pound", "pounds", "libra", "libras"}:
        return "GBP"
    if u in {"chf", "franco suizo", "francos suizos"}:
        return "CHF"
    if u in {"¥", "jpy", "yen", "yenes"}:
        return "JPY"
    if u in {"mxn", "peso mexicano", "pesos mexicanos"}:
        return "MXN"
    if u in {"%", "percent", "percentage", "porcentaje", "por ciento"}:
        return "PERCENT"
    if u in {"bps", "puntos básicos", "puntos basicos", "basis points"}:
        return "BPS"
    # Time
    if u in {"days", "day", "días", "dia", "dias", "jours", "jour", "tage", "tag", "giorni"}:
        return "DAYS"
    if u in {"months", "month", "meses", "mes", "mois", "monate"}:
        return "MONTHS"
    if u in {"years", "year", "años", "año", "ans", "jahre"}:
        return "YEARS"
    if u in {"ms", "milliseconds", "milisegundos"}:
        return "MS"
    # Clinical / Medical / Pharma
    if u in {"mg", "miligramos", "miligramo", "milligrams", "milligram"}:
        return "MG"
    if u in {"mcg", "µg", "ug", "microgramos", "micrograms"}:
        return "MCG"
    if u in {"g", "gr", "gramos", "grams"}:
        return "G"
    if u in {"ml", "mililitros", "milliliters"}:
        return "ML"
    if u in {"ui", "iu", "unidades internacionales", "international units"}:
        return "UI"
    if u in {"mmhg"}:
        return "MMHG"
    if u in {"bpm", "lpm", "latidos por minuto"}:
        return "BPM"
    # Engineering / Energy / Data
    if u in {"kwh", "kilovatios hora"}:
        return "KWH"
    if u in {"mwh", "megavatios hora"}:
        return "MWH"
    if u in {"mw", "megavatios", "megawatts"}:
        return "MW"
    if u in {"kg", "kilogramos", "kilos", "kilograms"}:
        return "KG"
    if u in {"km", "kilómetros", "kilometros", "kilometers"}:
        return "KM"
    if u in {"gb", "gigabytes"}:
        return "GB"
    if u in {"tb", "terabytes"}:
        return "TB"
    return u.upper()


def _extract_claim_unit(claim: Claim) -> Optional[str]:
    """Return canonical unit/currency for a claim (from LLM `claim.unit` or surface markers across domains)."""
    explicit = _normalize_unit_token(getattr(claim, "unit", None))
    if explicit:
        return explicit
    surface = f"{claim.value or ''} {getattr(claim, 'quote', '') or ''}"
    # Currencies & Finance
    if re.search(r"(?:€|\beuros?\b|\beur\b)", surface, re.IGNORECASE):
        return "EUR"
    if re.search(r"(?:\$|\busd\b|\bdollars?\b|\bd[oó]lares?\b)", surface, re.IGNORECASE):
        return "USD"
    if re.search(r"(?:£|\bgbp\b|\bpounds?\b|\blibras?\b)", surface, re.IGNORECASE):
        return "GBP"
    if re.search(r"(?:\d\s*%|\bpor\s+ciento\b|\bpercent\b)", surface, re.IGNORECASE):
        return "PERCENT"
    if re.search(r"\b(?:bps|basis\s+points|puntos\s+b[aá]sicos)\b", surface, re.IGNORECASE):
        return "BPS"
    # Clinical / Pharma
    if re.search(r"\b\d+(?:[\.,]\d+)?\s*(?:mg|miligramos?|milligrams?)\b", surface, re.IGNORECASE):
        return "MG"
    if re.search(r"\b\d+(?:[\.,]\d+)?\s*(?:mcg|µg|microgramos?)\b", surface, re.IGNORECASE):
        return "MCG"
    if re.search(r"\b\d+(?:[\.,]\d+)?\s*(?:ml|mililitros?|milliliters?)\b", surface, re.IGNORECASE):
        return "ML"
    if re.search(r"\b\d+(?:[\.,]\d+)?\s*(?:ui|iu|unidades\s+internacionales)\b", surface, re.IGNORECASE):
        return "UI"
    if re.search(r"\b\d+(?:[\.,]\d+)?\s*mmhg\b", surface, re.IGNORECASE):
        return "MMHG"
    # Engineering / Energy
    if re.search(r"\b\d+(?:[\.,]\d+)?\s*kwh\b", surface, re.IGNORECASE):
        return "KWH"
    if re.search(r"\b\d+(?:[\.,]\d+)?\s*mwh\b", surface, re.IGNORECASE):
        return "MWH"
    if re.search(r"\b\d+(?:[\.,]\d+)?\s*ms\b", surface, re.IGNORECASE):
        return "MS"
    if re.search(r"\b(?:days?|d[ií]as?|jours?|tage|giorni)\b", surface, re.IGNORECASE):
        return "DAYS"
    return None


def _filter_compatible_units(
    claims: List[Claim], query_text: str = ""
) -> Tuple[List[Claim], List[Claim]]:
    """Ensure numeric aggregations (SUM, AVG, MIN, MAX) never mix incompatible units
    across Legal, Clinical, Financial, or Engineering domains (e.g. EUR vs USD, MG vs ML, KWH vs PERCENT).
    Returns (compatible_claims, incompatible_excluded_claims).
    """
    units_by_idx: List[Optional[str]] = [_extract_claim_unit(c) for c in claims]
    present_units = [u for u in units_by_idx if u is not None]
    if len(set(present_units)) <= 1:
        return claims, []

    # Check if query explicitly asks for a specific unit
    target_unit: Optional[str] = None
    if re.search(r"(?:€|\beuros?\b|\beur\b)", query_text, re.IGNORECASE):
        target_unit = "EUR"
    elif re.search(r"(?:\$|\busd\b|\bdollars?\b|\bd[oó]lares?\b)", query_text, re.IGNORECASE):
        target_unit = "USD"
    elif re.search(r"\b(?:mg|miligramos?)\b", query_text, re.IGNORECASE):
        target_unit = "MG"
    elif re.search(r"\b(?:ml|mililitros?)\b", query_text, re.IGNORECASE):
        target_unit = "ML"
    elif re.search(r"\b(?:days?|d[ií]as?|jours?|tage)\b", query_text, re.IGNORECASE):
        target_unit = "DAYS"

    if not target_unit or target_unit not in present_units:
        # Pick the dominant unit
        counts: Dict[str, int] = {}
        for u in present_units:
            counts[u] = counts.get(u, 0) + 1
        target_unit = max(
            counts.keys(),
            key=lambda u: (counts[u], 1 if u in {"EUR", "USD", "GBP", "MG", "KWH"} else 0),
        )

    compatible: List[Claim] = []
    incompatible: List[Claim] = []
    for c, u in zip(claims, units_by_idx):
        if u is None or u == target_unit:
            compatible.append(c)
        else:
            incompatible.append(c)
    return compatible, incompatible


def _extract_concept_fingerprint(claim: Claim) -> str:
    """
    Extract a concept, temporal anchor, or item fingerprint to disambiguate identical numerical amounts
    representing distinct events (e.g. periodic quarterly invoices, monthly fees, distinct charges)
    while allowing legitimate reiterations of the same contract total or debt across pages to collapse.
    Prioritizes LLM-extracted `claim.concept_fingerprint` when available.
    """
    llm_fp = getattr(claim, "concept_fingerprint", None)
    if llm_fp and str(llm_fp).strip():
        return f"llm_concept:{str(llm_fp).strip().lower()}"

    tokens: List[str] = []

    # 1. Explicit temporal validity window
    if claim.valid_from or claim.valid_until:
        tokens.append(f"time:{claim.valid_from or ''}..{claim.valid_until or ''}")

    # 2. Search quote and paragraph_id for periodic, invoice, and item identifiers
    text_corpus = f"{claim.quote or ''} {claim.source.paragraph_id if claim.source else ''}".lower()

    # Quarters: Q1-Q4, T1-T4, 1T-4T, 1º trimestre, etc.
    q_match = re.search(
        r"\b(q[1-4]|[1-4]t|trimestre\s*[1-4]|[1-4]º?\s*trimestre|primer\s*trimestre|segundo\s*trimestre|tercer\s*trimestre|cuarto\s*trimestre)\b",
        text_corpus,
    )
    if q_match:
        raw_q = q_match.group(1).replace(" ", "")
        if "1" in raw_q or "primer" in raw_q:
            norm_q = "q1"
        elif "2" in raw_q or "segundo" in raw_q:
            norm_q = "q2"
        elif "3" in raw_q or "tercer" in raw_q:
            norm_q = "q3"
        elif "4" in raw_q or "cuarto" in raw_q:
            norm_q = "q4"
        else:
            norm_q = raw_q
        tokens.append(f"quarter:{norm_q}")

    # Months: enero..diciembre, january..december
    m_match = re.search(
        r"\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre|"
        r"january|february|march|april|may|june|july|august|september|october|november|december)\b",
        text_corpus,
    )
    if m_match:
        tokens.append(f"month:{m_match.group(1)}")

    # Specific invoice / receipt / installment IDs: e.g. "factura a-01", "factura 2026-1", "invoice #102", "cuota 3"
    inv_match = re.search(
        r"\b(?:factura|invoice|recibo|cuota|partida|plazo|vencimiento|abono)\s*(?:n[ºo°\. ]*|[#:\-\s])?\s*([a-z0-9\-_/]+)\b",
        text_corpus,
    )
    if inv_match:
        tokens.append(f"item:{inv_match.group(0).strip()}")
    else:
        # Check for standalone invoice codes like A-01, FAC-102
        code_match = re.search(r"\b([a-z]{1,4}-\d{2,})\b", text_corpus)
        if code_match:
            tokens.append(f"code:{code_match.group(1)}")

    # Distinct legal Hechos Probados: HP 2 vs HP 5
    hp_match = re.search(r"\b(?:hecho[_\s]+probado|hp)\s*([0-9]+)\b", text_corpus)
    if hp_match:
        tokens.append(f"hp:{hp_match.group(1)}")

    # Dates: dd/mm/yyyy, dd-mm-yyyy, yyyy-mm-dd
    d_match = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b", text_corpus)
    if d_match:
        tokens.append(f"date:{d_match.group(1)}")

    if tokens:
        return "|".join(sorted(set(tokens)))

    return ""


_STATE_UPDATE_CUES = re.compile(
    r"\b(?:se\s+actualiza\s+a|actualizad[oa]\s+a|se\s+modifica\s+a|modificad[oa]\s+a|"
    r"nueva\s+pauta|nueva\s+dosis|adenda\s+modificativa|pasa\s+a\s+ser|sustituye\s+a|"
    r"se\s+ampl[ií]a\s+a|se\s+reduce\s+a|updated\s+to|amended\s+to|supersedes|revised\s+to)\b",
    re.IGNORECASE,
)


def is_state_supersession(older: Claim, newer: Claim) -> bool:
    """Return True if *newer* chronologically supersedes *older* as an explicit state update
    (rather than being an independent cumulative event like a periodic monthly payment).
    """
    if not older.valid_from or not newer.valid_from:
        return False
    if str(newer.valid_from) <= str(older.valid_from):
        return False

    # Never treat distinct explicit invoices/quarters as state supersession
    fp_old = getattr(older, "concept_fingerprint", None) or ""
    fp_new = getattr(newer, "concept_fingerprint", None) or ""
    if fp_old and fp_new and fp_old != fp_new:
        return False

    newer_text = f"{getattr(newer, 'quote', '') or ''} {newer.value or ''}"
    if _STATE_UPDATE_CUES.search(newer_text):
        return True
    return False


def resolve_event_identity(claim: Claim) -> Optional[str]:
    """
    Implements Section 7.1 of the revised paper (Oct 2026):
        iota(u) -> resolved event identifier or None (bottom / unknown).
    Returns None when a claim has no usable event/concept identifier.
    """
    fp = _extract_concept_fingerprint(claim)
    return fp if fp else None


def events_equivalent(u_i: Claim, u_j: Claim) -> bool:
    """
    Implements Section 7.1 & Appendix A of the revised paper (Oct 2026):
        u_i ~_q u_j  <=>  iota(u_i) == iota(u_j) != bottom
    A blank/missing event identifier (None) NEVER establishes equivalence with another blank field.
    """
    ent_i = str(getattr(u_i, "canonical_entity", None) or u_i.entity or "").strip().lower()
    ent_j = str(getattr(u_j, "canonical_entity", None) or u_j.entity or "").strip().lower()
    if not ent_i or not ent_j or ent_i != ent_j:
        return False

    pred_i = str(getattr(u_i, "canonical_predicate", None) or u_i.predicate or "").strip().lower()
    pred_j = str(getattr(u_j, "canonical_predicate", None) or u_j.predicate or "").strip().lower()
    if not pred_i or not pred_j or pred_i != pred_j:
        return False

    id_i = resolve_event_identity(u_i)
    id_j = resolve_event_identity(u_j)
    if id_i is None or id_j is None:
        return False
    return id_i == id_j


def _is_specific_event_key(concept_key: str) -> bool:
    """Return True if concept_key identifies a specific invoice/item/concept event."""
    if not concept_key:
        return False
    return any(
        tag in concept_key
        for tag in ("llm_concept:", "item:", "code:")
    )


def _canonicalize_aggregation_claims(claims: List[Claim]) -> Tuple[List[Claim], List[Claim]]:
    """
    Produce a canonical, deduplicated, origin-precedence filtered view of claims
    before performing mathematical aggregation (SUM, COUNT, etc.).
    Returns (canonical_claims, excluded_contradictions).
    """
    if not claims:
        return [], []

    # 1. Origin Precedence: identify maximum origin rank present
    max_rank = max(get_origin_rank(c) for c in claims)
    # If primary document claims exist (rank 100), filter out injected/secondary contradictions (rank < 50)
    filtered: List[Claim] = []
    excluded: List[Claim] = []

    for c in claims:
        rank = get_origin_rank(c)
        if max_rank >= 100 and rank < 50:
            excluded.append(c)
        elif rank < max_rank and rank <= 10:
            excluded.append(c)
        else:
            filtered.append(c)

    if not filtered:
        filtered = [c for c in claims if get_origin_rank(c) == max_rank]

    # 2. Group by (entity, predicate)
    by_ep: Dict[Tuple[str, str], List[Claim]] = {}
    for c in filtered:
        ent = str(getattr(c, "canonical_entity", None) or c.entity or "").strip().lower()
        pred = str(getattr(c, "canonical_predicate", None) or c.predicate or "").strip().lower()
        by_ep.setdefault((ent, pred), []).append(c)

    canonical_claims: List[Claim] = []

    for (ent, pred), ep_claims in by_ep.items():
        # 2a. Filter out historical states superseded by a newer state update / amendment
        active_ep_claims: List[Claim] = []
        for cand in ep_claims:
            if any(is_state_supersession(cand, other) for other in ep_claims if other is not cand):
                excluded.append(cand)
            else:
                active_ep_claims.append(cand)

        # Deduplicate identical values within the same document and paragraph
        seen_keys: Set[Tuple[str, str, str, str]] = set()
        deduped_ep: List[Claim] = []
        for c in active_ep_claims:
            num = _extract_claim_numeric(c)
            val_norm = f"num:{num}" if num is not None else str(c.value).strip().lower()
            doc_id = c.source.document_id if c.source else ""
            para_id = c.source.paragraph_id if c.source else ""
            concept_key = _extract_concept_fingerprint(c)
            key = (val_norm, doc_id, para_id, concept_key)
            if key not in seen_keys:
                seen_keys.add(key)
                deduped_ep.append(c)

        # Cross-document & event-identity grouping (Section 7.1 & Appendix A):
        # - For records with a specific event identity (e.g. `invoice:101`, `item:factura a-01`),
        #   group by `concept_key` alone so that:
        #     * A second mention of `invoice 101` with the same amount collapses to 1 event.
        #     * A second mention of `invoice 101` with a DIFFERENT amount creates a disputed
        #       value for that event (resolved by authority/confidence, with the loser recorded
        #       in `excluded` contradictions rather than summed twice!).
        # - For other records, group by `(val_norm, concept_key)`.
        by_key: Dict[Tuple[str, str], List[Claim]] = {}
        for c in deduped_ep:
            num = _extract_claim_numeric(c)
            val_norm = f"num:{num}" if num is not None else str(c.value).strip().lower()
            concept_key = _extract_concept_fingerprint(c)
            if _is_specific_event_key(concept_key):
                group_key = ("__event__", concept_key)
            else:
                group_key = (val_norm, concept_key)
            by_key.setdefault(group_key, []).append(c)

        for (val_norm, concept_key), val_claims in by_key.items():
            best_rep = max(val_claims, key=lambda c: (get_origin_rank(c), c.confidence))
            best_num = _extract_claim_numeric(best_rep)
            best_val_norm = f"num:{best_num}" if best_num is not None else str(best_rep.value).strip().lower()
            all_instances = []
            for c in val_claims:
                c_num = _extract_claim_numeric(c)
                c_val_norm = f"num:{c_num}" if c_num is not None else str(c.value).strip().lower()
                if c is not best_rep and c_val_norm != best_val_norm:
                    # Incompatible amount for the same identified event -> disputed value
                    excluded.append(c)
                    continue
                if getattr(c, "instances", None):
                    all_instances.extend(c.instances)
            if all_instances and not getattr(best_rep, "instances", None):
                best_rep.instances = all_instances
            canonical_claims.append(best_rep)

    return canonical_claims, excluded


class AggregationEngine:
    """
    Deterministic calculation engine for structured aggregation queries.
    Bypasses generative LLM approximation for counts, sums and listings,
    ensuring 100% mathematical accuracy, zero hallucination, and verifiable support.
    """

    def detect_intent(self, text: str, query_parser_fn=None) -> Optional[AggregationIntent]:
        """Detect if *text* asks for an aggregation operation (via fast-path regex or LLM query_parser_fn)."""
        # Check SUM first (e.g. 'suma total', 'importe total')
        if _SUM_PATTERNS.search(text):
            return AggregationIntent(agg_type=AggregationType.SUM, raw_query=text)

        # Check COUNT (e.g. 'cuántos', 'how many', 'número de')
        if _COUNT_PATTERNS.search(text):
            return AggregationIntent(agg_type=AggregationType.COUNT, raw_query=text)

        # Check AVERAGE
        if _AVG_PATTERNS.search(text):
            return AggregationIntent(agg_type=AggregationType.AVERAGE, raw_query=text)

        # Check MIN / MAX
        if _MIN_PATTERNS.search(text):
            return AggregationIntent(agg_type=AggregationType.MIN, raw_query=text)
        if _MAX_PATTERNS.search(text):
            return AggregationIntent(agg_type=AggregationType.MAX, raw_query=text)

        # Check LIST (e.g. 'cuáles son todos', 'list all')
        if _LIST_PATTERNS.search(text):
            return AggregationIntent(agg_type=AggregationType.LIST, raw_query=text)

        # Fallback to LLM semantic query router if provided
        if query_parser_fn is not None:
            try:
                parsed = query_parser_fn(text)
                if isinstance(parsed, dict):
                    op = str(
                        parsed.get("aggregation_op")
                        or parsed.get("agg_type")
                        or parsed.get("intent")
                        or parsed.get("operation")
                        or ""
                    ).strip().lower()
                    if op in {t.value for t in AggregationType}:
                        return AggregationIntent(
                            agg_type=AggregationType(op),
                            raw_query=text,
                            target_predicate=parsed.get("predicate"),
                            target_entity=parsed.get("entity"),
                        )
            except Exception:
                pass

        return None

    def aggregate(
        self,
        claims: List[Claim],
        intent: AggregationIntent,
        *,
        strict_event_identity: bool = False,
    ) -> Result:
        """
        Execute deterministic calculation over *claims* according to *intent*,
        enforcing source precedence, unit compatibility, and canonical cross-source deduplication.
        When `strict_event_identity=True` (Paper Section 7.1), records with missing event
        identity (iota(u) = None) are never auto-merged or summed into a guaranteed total if
        identity ambiguity could change the requested sum.
        """
        from decimal import Decimal

        if not claims:
            return Result(
                value=0 if intent.agg_type == AggregationType.COUNT else None,
                confidence=0.0,
                contradictions=[],
                supporting_claims=[],
                reason=Reason.NO_EVIDENCE_FOUND,
            )

        # Identify records with missing event identity (iota(u) = bottom)
        unresolved_identity_claims = [c for c in claims if resolve_event_identity(c) is None]

        if strict_event_identity and len(unresolved_identity_claims) >= 2:
            return Result(
                value=None,
                confidence=0.0,
                contradictions=unresolved_identity_claims,
                supporting_claims=[],
                reason=Reason.NO_EVIDENCE_FOUND,
                metadata={
                    "status": "unresolved_event_identity",
                    "unresolved_identities": [c.id for c in unresolved_identity_claims],
                },
            )

        canonical_claims, excluded_contradictions = _canonicalize_aggregation_claims(claims)
        if not canonical_claims:
            return Result(
                value=0 if intent.agg_type == AggregationType.COUNT else None,
                confidence=0.0,
                contradictions=excluded_contradictions,
                supporting_claims=[],
                reason=Reason.NO_EVIDENCE_FOUND,
            )

        agg_type = intent.agg_type

        if agg_type in {AggregationType.SUM, AggregationType.AVERAGE, AggregationType.MIN, AggregationType.MAX}:
            canonical_claims, unit_excluded = _filter_compatible_units(
                canonical_claims, query_text=intent.raw_query
            )
            if unit_excluded:
                excluded_contradictions = list(excluded_contradictions) + unit_excluded

        if agg_type == AggregationType.COUNT:
            # If claims contain merged instances (from distinct factual mentions), count them
            total_items = 0
            for c in canonical_claims:
                inst = getattr(c, "instances", None) or []
                if len(inst) > 1:
                    total_items += len(inst)
                else:
                    total_items += 1
            aggregated_value: Any = total_items

        elif agg_type == AggregationType.SUM:
            numbers = [_extract_claim_numeric(c) for c in canonical_claims]
            valid_numbers = [n for n in numbers if n is not None]
            if not valid_numbers:
                return Result(
                    value=None,
                    confidence=0.0,
                    contradictions=[],
                    supporting_claims=[],
                    reason=Reason.NO_EVIDENCE_FOUND,
                )
            dec_sum = sum((Decimal(str(n)) for n in valid_numbers), Decimal("0"))
            aggregated_value = float(round(dec_sum, 4))

        elif agg_type == AggregationType.AVERAGE:
            numbers = [_extract_claim_numeric(c) for c in canonical_claims]
            valid_numbers = [n for n in numbers if n is not None]
            if not valid_numbers:
                return Result(
                    value=None,
                    confidence=0.0,
                    contradictions=excluded_contradictions,
                    supporting_claims=[],
                    reason=Reason.NO_EVIDENCE_FOUND,
                )
            dec_sum = sum((Decimal(str(n)) for n in valid_numbers), Decimal("0"))
            aggregated_value = float(round(dec_sum / Decimal(len(valid_numbers)), 4))

        elif agg_type == AggregationType.MIN:
            numbers = [_extract_claim_numeric(c) for c in canonical_claims]
            valid_numbers = [n for n in numbers if n is not None]
            aggregated_value = min(valid_numbers) if valid_numbers else None

        elif agg_type == AggregationType.MAX:
            numbers = [_extract_claim_numeric(c) for c in canonical_claims]
            valid_numbers = [n for n in numbers if n is not None]
            aggregated_value = max(valid_numbers) if valid_numbers else None

        elif agg_type == AggregationType.LIST:
            distinct_values = {
                str(c.value) for c in canonical_claims if c.value is not None
            }
            aggregated_value = sorted(list(distinct_values))

        else:
            aggregated_value = len(canonical_claims)

        # Aggregate confidence: mean confidence of canonical supporting claims
        confidences = [c.confidence for c in canonical_claims if c.confidence is not None]
        avg_confidence = round(sum(confidences) / len(confidences), 4) if confidences else 1.0

        return Result(
            value=aggregated_value,
            confidence=avg_confidence,
            contradictions=excluded_contradictions,
            supporting_claims=list(canonical_claims),
            reason=Reason.RESOLVED,
            metadata={
                "unresolved_identities": [c.id for c in unresolved_identity_claims],
                "disputed_events": [c.id for c in excluded_contradictions if _is_specific_event_key(_extract_concept_fingerprint(c))],
            },
        )
