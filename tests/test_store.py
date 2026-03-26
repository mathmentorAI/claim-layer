from pathlib import Path

from claim_layer import ClaimLayerStore, IngestedDocument


def test_ingest_and_query(tmp_path: Path):
    store = ClaimLayerStore(tmp_path / "evidence.db")

    payload = IngestedDocument(
        project_id="demo",
        filename="contract_a.pdf",
        entities=[
            {"entity_id": "acme", "name": "Acme Corp", "entity_type": "organization"},
        ],
        claims=[
            {
                "claim_id": "c1",
                "text": "Acme Corp agrees to pay $50,000.",
                "confidence": 0.9,
                "page": 3,
                "paragraph_id": "0002",
            }
        ],
        facts=[
            {
                "claim_ref": "c1",
                "entity_ref": "acme",
                "fact_type": "payment_amount",
                "value": "$50,000",
                "sources": [{"page": 3, "paragraph_id": "0002", "text": "Acme Corp agrees to pay $50,000."}],
            }
        ],
    )

    counts = store.ingest_document(payload)

    assert counts == {"documents": 1, "entities": 1, "claims": 1, "facts": 1}
    result = store.query_evidence("demo", "Acme Corp", "payment_amount")
    assert result["candidate_values"][0]["value"] == "$50,000"
    assert result["aggregate_confidence"] == 0.9


def test_detects_contradictions(tmp_path: Path):
    store = ClaimLayerStore(tmp_path / "evidence.db")
    payload = IngestedDocument(
        project_id="demo",
        filename="contract_b.pdf",
        entities=[{"entity_id": "acme", "name": "Acme Corp", "entity_type": "organization"}],
        claims=[
            {"claim_id": "c1", "text": "Payment term is 30 days.", "confidence": 0.9},
            {"claim_id": "c2", "text": "Payment term is 45 days.", "confidence": 0.7},
        ],
        facts=[
            {"claim_ref": "c1", "entity_ref": "acme", "fact_type": "payment_term", "value": "30 days"},
            {"claim_ref": "c2", "entity_ref": "acme", "fact_type": "payment_term", "value": "45 days"},
        ],
    )

    store.ingest_document(payload)

    contradictions = store.get_contradictions("demo")
    assert len(contradictions) == 1
    assert contradictions[0]["fact_type"] == "payment_term"


def test_creates_snapshots_and_units(tmp_path: Path):
    store = ClaimLayerStore(tmp_path / "evidence.db")
    payload = IngestedDocument(
        project_id="demo",
        filename="contract_c.pdf",
        entities=[{"entity_id": "bob", "name": "Bob Smith", "entity_type": "person"}],
        claims=[{"claim_id": "c1", "text": "Bob Smith is the project lead.", "confidence": 0.8, "page": 2}],
        facts=[
            {
                "claim_ref": "c1",
                "entity_ref": "bob",
                "fact_type": "role",
                "value": "project lead",
                "sources": [{"page": 2, "text": "Bob Smith is the project lead."}],
            }
        ],
    )

    store.ingest_document(payload)

    history = store.get_state_history("demo")
    units = store.get_evidence_units("demo")

    assert len(history) == 1
    assert len(units) == 1
    assert units[0]["claim"]["predicate"] == "role"


def test_delta_and_paragraph_indexes(tmp_path: Path):
    store = ClaimLayerStore(tmp_path / "evidence.db")
    store.ingest_document(
        IngestedDocument(
            project_id="demo",
            filename="one.pdf",
            entities=[{"entity_id": "acme", "name": "Acme Corp", "entity_type": "organization"}],
            claims=[{"claim_id": "c1", "text": "Payment term is 30 days.", "confidence": 0.9, "page": 1, "paragraph_id": "p1"}],
            facts=[{"claim_ref": "c1", "entity_ref": "acme", "fact_type": "payment_term", "value": "30 days"}],
        )
    )
    store.ingest_document(
        IngestedDocument(
            project_id="demo",
            filename="two.pdf",
            entities=[{"entity_id": "acme", "name": "Acme Corp", "entity_type": "organization"}],
            claims=[{"claim_id": "c2", "text": "Payment term is 45 days.", "confidence": 0.8, "page": 2, "paragraph_id": "p2"}],
            facts=[{"claim_ref": "c2", "entity_ref": "acme", "fact_type": "payment_term", "value": "45 days"}],
        )
    )

    history = store.get_state_history("demo")
    delta = store.compute_delta("demo", history[0]["id"], history[1]["id"])
    paragraphs = store.get_paragraphs_for_entity("demo", "Acme Corp")
    facttype_paragraphs = store.get_paragraphs_for_fact_type("demo", "payment_term")

    assert delta["delta"]["facts_added"] >= 1
    assert delta["delta"]["documents_added"] >= 1
    assert len(paragraphs) == 2
    assert len(facttype_paragraphs) == 2


def test_knowledge_and_accumulation_and_graph(tmp_path: Path):
    store = ClaimLayerStore(tmp_path / "evidence.db")
    store.ingest_document(
        IngestedDocument(
            project_id="demo",
            filename="graph.pdf",
            entities=[
                {"entity_id": "acme", "name": "Acme Corp", "entity_type": "organization"},
                {"entity_id": "bob", "name": "Bob Smith", "entity_type": "person"},
            ],
            claims=[
                {"claim_id": "c1", "text": "Acme Corp pays $50,000.", "confidence": 0.9, "page": 1, "paragraph_id": "p1"},
                {"claim_id": "c2", "text": "Bob Smith is project lead.", "confidence": 0.8, "page": 2, "paragraph_id": "p2"},
            ],
            facts=[
                {"claim_ref": "c1", "entity_ref": "acme", "fact_type": "payment_amount", "value": "$50,000"},
                {"claim_ref": "c2", "entity_ref": "bob", "fact_type": "role", "value": "project lead"},
            ],
        )
    )

    knowledge = store.derive_knowledge("demo")
    accumulation = store.get_confidence_accumulation("demo")
    graph = store.get_evidence_graph("demo")
    clusters = store.get_entity_clusters("demo", "Acme Corp")
    cluster_facts = store.get_cluster_facts("demo", "Acme Corp", "payment_amount")

    assert knowledge["knowledge"]["global_metrics"]["total_knowledge_items"] >= 2
    assert len(accumulation["accumulation_curves"]) >= 1
    assert graph["metrics"]["entity_count"] >= 2
    assert len(clusters) == 1
    assert cluster_facts[0]["fact_type"] == "payment_amount"
