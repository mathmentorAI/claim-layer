"""Sprint 5 Tests: End-to-End Unification of ClaimLayer, Core v2.0, and Paper Alignment."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest

from claimlayer import ClaimLayer
from core.claim_adapter import compute_structural_fidelity, decompose_confidence
from core.claim_extractor import ExtractedClaim
from core.interfaces import Claim, SourceRef
from core.source_precedence import OriginTier, get_origin_rank, get_origin_tier


def load_pipeline_module():
    script_path = (
        Path(__file__).resolve().parent.parent
        / "skills"
        / "evidence-intelligence"
        / "examples"
        / "pipeline_completo.py"
    )
    spec = importlib.util.spec_from_file_location("pipeline_completo", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestQuickstartAndSpanishNormalization:
    """Verifies the README_INSTALACION.md quickstart and bilingual number normalization."""

    def test_readme_quickstart_english_and_spanish_days(self):
        cl = ClaimLayer()
        cl.ingest(
            [
                "Payment terms are 30 days from invoice date.",
                "Invoices must be paid within thirty days.",
                "Updated terms: payment is due within 45 days.",
            ]
        )
        ans = cl.ask("What are the payment terms?")
        assert len(ans["results"]) >= 1
        top = ans["results"][0]
        assert top["confidence"] > 0.50
        assert "confidence_decomposition" in top
        assert "kappa_extraction" in top["confidence_decomposition"]
        assert "kappa_structuring" in top["confidence_decomposition"]

    def test_spanish_written_numbers_consolidate_with_digits(self):
        cl = ClaimLayer()
        cl.ingest(
            [
                "Plazo de pago: 30 días desde la factura.",
                "Plazo de pago: treinta días desde la factura.",
            ]
        )
        ans = cl.ask("¿Cuál es el plazo de pago?")
        assert len(ans["results"]) >= 1
        top = ans["results"][0]
        # Both statements normalize to the same canonical value, boosting confidence with 0 contradictions
        assert top["contradictions"] == []
        assert top["confidence"] >= 0.85


class TestMultiStatementNoBucketCollision:
    """Verifies elimination of the ('document', 'statement') single-bucket collision."""

    def test_multi_fact_legal_document_does_not_collapse_to_single_result(self):
        cl = ClaimLayer()
        statements = [
            {"text": "Hecho Probado 1: El contrato fue suscrito el 14 de marzo de 2022.", "page": 1, "paragraph_id": "p1"},
            {"text": "Hecho Probado 2: La sociedad demandada incumplió la entrega de los equipos.", "page": 2, "paragraph_id": "p2"},
            {"text": "Hecho Probado 3: El perito judicial tasó los daños materiales en el almacén.", "page": 3, "paragraph_id": "p3"},
            {"text": "Fundamento de Derecho 1: Concurre responsabilidad contractual conforme al artículo 1101.", "page": 4, "paragraph_id": "p4"},
            {"text": "Fundamento de Derecho 2: Procede la imposición de intereses de demora.", "page": 5, "paragraph_id": "p5"},
            {"text": "Fallo: Se condena a la parte demandada al abono de las costas procesales.", "page": 6, "paragraph_id": "p6"},
        ]
        ingest_info = cl.ingest(statements)
        assert ingest_info["claims_extracted"] == 6

        ans = cl.ask("Enumere los hechos probados, fundamentos y el fallo del documento.")
        # Previously len(ans["results"]) == 1 with confidence ~0.04 due to bucket collision
        assert len(ans["results"]) >= 4
        for res in ans["results"]:
            assert res["confidence"] >= 0.70, f"Unexpected confidence collapse: {res}"
            assert res["contradictions"] == []


class TestClaimLayerDeterministicAggregation:
    """Verifies AggregationEngine integration inside ClaimLayer.ask()."""

    def test_periodic_invoices_preserved_and_external_injected_excluded(self):
        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    "text": "Hecho Probado 1: Factura A-01 del primer trimestre (Q1) impagada por 25.000 €.",
                    "page": 2,
                    "paragraph_id": "p1",
                    "origin_tier": OriginTier.PRIMARY_DOCUMENT,
                },
                {
                    "text": "Hecho Probado 2: Factura A-02 del segundo trimestre (Q2) impagada por 25.000 €.",
                    "page": 5,
                    "paragraph_id": "p3",
                    "origin_tier": OriginTier.PRIMARY_DOCUMENT,
                },
                {
                    "text": "Hecho Probado 3: Factura A-03 del tercer trimestre (Q3) impagada por 25.000 €.",
                    "page": 8,
                    "paragraph_id": "p2",
                    "origin_tier": OriginTier.PRIMARY_DOCUMENT,
                },
                {
                    "text": "Nota externa: Recargo estimado no verificado por 5.000 €.",
                    "page": 99,
                    "paragraph_id": "p99",
                    "origin_tier": OriginTier.EXTERNAL_INJECTED,
                },
            ]
        )
        ans = cl.ask("¿A cuánto asciende la suma total de los importes impagados?")
        assert ans.get("aggregation") is not None
        assert ans["aggregation"]["operation"] == "SUM"
        assert ans["aggregation"]["result"] == 75000.0
        assert ans["results"][0]["value"] == "75000.0"
        assert len(ans["citations"]) == 3

    def test_cross_page_duplicate_contract_total_collapses(self):
        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    "text": "Importe total del contrato: 142.000 €.",
                    "entity": "contrato",
                    "predicate": "amount",
                    "value": "142.000 €",
                    "page": 1,
                    "paragraph_id": "p1",
                },
                {
                    "text": "Precio total del contrato: 142.000 €.",
                    "entity": "contrato",
                    "predicate": "amount",
                    "value": "142.000 €",
                    "page": 5,
                    "paragraph_id": "p12",
                },
            ]
        )
        ans = cl.ask("¿Cuál es la suma total del importe del contrato?")
        assert ans.get("aggregation") is not None
        assert ans["aggregation"]["result"] == 142000.0


class TestClaimLayerMultiHopGodelTNorm:
    """Verifies DependencyGraph 3-hop traversal with Attenuated Gödel T-Norm in ClaimLayer.ask()."""

    def test_three_hop_chain_godel_tnorm(self):
        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    "text": "Hecho Probado 1: Grupo_Alfa es matriz de su filial Filial_Sur.",
                    "entity": "Grupo_Alfa",
                    "predicate": "filial",
                    "value": "Filial_Sur",
                    "page": 3,
                    "paragraph_id": "p2",
                },
                {
                    "text": "Hecho Probado 2: Filial_Sur tiene como administrador único a Juan_Perez.",
                    "entity": "Filial_Sur",
                    "predicate": "administrador",
                    "value": "Juan_Perez",
                    "page": 4,
                    "paragraph_id": "p1",
                },
                {
                    "text": "Petitum: Se imputa a Juan_Perez un delito de estafa continuada.",
                    "entity": "Juan_Perez",
                    "predicate": "petitum",
                    "value": "estafa continuada",
                    "page": 9,
                    "paragraph_id": "p4",
                },
            ]
        )
        ans = cl.ask("¿Qué delito o petitum se imputa al administrador de la filial de Grupo_Alfa?")
        assert ans.get("multihop") is not None
        assert ans["multihop"]["hops"] == 3
        assert ans["results"][0]["value"] == "estafa continuada"
        # Gödel T-Norm for 3 hops with step confidences 1.0: 1.0 * (0.95 ** 2) = 0.9025
        assert abs(ans["results"][0]["confidence"] - 0.9025) < 1e-4
        assert len(ans["citations"]) == 3


class TestEpistemicAuditAndSourcePrecedenceInClaimLayer:
    """Verifies EpistemicJudge, layout pruning, and OriginTier precedence inside ClaimLayer."""

    def test_party_allegation_and_layout_noise_blocked_on_ingest(self):
        cl = ClaimLayer()
        info = cl.ingest(
            [
                {"text": "Página 4 de 20", "page": 4, "paragraph_id": "p0"},
                {
                    "text": "La defensa sostiene que el pago extinguió la deuda.",
                    "page": 6,
                    "paragraph_id": "p3",
                    "claim_type": "deductive",
                },
                {
                    "text": "Fallo: Se condena al pago de 50.000 €.",
                    "page": 10,
                    "paragraph_id": "p1",
                },
            ]
        )
        assert info["claims_extracted"] == 1
        assert info["claims_rejected"] == 2
        reasons = [r["reason"] for r in info["rejected_details"]]
        assert any("layout_noise" in r for r in reasons)
        assert any("party allegation" in r for r in reasons)

    def test_origin_tier_enum_string_parsing_and_precedence(self):
        c_ext = Claim(
            id="c_ext",
            entity="Factura_99",
            predicate="amount",
            value="5.000 €",
            source=SourceRef(document_id="ext.txt", page=99, paragraph_id="p99"),
            quote="Importe: 5.000 €",
            confidence=0.95,
            origin_tier=str(OriginTier.EXTERNAL_INJECTED),
        )
        assert get_origin_tier(c_ext) == OriginTier.EXTERNAL_INJECTED
        assert get_origin_rank(c_ext) == 10


class TestPaperDualConfidenceAndSkillPipeline:
    """Verifies Section 8.3.3 dual confidence decomposition and skill pipeline execution."""

    def test_dual_confidence_decomposition_kappa(self):
        c_structured = ExtractedClaim(
            quote="Importe: 25.000 €",
            paragraph_id="p1",
            confidence=0.90,
            entity="Factura_1",
            predicate="amount",
            value="25.000 €",
        )
        c_generic = ExtractedClaim(
            quote="Texto libre sin estructurar",
            paragraph_id="p2",
            confidence=0.90,
            entity="document",
            predicate="statement",
            value="Texto libre sin estructurar",
        )
        assert compute_structural_fidelity(c_structured) == 1.0
        assert compute_structural_fidelity(c_generic) == 0.65

        d1 = decompose_confidence(c_structured)
        d2 = decompose_confidence(c_generic)
        assert d1["kappa_structuring"] == 1.0
        assert d2["kappa_structuring"] == 0.65
        assert d1["effective_confidence"] > d2["effective_confidence"]

    def test_skill_pipeline_completo_demo_runs_cleanly(self):
        mod = load_pipeline_module()
        cl = mod.demo_determinista_offline()
        assert len(cl.core_claims) == 7
        assert len(cl.rejected_claims) == 2


class TestLLMDrivenMultilingualCanonicalNormalization:
    """
    Verifies LLM-driven universal multilingual canonical normalization:
    1. Structured Phase 1 extraction emitting `canonical_value` across any language
       (French, German, Portuguese, complex Spanish text numbers).
    2. `ClaimLayer(normalizer_fn=LLMValueNormalizer(...))` normalizing plain-text
       claims once at ingestion time and caching deterministically for 0ms `ask()`.
    3. `AggregationEngine` summing complex written amounts ("ciento cuarenta y dos mil euros")
       via `canonical_value` and `_CANONICAL_OVERRIDES`.
    """

    def test_structured_canonical_value_reconciles_french_german_portuguese_and_spanish(self):
        from claimlayer import clear_canonical_overrides
        clear_canonical_overrides()

        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    "text": "Le délai de paiement est de trente jours.",
                    "entity": "payment terms",
                    "predicate": "duration",
                    "value": "trente jours",
                    "canonical_value": "30 days",
                    "page": 1,
                    "paragraph_id": "p1",
                },
                {
                    "text": "Die Zahlungsfrist beträgt dreißig Tage.",
                    "entity": "payment terms",
                    "predicate": "duration",
                    "value": "dreißig Tage",
                    "canonical_value": "30 days",
                    "page": 2,
                    "paragraph_id": "p2",
                },
                {
                    "text": "O prazo de pagamento é de trinta dias.",
                    "entity": "payment terms",
                    "predicate": "duration",
                    "value": "trinta dias",
                    "canonical_value": "30 days",
                    "page": 3,
                    "paragraph_id": "p3",
                },
                {
                    "text": "Payment terms are 30 days.",
                    "entity": "payment terms",
                    "predicate": "duration",
                    "value": "30 days",
                    "canonical_value": "30 days",
                    "page": 4,
                    "paragraph_id": "p4",
                },
            ]
        )
        ans = cl.ask("What are the payment terms?")
        assert ans["abstain"] is False
        assert len(ans["results"]) == 1
        assert ans["results"][0]["canonical_value"] == 30
        assert len(ans["results"][0]["contradictions"]) == 0
        assert ans["results"][0]["confidence"] > 0.70

    def test_llm_value_normalizer_hook_in_claimlayer_for_unstructured_multilingual_text(self):
        from claimlayer import LLMValueNormalizer, clear_canonical_overrides
        clear_canonical_overrides()

        llm_calls = []

        def mock_llm_normalizer(raw_val: str):
            llm_calls.append(raw_val)
            mapping = {
                "trente jours": "30 days",
                "dreißig Tage": "30 days",
                "ciento cuarenta y dos mil euros": 142000.0,
            }
            return mapping.get(raw_val, raw_val)

        normalizer = LLMValueNormalizer(llm_callable=mock_llm_normalizer)
        cl = ClaimLayer(normalizer_fn=normalizer)
        cl.ingest(
            [
                {"text": "Payment terms are trente jours.", "page": 1, "paragraph_id": "p1"},
                {"text": "Payment terms are dreißig Tage.", "page": 2, "paragraph_id": "p2"},
                # Duplicate raw value to verify deterministic cache (only 1 LLM call per unique raw value)
                {"text": "Payment terms are trente jours.", "page": 3, "paragraph_id": "p3"},
            ]
        )
        # LLM was called only twice (for "trente jours" and "dreißig Tage")
        assert len(llm_calls) == 2

        ans = cl.ask("What are the payment terms?")
        # Zero additional LLM calls during ask()
        assert len(llm_calls) == 2
        assert ans["abstain"] is False
        assert ans["results"][0]["canonical_value"] == 30
        assert len(ans["results"][0]["contradictions"]) == 0

    def test_complex_written_monetary_amounts_summed_via_llm_canonical_value(self):
        from claimlayer import clear_canonical_overrides
        clear_canonical_overrides()

        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    "text": "Factura A-01 impagada por ciento cuarenta y dos mil euros.",
                    "entity": "Factura_A01",
                    "predicate": "amount",
                    "value": "ciento cuarenta y dos mil euros",
                    "canonical_value": 142000.0,
                    "page": 2,
                    "paragraph_id": "p1",
                },
                {
                    "text": "Factura A-02 impagada por 58.000 €.",
                    "entity": "Factura_A02",
                    "predicate": "amount",
                    "value": "58.000 €",
                    "canonical_value": 58000.0,
                    "page": 4,
                    "paragraph_id": "p2",
                },
            ]
        )
        ans = cl.ask("¿Cuál es la suma total de los importes impagados?")
        assert ans.get("aggregation") is not None
        assert ans["aggregation"]["operation"] == "SUM"
        assert ans["aggregation"]["result"] == 200000.0
        assert ans["results"][0]["value"] == "200000.0"


class TestSprint6UniversalLLMAssistedSemantics:
    """
    Sprint 6 tests verifying the 5 hybrid LLM-assisted semantic capabilities:
    1. Entity coreference & honorific/corporate alias resolution (`canonical_entity`) in 3-hop graphs.
    2. LLM `concept_fingerprint` & unit/currency isolation (`unit="EUR"` vs `"USD"`) in `AggregationEngine`.
    3. Contextual discourse attribution (`speaker_role="PARTY_ALLEGATION"`) blocked by `EpistemicJudge`.
    4. Domain predicate synonym normalization (`canonical_predicate`).
    5. Semantic query routing (`LLMQueryRouter` / `query_parser_fn`).
    """

    def test_entity_coreference_and_honorific_alias_in_3hop_graph(self):
        from claimlayer import clear_canonical_overrides
        clear_canonical_overrides()

        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    "text": "Filial Sur S.A. tiene como administrador único a D. Juan Pérez García.",
                    "entity": "Filial Sur S.A.",
                    "canonical_entity": "Filial_Sur",
                    "predicate": "administrador_unico",
                    "value": "D. Juan Pérez García",
                    "page": 1,
                    "paragraph_id": "p1",
                    "confidence": 0.90,
                },
                {
                    "text": "El Sr. Pérez figura como investigado en el Proceso Penal 402/2025.",
                    "entity": "El Sr. Pérez",
                    "predicate": "investigado_en",
                    "value": "Proceso Penal 402/2025",
                    "page": 4,
                    "paragraph_id": "p2",
                    "confidence": 0.85,
                },
                {
                    "text": "El Expediente 402/2025 se instruye por delito de estafa continuada.",
                    "entity": "Expediente 402/2025",
                    "canonical_entity": "Proceso Penal 402/2025",
                    "predicate": "causa_imputacion",
                    "value": "estafa continuada",
                    "page": 7,
                    "paragraph_id": "p3",
                    "confidence": 0.80,
                },
            ]
        )

        ans = cl.ask("¿Cuál es la causa_imputacion de Filial Sur?")
        assert ans["abstain"] is False
        assert ans.get("multihop") is not None
        assert ans["multihop"]["hops"] == 3
        assert ans["multihop"]["value"] == "estafa continuada"
        # min(0.90, 0.85, 0.80) * 0.95^2 = 0.80 * 0.9025 = 0.722
        assert abs(ans["multihop"]["confidence"] - 0.722) < 1e-3

    def test_concept_fingerprint_and_unit_isolation_in_aggregation(self):
        from claimlayer import clear_canonical_overrides
        clear_canonical_overrides()

        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    "text": "Resumen: el principal reclamado asciende a 55.000 €.",
                    "entity": "Contrato",
                    "predicate": "amount",
                    "value": "55.000 €",
                    "canonical_value": 55000.0,
                    "concept_fingerprint": "principal_contract_debt",
                    "unit": "EUR",
                    "page": 1,
                    "paragraph_id": "p1",
                },
                {
                    "text": "En conclusión, la deuda principal del contrato es de 55.000 €.",
                    "entity": "Contrato",
                    "predicate": "amount",
                    "value": "55.000 €",
                    "canonical_value": 55000.0,
                    "concept_fingerprint": "principal_contract_debt",
                    "unit": "EUR",
                    "page": 8,
                    "paragraph_id": "p8",
                },
                {
                    "text": "Penalización adicional pactada: 15.000 €.",
                    "entity": "Contrato",
                    "predicate": "amount",
                    "value": "15.000 €",
                    "canonical_value": 15000.0,
                    "concept_fingerprint": "penalty_clause_1",
                    "unit": "EUR",
                    "page": 4,
                    "paragraph_id": "p4",
                },
                {
                    "text": "Garantía internacional depositada en cuenta extranjera: 10.000 USD.",
                    "entity": "Contrato",
                    "predicate": "amount",
                    "value": "10.000 USD",
                    "canonical_value": 10000.0,
                    "concept_fingerprint": "foreign_deposit_usd",
                    "unit": "USD",
                    "page": 5,
                    "paragraph_id": "p5",
                },
            ]
        )

        ans = cl.ask("¿Cuál es la suma total de los importes del Contrato?")
        assert ans.get("aggregation") is not None
        assert ans["aggregation"]["operation"] == "SUM"
        # 55.000 € (deduplicated across p1 and p8 via concept_fingerprint="principal_contract_debt")
        # + 15.000 € (penalty_clause_1) = 70.000 €
        # 10.000 USD is isolated due to incompatible unit ("USD" != majority "EUR")
        assert ans["aggregation"]["result"] == 70000.0
        assert len(ans["results"][0]["contradictions"]) == 1

    def test_speaker_role_contextual_attribution_blocked_by_epistemic_judge(self):
        from claimlayer import clear_canonical_overrides
        clear_canonical_overrides()

        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    # Assertive phrasing inside a party allegations section (no explicit "alega que" in the sentence)
                    "text": "El lucro cesante sufrido por la actora asciende a 3.000.000 €.",
                    "entity": "Lucro_Cesante",
                    "predicate": "amount",
                    "value": "3.000.000 €",
                    "canonical_value": 3000000.0,
                    "speaker_role": "PARTY_ALLEGATION",
                    "page": 3,
                    "paragraph_id": "p3",
                    "confidence": 0.92,
                },
                {
                    # Proven judicial finding
                    "text": "Se declara probado que el daño emergente acreditado es de 45.000 €.",
                    "entity": "Dano_Emergente",
                    "predicate": "amount",
                    "value": "45.000 €",
                    "canonical_value": 45000.0,
                    "speaker_role": "COURT_FINDING",
                    "page": 9,
                    "paragraph_id": "p9",
                    "confidence": 0.95,
                },
            ]
        )

        # Party allegation is rejected by EpistemicJudge even without surface "alega que" words
        assert len(cl.core_claims) == 1
        assert len(cl.rejected_claims) == 1
        assert cl.rejected_claims[0]["speaker_role"] == "PARTY_ALLEGATION"

        ans = cl.ask("¿A cuánto asciende la suma total de las partidas?")
        assert ans["aggregation"]["result"] == 45000.0

    def test_canonical_predicate_unifies_domain_synonyms(self):
        from claimlayer import clear_canonical_overrides
        clear_canonical_overrides()

        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    "text": "Los honorarios devengados en primera instancia fueron de 12.000 €.",
                    "entity": "Minuta_1",
                    "predicate": "honorarios_devengados",
                    "canonical_predicate": "amount",
                    "value": "12.000 €",
                    "canonical_value": 12000.0,
                    "concept_fingerprint": "minuta_primera_instancia",
                    "unit": "EUR",
                    "page": 2,
                    "paragraph_id": "p1",
                },
                {
                    "text": "La retribución profesional en apelación ascendió a 8.000 €.",
                    "entity": "Minuta_2",
                    "predicate": "retribucion_profesional",
                    "canonical_predicate": "amount",
                    "value": "8.000 €",
                    "canonical_value": 8000.0,
                    "concept_fingerprint": "minuta_apelacion",
                    "unit": "EUR",
                    "page": 5,
                    "paragraph_id": "p2",
                },
            ]
        )

        ans = cl.ask("¿Cuál es la suma total de los honorarios?")
        assert ans.get("aggregation") is not None
        assert ans["aggregation"]["operation"] == "SUM"
        assert ans["aggregation"]["result"] == 20000.0

    def test_llm_query_router_handles_open_legal_phrasing(self):
        from claimlayer import LLMQueryRouter, clear_canonical_overrides
        clear_canonical_overrides()

        router_calls = []

        def mock_router_llm(q: str):
            router_calls.append(q)
            return {
                "intent": "SUM",
                "entity": "Expediente_Concursal",
                "predicate": "amount",
            }

        router = LLMQueryRouter(llm_callable=mock_router_llm)
        cl = ClaimLayer(query_parser_fn=router)
        cl.ingest(
            [
                {
                    "text": "Crédito privilegiado reconocido: 90.000 €.",
                    "entity": "Expediente_Concursal",
                    "predicate": "amount",
                    "value": "90.000 €",
                    "canonical_value": 90000.0,
                    "concept_fingerprint": "credito_privilegiado",
                    "unit": "EUR",
                    "page": 2,
                    "paragraph_id": "p1",
                },
                {
                    "text": "Crédito ordinario reconocido: 60.000 €.",
                    "entity": "Expediente_Concursal",
                    "predicate": "amount",
                    "value": "60.000 €",
                    "canonical_value": 60000.0,
                    "concept_fingerprint": "credito_ordinario",
                    "unit": "EUR",
                    "page": 3,
                    "paragraph_id": "p2",
                },
            ]
        )

        # Phrasing that doesn't match any regex in _SUM_PATTERNS
        open_query = "Ruego determinen el volumen consolidado de la masa pasiva en este procedimiento"
        ans = cl.ask(open_query)
        assert ans.get("aggregation") is not None
        assert ans["aggregation"]["operation"] == "SUM"
        assert ans["aggregation"]["result"] == 150000.0
        # Router caches deterministically per query string
        assert len(router_calls) == 1


class TestSprint7ZeroConfigCrossDomainGeneralization:
    """
    Sprint 7 tests verifying Zero-Config cross-domain readiness across Clinical/Medical,
    Financial/Audit, and Engineering/Cybersecurity domains without prior configuration:
    1. Dynamic ledger schema auto-discovery (`known_entities`, `known_predicates`) in `QueryLayer`.
    2. Cross-domain `EpistemicJudge` roles (`PATIENT_SELF_REPORT`, `MANAGEMENT_PROJECTION`, `USER_TICKET_REPORT` vs `LAB_CONFIRMED`, `AUDITED_STATEMENT`, `VERIFIED_TELEMETRY`).
    3. Temporal state supersession (`is_state_supersession`) vs cumulative events.
    4. Universal clinical, financial, and engineering unit isolation (`MG` vs `ML`, `EUR` vs `PERCENT`).
    5. Cross-domain `claim_type` mapping (`prescription`, `lab_result`, `covenant`, `sla`).
    """

    def test_zero_config_clinical_medical_domain_supersession_and_epistemic_audit(self):
        from claimlayer import clear_canonical_overrides
        clear_canonical_overrides()

        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    "text": "Pauta inicial (enero 2026): dosis de warfarina de 5 mg diarios.",
                    "entity": "Paciente_Gomez",
                    "predicate": "dosis_warfarina",
                    "value": "5 mg",
                    "canonical_value": 5.0,
                    "unit": "mg",
                    "claim_type": "prescription",
                    "speaker_role": "CLINICAL_FINDING",
                    "valid_from": "2026-01-10",
                    "valid_until": "2026-05-14",
                    "page": 1,
                    "paragraph_id": "p1",
                    "confidence": 0.92,
                },
                {
                    "text": "Revisión hematológica (mayo 2026): se actualiza a nueva pauta de 2.5 mg diarios.",
                    "entity": "Paciente_Gomez",
                    "predicate": "dosis_warfarina",
                    "value": "2.5 mg",
                    "canonical_value": 2.5,
                    "unit": "mg",
                    "claim_type": "prescription",
                    "speaker_role": "LAB_CONFIRMED",
                    "valid_from": "2026-05-15",
                    "page": 4,
                    "paragraph_id": "p2",
                    "confidence": 0.95,
                },
                {
                    "text": "El paciente refiere creer que padece insuficiencia hepática severa sin analítica.",
                    "entity": "Paciente_Gomez",
                    "predicate": "diagnostico_secundario",
                    "value": "insuficiencia hepática",
                    "claim_type": "symptom",
                    "speaker_role": "PATIENT_SELF_REPORT",
                    "page": 2,
                    "paragraph_id": "p3",
                    "confidence": 0.88,
                },
            ]
        )

        # Unverified patient self-report is blocked by EpistemicJudge
        assert len(cl.core_claims) == 2
        assert len(cl.rejected_claims) == 1
        assert cl.rejected_claims[0]["speaker_role"] == "PATIENT_SELF_REPORT"

        # Querying the updated dosage elects 2.5 mg without contradiction penalty from superseded 5 mg
        ans = cl.ask("¿Cuál es la dosis_warfarina de Paciente_Gomez?")
        assert ans["abstain"] is False
        res = ans["results"][0]
        assert res["value"] == "2.5 mg"
        assert res["contradictions"] == []
        assert res.get("superseded_states") == [{"value": "5 mg", "reason": "superseded_by_newer_state"}]
        assert res["confidence"] >= 0.90

    def test_zero_config_financial_audit_domain_and_unit_isolation(self):
        from claimlayer import clear_canonical_overrides
        clear_canonical_overrides()

        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    "text": "La dirección proyecta un EBITDA ajustado de 50.000.000 € sin auditar.",
                    "entity": "Holding_Iberia",
                    "predicate": "ebitda_ajustado",
                    "value": "50.000.000 €",
                    "canonical_value": 50000000.0,
                    "unit": "EUR",
                    "claim_type": "forecast",
                    "speaker_role": "MANAGEMENT_PROJECTION",
                    "page": 2,
                    "paragraph_id": "p1",
                    "confidence": 0.90,
                },
                {
                    "text": "El informe de auditoría certifica un EBITDA filial norte de 18.000.000 €.",
                    "entity": "Holding_Iberia",
                    "predicate": "ebitda_ajustado",
                    "value": "18.000.000 €",
                    "canonical_value": 18000000.0,
                    "concept_fingerprint": "ebitda_filial_norte",
                    "unit": "EUR",
                    "claim_type": "audit_report",
                    "speaker_role": "AUDITED_STATEMENT",
                    "page": 6,
                    "paragraph_id": "p2",
                    "confidence": 0.96,
                },
                {
                    "text": "El informe de auditoría certifica un EBITDA filial sur de 12.000.000 €.",
                    "entity": "Holding_Iberia",
                    "predicate": "ebitda_ajustado",
                    "value": "12.000.000 €",
                    "canonical_value": 12000000.0,
                    "concept_fingerprint": "ebitda_filial_sur",
                    "unit": "EUR",
                    "claim_type": "audit_report",
                    "speaker_role": "AUDITED_STATEMENT",
                    "page": 7,
                    "paragraph_id": "p3",
                    "confidence": 0.95,
                },
                {
                    "text": "Margen operativo porcentual auditado: 22%.",
                    "entity": "Holding_Iberia",
                    "predicate": "ebitda_ajustado",
                    "value": "22%",
                    "canonical_value": 22.0,
                    "concept_fingerprint": "margen_porcentual",
                    "unit": "%",
                    "claim_type": "audit_report",
                    "speaker_role": "AUDITED_STATEMENT",
                    "page": 8,
                    "paragraph_id": "p4",
                    "confidence": 0.95,
                },
            ]
        )

        # Unaudited MANAGEMENT_PROJECTION (50M) is blocked; 22% PERCENT unit is isolated from EUR sum
        assert len(cl.rejected_claims) == 1
        assert cl.rejected_claims[0]["speaker_role"] == "MANAGEMENT_PROJECTION"

        ans = cl.ask("¿Cuál es la suma total del ebitda_ajustado de Holding_Iberia en euros?")
        assert ans.get("aggregation") is not None
        assert ans["aggregation"]["operation"] == "SUM"
        assert ans["aggregation"]["result"] == 30000000.0

    def test_zero_config_engineering_3hop_telemetry_and_hypothesis_blocking(self):
        from claimlayer import clear_canonical_overrides
        clear_canonical_overrides()

        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    "text": "Servicio_Checkout depende del clúster Cluster_Redis_EU.",
                    "entity": "Servicio_Checkout",
                    "predicate": "depende_de",
                    "value": "Cluster_Redis_EU",
                    "claim_type": "specification",
                    "speaker_role": "VERIFIED_TELEMETRY",
                    "page": 1,
                    "paragraph_id": "p1",
                    "confidence": 0.95,
                },
                {
                    "text": "Cluster_Redis_EU está alojado en Nodo_Baremetal_04.",
                    "entity": "Cluster_Redis_EU",
                    "predicate": "alojado_en",
                    "value": "Nodo_Baremetal_04",
                    "claim_type": "specification",
                    "speaker_role": "VERIFIED_TELEMETRY",
                    "page": 2,
                    "paragraph_id": "p2",
                    "confidence": 0.90,
                },
                {
                    "text": "Confirmado por telemetría: Nodo_Baremetal_04 presenta latencia_p99 de 450 ms.",
                    "entity": "Nodo_Baremetal_04",
                    "predicate": "latencia_p99",
                    "value": "450 ms",
                    "canonical_value": 450.0,
                    "unit": "ms",
                    "claim_type": "telemetry_log",
                    "speaker_role": "VERIFIED_TELEMETRY",
                    "page": 3,
                    "paragraph_id": "p3",
                    "confidence": 0.92,
                },
                {
                    "text": "El usuario reporta sin logs que la caída se debe a un ataque DDoS externo.",
                    "entity": "Servicio_Checkout",
                    "predicate": "causa_incidente",
                    "value": "ataque DDoS",
                    "claim_type": "incident",
                    "speaker_role": "USER_TICKET_REPORT",
                    "page": 4,
                    "paragraph_id": "p4",
                    "confidence": 0.80,
                },
            ]
        )

        assert len(cl.rejected_claims) == 1
        assert cl.rejected_claims[0]["speaker_role"] == "USER_TICKET_REPORT"

        ans = cl.ask("¿Cuál es la latencia_p99 asociada a Servicio_Checkout?")
        assert ans["abstain"] is False
        assert ans.get("multihop") is not None
        assert ans["multihop"]["hops"] == 3
        assert ans["multihop"]["value"] == "450 ms"


# ===========================================================================
# SPRINT 8: Beyond State-of-the-Art (Semirings, JTMS, Allen Intervals, Jøsang, Merkle)
# ===========================================================================


class TestSprint8BeyondSOTAEpistemicFrontier:
    """
    Validates Sprint 8 Beyond-SOTA capabilities:
    1. Bottleneck fixes: non-circular ClaimConsolidator instances, batched SQLite writes & cold-start DB rehydration.
    2. Provenance Semirings K = ([0,1], ⊕, ⊗) & Dijkstra Max-Min path traversal (no weak-path shadowing, parallel path fusion, multihop contradiction detection).
    3. Non-Monotonic Truth Maintenance (JTMS): arbitrary-depth premise DAG closure + cascading retraction of orphan conclusions (Pollock's Undercutting Defeaters).
    4. Allen's Interval Algebra & Point-in-Time (`as_of`) Time-Travel Queries.
    5. Jøsang's Subjective Logic ω = (b, d, u) & Cryptographic Merkle Epistemic Certificates.
    """

    def test_consolidator_deepcopy_no_circular_reference_and_sqlite_rehydration(self, tmp_path):
        import copy
        from core.claim_consolidator import ClaimConsolidator
        from core.claim_extractor import ExtractedClaim

        consolidator = ClaimConsolidator()
        c1 = ExtractedClaim(
            entity="Contrato_Alfa",
            predicate="delito",
            value="estafa",
            quote="Se imputa delito de estafa.",
            page_number=1,
            paragraph_id="p1",
            confidence=0.85,
        )
        c2 = ExtractedClaim(
            entity="Contrato_Alfa",
            predicate="delito",
            value="estafa agravada",
            quote="Se imputa delito de estafa agravada en el mismo párrafo.",
            page_number=1,
            paragraph_id="p1",
            confidence=0.92,
        )
        merged = consolidator.consolidate([c1, c2])
        assert len(merged) == 1
        assert len(merged[0].instances) == 2
        # Verify no circular reference exists when deep-copying
        cloned = copy.deepcopy(merged[0])
        assert cloned.value == "estafa agravada"

        # Verify SQLite batch ingestion & cold-start rehydration
        db_file = tmp_path / "persisted_ledger.db"
        cl1 = ClaimLayer(db_path=db_file, project_id="proj_rehydrate")
        cl1.ingest(
            [
                {
                    "id": "doc1_c1",
                    "filename": "contrato_unico.pdf",
                    "entity": "Grupo_Delta",
                    "predicate": "jurisdiccion",
                    "value": "Madrid",
                    "quote": "La jurisdicción aplicable a Grupo_Delta es Madrid.",
                    "page": 1,
                    "paragraph_id": "p1",
                    "confidence": 0.95,
                },
                {
                    "id": "doc1_c2",
                    "filename": "contrato_unico.pdf",
                    "entity": "Grupo_Delta",
                    "predicate": "moneda_liquidacion",
                    "value": "EUR",
                    "quote": "La moneda de liquidación de Grupo_Delta es EUR.",
                    "page": 2,
                    "paragraph_id": "p2",
                    "confidence": 0.94,
                },
            ]
        )

        # Reopen from disk in a fresh ClaimLayer instance (Cold-Start Rehydration)
        cl2 = ClaimLayer(db_path=db_file, project_id="proj_rehydrate")
        assert len(cl2.core_claims) == 2
        res_jur = cl2.ask("¿Cuál es la jurisdiccion de Grupo_Delta?")
        assert res_jur["results"][0]["value"] == "Madrid"
        res_mon = cl2.ask("¿Cuál es la moneda_liquidacion de Grupo_Delta?")
        assert res_mon["results"][0]["value"] == "EUR"

    def test_provenance_semiring_dijkstra_no_shadowing_parallel_fusion_and_contradictions(self):
        from core.graph_traverser import DependencyGraph
        from core.interfaces import Claim, Reason, SourceRef

        # 1. Weak 1-hop path (A -> B, heuristic weight 0.10) must NOT shadow stronger 2-hop deductive path (A -> D -> B)
        claims_shadow = [
            Claim(
                id="weak_ab",
                entity="Holding_A",
                predicate="controla",
                value="Operadora_B",
                source=SourceRef("rumor.txt", 1, "p1"),
                confidence=0.50,
                inference_type="heuristic",  # weight 0.10 -> score 0.05
            ),
            Claim(
                id="strong_ad",
                entity="Holding_A",
                predicate="matriz_de",
                value="Filial_D",
                source=SourceRef("escritura.pdf", 1, "p1"),
                confidence=0.95,
                inference_type="deductive",  # weight 1.0 -> score 0.95
            ),
            Claim(
                id="strong_db",
                entity="Filial_D",
                predicate="propietaria_de",
                value="Operadora_B",
                source=SourceRef("escritura.pdf", 2, "p2"),
                confidence=0.95,
                inference_type="deductive",  # weight 1.0 -> score 0.95
            ),
            Claim(
                id="target_b",
                entity="Operadora_B",
                predicate="beneficiario_final",
                value="Fondo_Soberano_X",
                source=SourceRef("registro.pdf", 3, "p3"),
                confidence=0.95,
                inference_type="deductive",
            ),
        ]
        graph = DependencyGraph(claims_shadow)
        paths = graph.find_paths("Holding_A", "beneficiario_final", max_hops=3)
        assert len(paths) >= 2
        # Best path is the 3-step deductive path (Holding_A -> Filial_D -> Operadora_B -> Fondo_Soberano_X)
        # with confidence 0.95 * (0.95^2) = 0.8574, NOT the weak 2-step heuristic path (0.0475)!
        assert paths[0].confidence == pytest.approx(0.95 * (0.95 ** 2), rel=1e-3)
        assert len(paths[0].steps) == 3

        # 2. Parallel independent paths (⊕ Noisy-OR fusion) vs competing path (multihop contradiction)
        claims_semiring = [
            # Path 1: Alpha -> Via_1 -> Valor_Verdadero (conf ~ 0.90 * 0.95 = 0.855)
            Claim(
                id="p1_a",
                entity="Alpha_Corp",
                predicate="participa_en",
                value="Vehiculo_1",
                source=SourceRef("doc_a.pdf", 1, "p1"),
                confidence=0.90,
                inference_type="deductive",
            ),
            Claim(
                id="p1_b",
                entity="Vehiculo_1",
                predicate="jurisdiccion_fiscal",
                value="Luxemburgo",
                source=SourceRef("doc_a.pdf", 2, "p2"),
                confidence=0.90,
                inference_type="deductive",
            ),
            # Path 2 (independent): Alpha -> Via_2 -> Luxemburgo (conf ~ 0.80 * 0.95 = 0.76)
            Claim(
                id="p2_a",
                entity="Alpha_Corp",
                predicate="consolida_con",
                value="Vehiculo_2",
                source=SourceRef("doc_b.pdf", 1, "p1"),
                confidence=0.80,
                inference_type="deductive",
            ),
            Claim(
                id="p2_b",
                entity="Vehiculo_2",
                predicate="jurisdiccion_fiscal",
                value="Luxemburgo",
                source=SourceRef("doc_b.pdf", 2, "p2"),
                confidence=0.80,
                inference_type="deductive",
            ),
            # Competing Path 3: Alpha -> Via_3 -> Islas_Caiman (weak inductive path)
            Claim(
                id="p3_a",
                entity="Alpha_Corp",
                predicate="vinculada_a",
                value="Vehiculo_3",
                source=SourceRef("nota.pdf", 1, "p1"),
                confidence=0.50,
                inference_type="inductive",  # weight 0.55 -> 0.275
            ),
            Claim(
                id="p3_b",
                entity="Vehiculo_3",
                predicate="jurisdiccion_fiscal",
                value="Islas_Caiman",
                source=SourceRef("nota.pdf", 2, "p2"),
                confidence=0.50,
                inference_type="inductive",
            ),
        ]
        g2 = DependencyGraph(claims_semiring)
        det = g2.resolve_multihop_detailed("Alpha_Corp", "jurisdiccion_fiscal")
        assert det is not None
        res_mh = det["result"]
        assert res_mh.value == "Luxemburgo"
        assert res_mh.reason == Reason.CONTRADICTION
        # Fused support of the 2 independent Luxemburgo paths exceeds single path (0.855)
        assert det["winner_group"]["independent_path_count"] == 2
        assert det["winner_group"]["fused_support"] > 0.855
        # Losing path claims are surfaced in contradictions
        assert len(res_mh.contradictions) == 2
        assert res_mh.verify_certificate() is True

    def test_jtms_transitive_premise_dag_and_cascading_undercutting_retraction(self):
        from datetime import datetime, timezone
        from core.epistemic_judge import EpistemicJudge
        from core.inference_engine import resolve_claims_detailed
        from core.interfaces import Claim, Reason, SourceRef

        # 1. Depth-3 Premise DAG evaluated in reverse order [C3, P2, P1]
        p1 = Claim(
            id="p1",
            entity="Acusado_Z",
            predicate="coartada",
            value="estaba fuera del país",
            source=SourceRef("escrito_defensa.pdf", 1, "p1"),
            confidence=0.95,
            inference_type="deductive",
            speaker_role="PARTY_ALLEGATION",
            quote="La defensa sostiene que el acusado estaba fuera del país.",
        )
        p2 = Claim(
            id="p2",
            entity="Acusado_Z",
            predicate="ausencia_lugar_hechos",
            value="verificada",
            source=SourceRef("informe.pdf", 2, "p2"),
            confidence=0.95,
            inference_type="deductive",
            premises=["p1"],
            quote="Por consiguiente, no se encontraba en el lugar.",
        )
        c3 = Claim(
            id="c3",
            entity="Acusado_Z",
            predicate="responsabilidad_penal",
            value="exento",
            source=SourceRef("conclusion.pdf", 3, "p3"),
            confidence=0.95,
            inference_type="deductive",
            premises=["p2"],
            quote="Queda exento de responsabilidad penal.",
        )

        judge = EpistemicJudge()
        # Pass in reverse order [c3, p2, p1] to prove order-independent fixed-point DAG closure
        sanitized, trace = judge.audit_and_sanitize_claims([c3, p2, p1])
        assert c3.inference_type == "abductive"
        assert p2.inference_type == "abductive"
        assert p1.inference_type == "abductive"

        # 2. JTMS Cascading Retraction when root premise expires (Pollock's Undercutting Defeater)
        cert_premise = Claim(
            id="cert_iso",
            entity="Proveedor_Cloud",
            predicate="estado_cumplimiento",
            value="apto_produccion",
            source=SourceRef("certificado_iso.pdf", 1, "p1"),
            confidence=0.98,
            inference_type="deductive",
            valid_from="2023-01-01",
            valid_until="2024-12-31",  # Expired at eval_time=2026-06-01
        )
        derived_authorization = Claim(
            id="auth_derived",
            entity="Proveedor_Cloud",
            predicate="estado_cumplimiento",
            value="apto_produccion",
            source=SourceRef("dictamen_interno.pdf", 2, "p4"),
            confidence=0.95,
            inference_type="deductive",
            premises=["cert_iso"],  # Depends on expired cert_iso!
            valid_from=None,
            valid_until=None,
        )

        out = resolve_claims_detailed(
            [cert_premise, derived_authorization],
            now=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        # Because cert_iso expired, derived_authorization is automatically undercut and retracted!
        assert out["result"].reason == Reason.STALE_EVIDENCE
        assert out["result"].value is None
        inactive_reasons = {item["claim_id"]: item["reason"] for item in out["trace"]["inactive_claims"]}
        assert inactive_reasons["cert_iso"] == "expired"
        assert inactive_reasons["auth_derived"] == "undercut_by_inactive_premise"

    def test_allen_interval_algebra_and_point_in_time_as_of_queries(self):
        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    "id": "tramo_2023",
                    "filename": "contrato_sindicado.pdf",
                    "entity": "Prestamo_Sindicado",
                    "predicate": "tipo_interes",
                    "value": "3.5%",
                    "quote": "Durante el ejercicio 2023 el tipo de interés de Prestamo_Sindicado es 3.5%.",
                    "valid_from": "2023-01-01",
                    "valid_until": "2023-12-31",
                    "page": 4,
                    "paragraph_id": "p1",
                    "confidence": 0.96,
                },
                {
                    "id": "tramo_2024_onwards",
                    "filename": "contrato_sindicado.pdf",
                    "entity": "Prestamo_Sindicado",
                    "predicate": "tipo_interes",
                    "value": "5.25%",
                    "quote": "A partir de 2024 el tipo de interés de Prestamo_Sindicado es 5.25%.",
                    "valid_from": "2024-01-01",
                    "valid_until": "2028-12-31",
                    "page": 5,
                    "paragraph_id": "p2",
                    "confidence": 0.96,
                },
            ]
        )

        # 1. Current query: Allen's Interval Algebra recognizes [2023-01-01, 2023-12-31] strictly
        # precedes [2024-01-01, 2028-12-31] (disjoint intervals -> 0 contradictions, high confidence)
        now_ans = cl.ask("¿Cuál es el tipo_interes de Prestamo_Sindicado?")
        assert now_ans["results"][0]["value"] == "5.25%"
        assert now_ans["results"][0]["contradictions"] == []
        assert now_ans["results"][0]["confidence"] >= 0.95

        # 2. Natural-language Point-in-Time (`as_of`) Time-Travel Query for June 2023
        hist_ans = cl.ask("¿Cuál era el tipo_interes de Prestamo_Sindicado en junio de 2023?")
        assert hist_ans["results"][0]["value"] == "3.5%"
        assert hist_ans["results"][0]["contradictions"] == []
        assert hist_ans.get("as_of", "").startswith("2023-06-15")

    def test_josang_subjective_logic_and_merkle_cryptographic_verification(self):
        from core.epistemic_certificate import compute_subjective_opinion

        # 1. Compare Weak Evidence (W=0.50, L=0.0) vs Hard Conflict (W=0.90, L=0.90)
        op_weak = compute_subjective_opinion(0.50, 0.0)
        op_conflict = compute_subjective_opinion(0.90, 0.90)

        # Both have similar scalar expectation (~0.50), but completely opposite epistemic structures!
        assert op_weak.belief == pytest.approx(0.50)
        assert op_weak.disbelief == pytest.approx(0.00)
        assert op_weak.uncertainty == pytest.approx(0.50)

        assert op_conflict.belief == pytest.approx(0.495)
        assert op_conflict.disbelief == pytest.approx(0.495)
        assert op_conflict.uncertainty == pytest.approx(0.01)
        assert op_conflict.epistemic_regime == "HIGH_CONFLICT"

        # 2. Cryptographic Merkle Certificate Verification & Tamper Detection
        cl = ClaimLayer()
        cl.ingest(
            [
                {
                    "id": "m1",
                    "filename": "auditoria_forense.pdf",
                    "entity": "Banco_Meridional",
                    "predicate": "ratio_cet1",
                    "value": "13.4%",
                    "quote": "El informe de auditoría certifica un ratio CET1 de 13.4%.",
                    "speaker_role": "AUDITED_STATEMENT",
                    "page": 10,
                    "paragraph_id": "p3",
                    "confidence": 0.95,
                }
            ]
        )
        response = cl.ask("¿Cuál es el ratio_cet1 de Banco_Meridional?")
        assert cl.verify_response_integrity(response) is True

        # Tamper with the value in the response -> cryptographic verification immediately fails!
        response["results"][0]["value"] = "18.9%"
        assert cl.verify_response_integrity(response) is False

    def test_inapelable_sota_vs_deltoryx_master_showcase(self):
        """
        Master E2E Showcase ("Operación Cronos — Due Diligence de Grupo_Vertice"):
        Executes all 6 frontier traps where current SOTA RAG/GraphRAG/Agents fail,
        proving deterministic, mathematically verifiable resolution in Deltoryx v2.0.
        """
        from claimlayer import clear_canonical_overrides
        clear_canonical_overrides()

        cl = ClaimLayer(project_id="operacion_cronos")
        cl.ingest(
            [
                # Trap 1: Unaudited Management Projection (should be blocked by EpistemicJudge)
                {
                    "id": "mgmt_1",
                    "filename": "nota_prensa_gerencia.pdf",
                    "entity": "Grupo_Vertice",
                    "predicate": "contingencia_firme",
                    "value": "0 €",
                    "quote": "La dirección proyecta una contingencia firme de 0 € sin auditar.",
                    "speaker_role": "MANAGEMENT_PROJECTION",
                    "origin_tier": "EXTERNAL_INJECTED",
                    "page": 1,
                    "paragraph_id": "p1",
                    "confidence": 0.99,
                },
                # Trap 2: Expired Premise + Orphan Derived Conclusion (JTMS Undercutting Defeater)
                {
                    "id": "cert_2022",
                    "filename": "certificado_regulatorio.pdf",
                    "entity": "Grupo_Vertice",
                    "predicate": "certificado_base",
                    "value": "vigente",
                    "quote": "Certificado regulatorio válido desde 2022 hasta fin de 2024.",
                    "valid_from": "2022-01-01",
                    "valid_until": "2024-12-31",  # Expired!
                    "page": 2,
                    "paragraph_id": "p1",
                    "confidence": 0.98,
                },
                {
                    "id": "dictamen_exencion",
                    "filename": "dictamen_juridico.pdf",
                    "entity": "Grupo_Vertice",
                    "predicate": "exencion_regulatoria",
                    "value": "activa",
                    "quote": "En virtud del certificado base, la exención regulatoria de Grupo_Vertice está activa.",
                    "premises": ["cert_2022"],  # Depends on expired cert_2022!
                    "page": 3,
                    "paragraph_id": "p2",
                    "confidence": 0.95,
                },
                # Trap 3: Allen's Interval Algebra & Time-Travel (`as_of`)
                {
                    "id": "margen_2023",
                    "filename": "contrato_sindicado.pdf",
                    "entity": "Grupo_Vertice",
                    "predicate": "margen_financiero",
                    "value": "2.10%",
                    "quote": "Durante 2023 el margen financiero de Grupo_Vertice se fija en 2.10%.",
                    "valid_from": "2023-01-01",
                    "valid_until": "2023-12-31",
                    "page": 10,
                    "paragraph_id": "p1",
                    "confidence": 0.96,
                },
                {
                    "id": "margen_2024_2028",
                    "filename": "contrato_sindicado.pdf",
                    "entity": "Grupo_Vertice",
                    "predicate": "margen_financiero",
                    "value": "4.75%",
                    "quote": "Desde enero de 2024 hasta 2028 el margen financiero de Grupo_Vertice es 4.75%.",
                    "valid_from": "2024-01-01",
                    "valid_until": "2028-12-31",
                    "page": 11,
                    "paragraph_id": "p2",
                    "confidence": 0.96,
                },
                # Trap 4: Multi-hop Provenance Semiring (2 corroborating paths to Fondo_Soberano_Nordico)
                {
                    "id": "mh_1a",
                    "filename": "escritura_mercantil.pdf",
                    "entity": "Grupo_Vertice",
                    "predicate": "controlado_por",
                    "value": "Holding_Lux",
                    "quote": "Grupo_Vertice está controlado por Holding_Lux.",
                    "page": 14,
                    "paragraph_id": "p1",
                    "confidence": 0.95,
                },
                {
                    "id": "mh_1b",
                    "filename": "escritura_mercantil.pdf",
                    "entity": "Holding_Lux",
                    "predicate": "titular_real",
                    "value": "Fondo_Soberano_Nordico",
                    "quote": "El titular real de Holding_Lux es Fondo_Soberano_Nordico.",
                    "page": 15,
                    "paragraph_id": "p2",
                    "confidence": 0.95,
                },
                {
                    "id": "mh_2a",
                    "filename": "registro_internacional.pdf",
                    "entity": "Grupo_Vertice",
                    "predicate": "filial_directa_de",
                    "value": "Vehiculo_Suizo",
                    "quote": "Grupo_Vertice es filial directa de Vehiculo_Suizo.",
                    "page": 4,
                    "paragraph_id": "p1",
                    "confidence": 0.90,
                },
                {
                    "id": "mh_2b",
                    "filename": "registro_internacional.pdf",
                    "entity": "Vehiculo_Suizo",
                    "predicate": "titular_real",
                    "value": "Fondo_Soberano_Nordico",
                    "quote": "El titular real de Vehiculo_Suizo es Fondo_Soberano_Nordico.",
                    "page": 5,
                    "paragraph_id": "p2",
                    "confidence": 0.90,
                },
                # Trap 5: Periodic Tranches + Written Multilingual Number + Reiteration + Unit Isolation
                {
                    "id": "deuda_q1",
                    "filename": "informe_auditoria.pdf",
                    "entity": "Grupo_Vertice",
                    "predicate": "contingencia_firme",
                    "value": "1.200.000 €",
                    "canonical_value": 1200000.0,
                    "concept_fingerprint": "tramo_q1_2025",
                    "unit": "EUR",
                    "quote": "Certificado por el auditor: contingencia firme Q1 por 1.200.000 €.",
                    "speaker_role": "AUDITED_STATEMENT",
                    "page": 20,
                    "paragraph_id": "p1",
                    "confidence": 0.96,
                },
                {
                    "id": "deuda_q2",
                    "filename": "informe_auditoria.pdf",
                    "entity": "Grupo_Vertice",
                    "predicate": "contingencia_firme",
                    "value": "1.200.000 €",
                    "canonical_value": 1200000.0,
                    "concept_fingerprint": "tramo_q2_2025",
                    "unit": "EUR",
                    "quote": "Certificado por el auditor: contingencia firme Q2 por 1.200.000 €.",
                    "speaker_role": "AUDITED_STATEMENT",
                    "page": 21,
                    "paragraph_id": "p2",
                    "confidence": 0.96,
                },
                {
                    "id": "deuda_q3_texto",
                    "filename": "informe_auditoria.pdf",
                    "entity": "Grupo_Vertice",
                    "predicate": "contingencia_firme",
                    "value": "seiscientos mil euros",
                    "canonical_value": 600000.0,
                    "concept_fingerprint": "tramo_q3_2025",
                    "unit": "EUR",
                    "quote": "Certificado por el auditor: contingencia firme Q3 por seiscientos mil euros.",
                    "speaker_role": "AUDITED_STATEMENT",
                    "page": 22,
                    "paragraph_id": "p3",
                    "confidence": 0.95,
                },
                {
                    "id": "deuda_q1_reiteracion",
                    "filename": "informe_auditoria.pdf",
                    "entity": "Grupo_Vertice",
                    "predicate": "contingencia_firme",
                    "value": "1.200.000 €",
                    "canonical_value": 1200000.0,
                    "concept_fingerprint": "tramo_q1_2025",  # Same concept as Q1 -> deduplicated!
                    "unit": "EUR",
                    "quote": "En conclusiones se reitera la contingencia firme Q1 de 1.200.000 €.",
                    "speaker_role": "AUDITED_STATEMENT",
                    "page": 45,
                    "paragraph_id": "p9",
                    "confidence": 0.96,
                },
                {
                    "id": "ratio_porcentual",
                    "filename": "informe_auditoria.pdf",
                    "entity": "Grupo_Vertice",
                    "predicate": "contingencia_firme",
                    "value": "15%",
                    "canonical_value": 15.0,
                    "concept_fingerprint": "ratio_sobre_patrimonio",
                    "unit": "%",  # Incompatible unit -> isolated from EUR sum!
                    "quote": "Representa un 15% sobre el patrimonio neto.",
                    "speaker_role": "AUDITED_STATEMENT",
                    "page": 46,
                    "paragraph_id": "p10",
                    "confidence": 0.95,
                },
            ]
        )

        # Verification 1: Unaudited MANAGEMENT_PROJECTION was blocked at ingestion
        assert len(cl.rejected_claims) == 1
        assert cl.rejected_claims[0]["id"] == "mgmt_1"

        # Verification 2: JTMS Undercutting Defeater retracted `dictamen_exencion` because `cert_2022` expired
        ans_exencion = cl.ask("¿Cuál es la exencion_regulatoria de Grupo_Vertice?")
        assert ans_exencion["abstain"] is True
        assert any(
            rc["claim_id"] == "dictamen_exencion" and rc["reason"] == "undercut_by_retracted_premise"
            for rc in ans_exencion.get("retracted_conclusions", [])
        )

        # Verification 3: Allen's Interval Algebra resolves current margin (4.75%) with 0 contradictions,
        # and Time-Travel (`as_of`) resolves June 2023 margin (2.10%)
        ans_margen_hoy = cl.ask("¿Cuál es el margen_financiero de Grupo_Vertice?")
        assert ans_margen_hoy["results"][0]["value"] == "4.75%"
        assert ans_margen_hoy["results"][0]["contradictions"] == []
        assert cl.verify_response_integrity(ans_margen_hoy) is True

        ans_margen_2023 = cl.ask("¿Cuál era el margen_financiero de Grupo_Vertice en junio de 2023?")
        assert ans_margen_2023["results"][0]["value"] == "2.10%"
        assert ans_margen_2023["results"][0]["contradictions"] == []

        # Verification 4: Multi-hop Semiring fuses both independent paths to Fondo_Soberano_Nordico
        ans_ubo = cl.ask("¿Quién es el titular_real de Grupo_Vertice?")
        assert ans_ubo["multihop"]["value"] == "Fondo_Soberano_Nordico"
        assert ans_ubo["multihop"]["confidence"] > 0.90  # Reinforced by parallel path fusion (⊕)
        assert cl.verify_response_integrity(ans_ubo) is True

        # Verification 5: Exact EUR SUM (1.2M Q1 + 1.2M Q2 + 600k Q3 = 3,000,000 €), excluding Q1 reiteration and 15%
        ans_sum = cl.ask("¿A cuánto asciende la suma total de la contingencia_firme de Grupo_Vertice en euros?")
        assert ans_sum["aggregation"]["operation"] == "SUM"
        assert ans_sum["aggregation"]["result"] == 3000000.0
        assert cl.verify_response_integrity(ans_sum) is True


class TestSprint9RevisedPaperPropositionsAndWorkedExamples:
    """
    Formal verification of Propositions 1-5 and Appendix A worked examples
    from the revised paper (19 October 2026):
      'Evidence Intelligence for Auditable Reasoning over Structured Evidence —
       A revised architecture with conditional guarantees and an empirical reassessment'
    """

    def test_paper_appendix_a_support_opposition_and_qg(self):
        """
        Appendix A (Support and opposition) & Proposition 3:
        - Two independent origin groups with assessed support 0.8 and 0.7 give
          S = 1 - (1 - 0.8)(1 - 0.7) = 0.94.
        - Opposing support of 0.6 gives Q = 0.94^2 / (0.94 + 0.6) ≈ 0.573766.
        - If the two positive records instead belong to one dependence group,
          S = 0.8 and Q = 0.8^2 / (0.8 + 0.6) ≈ 0.457143.
        - Repeating the 0.8 record within that group does not increase either value.
        """
        from core.inference_engine import (
            compute_bounded_conflict_index,
            resolve_claims_detailed,
        )
        from core.interfaces import Claim, SourceRef

        # Case 1: Two independent origin groups (0.8 and 0.7) vs opposing (0.6)
        c1 = Claim(
            id="u1", entity="Obligacion", predicate="deadline", value="30 days",
            source=SourceRef("doc_A.pdf", 1, "p1"), confidence=0.8,
            dependence_group="origin_1",
        )
        c2 = Claim(
            id="u2", entity="Obligacion", predicate="deadline", value="30 days",
            source=SourceRef("doc_B.pdf", 2, "p1"), confidence=0.7,
            dependence_group="origin_2",
        )
        c_opp = Claim(
            id="u3", entity="Obligacion", predicate="deadline", value="60 days",
            source=SourceRef("doc_C.pdf", 3, "p1"), confidence=0.6,
            dependence_group="origin_opp",
        )
        res_indep = resolve_claims_detailed([c1, c2, c_opp], penalty_strategy="paper_qg")
        assert abs(res_indep["trace"]["Sg"] - 0.94) < 1e-6
        assert abs(res_indep["trace"]["Og"] - 0.60) < 1e-6
        assert abs(res_indep["trace"]["Qg"] - 0.573766) < 1e-5
        assert abs(res_indep["result"].confidence - 0.573766) < 1e-5

        # Case 2: Both positive records belong to ONE dependence group ("shared_origin"), plus a repeated 0.8 record
        c1_dep = Claim(
            id="u1_d", entity="Obligacion", predicate="deadline", value="30 days",
            source=SourceRef("doc_A1.pdf", 1, "p1"), confidence=0.8,
            dependence_group="shared_origin",
        )
        c2_dep = Claim(
            id="u2_d", entity="Obligacion", predicate="deadline", value="30 days",
            source=SourceRef("doc_A2.pdf", 2, "p1"), confidence=0.7,
            dependence_group="shared_origin",
        )
        c3_repeat = Claim(
            id="u3_rep", entity="Obligacion", predicate="deadline", value="30 days",
            source=SourceRef("doc_A3.pdf", 4, "p2"), confidence=0.8,
            dependence_group="shared_origin",
        )
        res_dep = resolve_claims_detailed([c1_dep, c2_dep, c3_repeat, c_opp], penalty_strategy="paper_qg")
        assert abs(res_dep["trace"]["Sg"] - 0.80) < 1e-6
        assert abs(res_dep["trace"]["Og"] - 0.60) < 1e-6
        assert abs(res_dep["trace"]["Qg"] - 0.457143) < 1e-5
        assert compute_bounded_conflict_index(1.0, 1.0) == 0.5

    def test_paper_appendix_a_three_valued_conflict_semantics(self):
        """
        Appendix A (Context and conflict) & Section 4.2 (Proposition 2):
        - Two concurrent positive assertions of different payment deadlines conflict ('incompatible')
          under a functional deadline predicate.
        - Different deadlines in disjoint effective periods describe change ('compatible').
        - Two offices under a multivalued location predicate are 'compatible'.
        - A missing effective date that could alter the comparison yields 'unknown'.
        - A claimant's allegation and an unqualified factual finding yield 'unknown'.
        - Catch-all predicate 'general' yields 'unknown'.
        """
        from core.inference_engine import compare_claims_three_valued
        from core.interfaces import Claim, SourceRef

        # 1. Functional deadline conflict
        d1 = Claim("d1", "Contrato_A", "deadline", "30 days", SourceRef("doc.pdf", 1, "p1"), 0.9)
        d2 = Claim("d2", "Contrato_A", "deadline", "60 days", SourceRef("doc.pdf", 2, "p2"), 0.9)
        assert compare_claims_three_valued(d1, d2) == "incompatible"

        # 2. Disjoint effective periods -> compatible (change over time)
        t1 = Claim(
            "t1", "Contrato_A", "deadline", "30 days", SourceRef("doc.pdf", 1, "p1"), 0.9,
            valid_from="2023-01-01", valid_until="2023-12-31",
        )
        t2 = Claim(
            "t2", "Contrato_A", "deadline", "60 days", SourceRef("doc.pdf", 2, "p2"), 0.9,
            valid_from="2024-01-01",
        )
        assert compare_claims_three_valued(t1, t2) == "compatible"

        # 3. Multivalued location predicate -> compatible
        loc1 = Claim("l1", "ACME", "location", "Madrid", SourceRef("doc.pdf", 1, "p1"), 0.9)
        loc2 = Claim("l2", "ACME", "location", "Barcelona", SourceRef("doc.pdf", 1, "p2"), 0.9)
        assert compare_claims_three_valued(loc1, loc2) == "compatible"

        # 4. Missing effective date on one side while the other has a bounded interval -> unknown
        assert compare_claims_three_valued(t1, d2) == "unknown"

        # 5. Claimant's allegation vs factual finding -> unknown
        alleg = Claim(
            "a1", "ACME", "debt_status", "unpaid", SourceRef("doc.pdf", 3, "p1"), 0.9,
            speaker_role="PARTY_ALLEGATION",
        )
        finding = Claim(
            "f1", "ACME", "debt_status", "paid", SourceRef("doc.pdf", 5, "p2"), 0.9,
            speaker_role="COURT_FINDING",
        )
        assert compare_claims_three_valued(alleg, finding) == "unknown"

        # 6. Catch-all predicate 'general' -> unknown
        g1 = Claim("g1", "ACME", "general", "valor A", SourceRef("doc.pdf", 1, "p1"), 0.9)
        g2 = Claim("g2", "ACME", "general", "valor B", SourceRef("doc.pdf", 2, "p2"), 0.9)
        assert compare_claims_three_valued(g1, g2) == "unknown"

    def test_paper_appendix_a_event_aggregation_and_null_non_equivalence(self):
        """
        Appendix A (Aggregation) & Section 7 (Proposition 5):
        - Event keys (contract A, issuer X, invoice 101) and (contract A, issuer X, invoice 102)
          remain distinct even if both amounts equal EUR 25,000 -> SUM = 50,000.
        - A second mention of invoice 101 does not add an event -> SUM remains 50,000.
        - A second, incompatible amount for invoice 101 creates a disputed value for that event.
        - A blank invoice field does not establish equivalence with another blank field
          (events_equivalent(blank1, blank2) is False), and strict_event_identity=True abstains.
        - Decimal arithmetic avoids binary floating-point rounding drift (0.1 + 0.2 == 0.3).
        """
        from core.aggregation_engine import (
            AggregationEngine,
            AggregationIntent,
            AggregationType,
            events_equivalent,
        )
        from core.interfaces import Claim, Reason, SourceRef

        inv_101_a = Claim(
            "i1", "Contract_A", "amount", "25.000 €", SourceRef("doc1.pdf", 1, "p1"), 0.95,
            concept_fingerprint="contract_A:issuer_X:invoice_101", unit="EUR",
        )
        inv_102 = Claim(
            "i2", "Contract_A", "amount", "25.000 €", SourceRef("doc1.pdf", 2, "p2"), 0.95,
            concept_fingerprint="contract_A:issuer_X:invoice_102", unit="EUR",
        )
        inv_101_dup = Claim(
            "i3", "Contract_A", "amount", "25.000 €", SourceRef("doc2.pdf", 5, "p1"), 0.90,
            concept_fingerprint="contract_A:issuer_X:invoice_101", unit="EUR",
        )
        inv_101_disputed = Claim(
            "i4", "Contract_A", "amount", "40.000 €", SourceRef("doc2.pdf", 6, "p3"), 0.70,
            concept_fingerprint="contract_A:issuer_X:invoice_101", unit="EUR",
        )

        assert events_equivalent(inv_101_a, inv_101_dup) is True
        assert events_equivalent(inv_101_a, inv_102) is False

        eng = AggregationEngine()
        intent_sum = AggregationIntent(agg_type=AggregationType.SUM, raw_query="Suma total en euros")
        res = eng.aggregate([inv_101_a, inv_102, inv_101_dup, inv_101_disputed], intent_sum)
        assert res.value == 50000.0
        assert "i4" in res.metadata.get("disputed_events", [])
        assert any(c.id == "i4" for c in res.contradictions)

        # Blank event identity fields (iota(u) = None) do NOT establish equivalence
        blank_1 = Claim("b1", "Contract_A", "amount", "25.000 €", SourceRef("doc1.pdf", 1, "p1"), 0.9)
        blank_2 = Claim("b2", "Contract_A", "amount", "25.000 €", SourceRef("doc1.pdf", 3, "p4"), 0.9)
        assert events_equivalent(blank_1, blank_2) is False

        # Under strict_event_identity=True, two unresolved blank records abstain
        res_strict = eng.aggregate([blank_1, blank_2], intent_sum, strict_event_identity=True)
        assert res_strict.value is None
        assert res_strict.reason == Reason.NO_EVIDENCE_FOUND
        assert res_strict.metadata.get("status") == "unresolved_event_identity"

        # Exact Decimal arithmetic: 0.1 + 0.2 == 0.3
        d1 = Claim("d1", "TestDec", "amount", 0.1, SourceRef("doc.pdf", 1, "p1"), 0.9, concept_fingerprint="item:1")
        d2 = Claim("d2", "TestDec", "amount", 0.2, SourceRef("doc.pdf", 1, "p2"), 0.9, concept_fingerprint="item:2")
        res_dec = eng.aggregate([d1, d2], intent_sum)
        assert res_dec.value == 0.3

    def test_paper_appendix_a_checked_derivation_and_cycle_rejection(self):
        """
        Appendix A (Derivation) & Section 6.1 (Proposition 4):
        - A conclusion with an unknown premise identifier is 'unverified'.
        - A cycle cannot justify itself ('unverified', 'Cyclic justification detected in premise DAG').
        - A valid proof involving attributed allegations retains those attribution conditions ('unverified').
        - A valid acyclic derivation over verified leaves has status 'rule_derived'.
        """
        from core.epistemic_judge import EpistemicJudge
        from core.interfaces import Claim, SourceRef

        judge = EpistemicJudge()
        leaf = Claim("leaf_1", "ACME", "status", "active", SourceRef("doc.pdf", 1, "p1"), 0.95, quote="Hecho Probado: ACME está activa.")

        # 1. Valid source-supported leaf
        a_leaf = judge.audit_claim(leaf)
        assert a_leaf.derivation_status == "source_supported"

        # 2. Valid rule-derived conclusion
        derived_ok = Claim(
            "der_1", "ACME", "capacity", "eligible", SourceRef("doc.pdf", 2, "p1"), 0.95,
            premises=["leaf_1"], quote="Por tanto ACME es elegible.",
        )
        a_der = judge.audit_claim(derived_ok, verified_premise_ids={"leaf_1"}, premise_lookup={"leaf_1": leaf})
        assert a_der.derivation_status == "rule_derived"
        assert a_der.is_overridden is False

        # 3. Unknown premise identifier -> unverified
        derived_missing = Claim(
            "der_miss", "ACME", "capacity", "eligible", SourceRef("doc.pdf", 2, "p1"), 0.95,
            premises=["unknown_premise_99"],
        )
        a_miss = judge.audit_claim(derived_missing, verified_premise_ids={"leaf_1"})
        assert a_miss.derivation_status == "unverified"
        assert a_miss.is_overridden is True

        # 4. Cyclic justification (cyc_1 -> cyc_2 -> cyc_1) -> unverified
        cyc_1 = Claim("cyc_1", "ACME", "p", "v1", SourceRef("doc.pdf", 1, "p1"), 0.9, premises=["cyc_2"])
        cyc_2 = Claim("cyc_2", "ACME", "p", "v2", SourceRef("doc.pdf", 1, "p2"), 0.9, premises=["cyc_1"])
        a_cyc = judge.audit_claim(cyc_1, verified_premise_ids={"cyc_1", "cyc_2"}, premise_lookup={"cyc_1": cyc_1, "cyc_2": cyc_2})
        assert a_cyc.derivation_status == "unverified"
        assert a_cyc.is_overridden is True
        assert "Cyclic justification" in (a_cyc.override_reason or "")

    def test_paper_section_5_1_tripartite_quality_vector(self):
        """
        Section 5.1:
        kappa_i = (kappa_span, kappa_struct, kappa_app), a_i = min{kappa_span, kappa_struct, kappa_app}.
        """
        from core.claim_adapter import decompose_confidence
        from core.interfaces import Claim, SourceRef

        c_good = Claim(
            "c_good", "ACME", "payment_deadline", "30 days",
            SourceRef("contract.pdf", 1, "p1"), 0.92,
            quote="ACME payment deadline is 30 days.",
            origin_tier="PRIMARY_DOCUMENT",
        )
        dec_good = decompose_confidence(c_good)
        assert dec_good["kappa_span"] == 0.92
        assert dec_good["kappa_struct"] == 1.0
        assert dec_good["kappa_app"] == 1.0
        assert dec_good["composite_support_index"] == 0.92

        c_generic_ext = Claim(
            "c_gen", "ACME", "general", "some note",
            SourceRef("note.txt", 1, "p1"), 0.90,
            quote="some note",
            origin_tier="EXTERNAL_INJECTED",
        )
        dec_gen = decompose_confidence(c_generic_ext)
        assert dec_gen["kappa_struct"] == 0.65
        assert dec_gen["kappa_app"] == 0.50
        assert dec_gen["composite_support_index"] == 0.50



