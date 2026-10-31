"""Invariant and end-to-end test suite for ClaimLayer v3 computable verification."""

from __future__ import annotations

import json
from pathlib import Path

from claimlayer import (
    Assertion,
    FactRecord,
    Ledger,
    MCPVerificationServer,
    Policy,
    Source,
    verify,
    verify_receipt,
)
from claimlayer.cli import main as cli_main
from claimlayer.mcp_server import MCPSession


def test_g1_strict_determinism() -> None:
    ledger = Ledger(
        sources=[
            Source(
                id="contract_a",
                text="Section 2: ACME payment terms are 30 days. Cap is $500,000.",
                tier="authoritative",
            )
        ]
    )
    assertions = [
        Assertion(
            subject="ACME",
            predicate="payment_terms",
            value="30 days",
            source_id="contract_a",
            quote="ACME payment terms are 30 days.",
        )
    ]
    policy = Policy(policy_id="det_v1")

    v1 = verify(assertions, ledger, policy, as_of="2026-10-30")
    v2 = verify(assertions, ledger, policy, as_of="2026-10-30")

    assert v1.status == "PASS"
    assert v1.verdict_id == v2.verdict_id
    assert v1.to_dict() == v2.to_dict()
    assert v1.verify_receipt() is True


def test_g2_quote_and_source_grounding_bounces_to_agent() -> None:
    ledger = Ledger(
        sources=[Source(id="doc_1", text="Vendor fee is $12,000 per quarter.", tier="standard")]
    )

    # 1. Unknown source
    v_missing_src = verify(
        [
            Assertion(
                subject="Vendor",
                predicate="fee",
                value="$12,000",
                source_id="nonexistent_doc",
                quote="Vendor fee is $12,000",
            )
        ],
        ledger,
    )
    assert v_missing_src.status == "RETRY"
    assert v_missing_src.requires_human is False
    assert v_missing_src.issues[0].code == "SOURCE_NOT_FOUND"

    # 2. Fabricated quote
    v_bad_quote = verify(
        [
            Assertion(
                subject="Vendor",
                predicate="fee",
                value="$12,000",
                source_id="doc_1",
                quote="Vendor fee is waived completely for 2026.",
            )
        ],
        ledger,
    )
    assert v_bad_quote.status == "RETRY"
    assert v_bad_quote.requires_human is False
    assert v_bad_quote.issues[0].code == "QUOTE_NOT_IN_SOURCE"


def test_g3_quantity_scale_unit_and_date_verification() -> None:
    ledger = Ledger(
        sources=[
            Source(
                id="term_sheet",
                text=(
                    "Invoices are payable within thirty (30) days. "
                    "Working capital collar is $500,000. Maturity date is 2027-06-30."
                ),
                tier="authoritative",
            )
        ]
    )

    # Equivalent written number ("thirty (30) days" <-> "30 days") and scale ("$500K" <-> "$500,000")
    v_ok = verify(
        [
            Assertion(
                subject="Deal",
                predicate="payment_terms",
                value="30 days",
                source_id="term_sheet",
                quote="payable within thirty (30) days.",
            ),
            Assertion(
                subject="Deal",
                predicate="nwc_collar",
                value="$500K",
                source_id="term_sheet",
                quote="Working capital collar is $500,000.",
            ),
            Assertion(
                subject="Deal",
                predicate="maturity_date",
                value="2027-06-30",
                source_id="term_sheet",
                quote="Maturity date is 2027-06-30.",
            ),
        ],
        ledger,
    )
    assert v_ok.status == "PASS"
    assert v_ok.allowed_to_proceed is True

    # Wrong magnitude ($50K vs $500,000) -> RETRY
    v_wrong_num = verify(
        [
            Assertion(
                subject="Deal",
                predicate="nwc_collar",
                value="$50K",
                source_id="term_sheet",
                quote="Working capital collar is $500,000.",
            )
        ],
        ledger,
    )
    assert v_wrong_num.status == "RETRY"
    assert v_wrong_num.issues[0].code == "QUANTITY_MISMATCH"

    # Unit collision check ("30 EUR" vs "30 days") -> UNIT_MISMATCH (RETRY)
    v_wrong_unit = verify(
        [
            Assertion(
                subject="Deal",
                predicate="payment_terms",
                value="30 EUR",
                source_id="term_sheet",
                quote="payable within thirty (30) days.",
            )
        ],
        ledger,
    )
    assert v_wrong_unit.status == "RETRY"
    assert v_wrong_unit.issues[0].code == "UNIT_MISMATCH"

    # Wrong ISO date -> DATE_MISMATCH (RETRY)
    v_wrong_date = verify(
        [
            Assertion(
                subject="Deal",
                predicate="maturity_date",
                value="2027-12-31",
                source_id="term_sheet",
                quote="Maturity date is 2027-06-30.",
            )
        ],
        ledger,
    )
    assert v_wrong_date.status == "RETRY"
    assert v_wrong_date.issues[0].code == "DATE_MISMATCH"


def test_g4_partial_amendment_supersession_and_temporal_expiry() -> None:
    ledger = Ledger(
        sources=[
            Source(
                id="msa_base",
                text="Payment terms are 45 days. Governing law is New York.",
                tier="standard",
            ),
            Source(
                id="amendment_1",
                text="Section 4 is amended: Payment terms are 30 days.",
                tier="authoritative",
                supersedes=["msa_base"],
            ),
            Source(
                id="promo_2025",
                text="Promotional discount is 15%.",
                tier="standard",
                valid_until="2025-12-31",
            ),
        ],
        facts=[
            FactRecord(
                subject="ACME",
                predicate="payment_terms",
                value="30 days",
                source_id="amendment_1",
                quote="Payment terms are 30 days.",
            )
        ],
    )

    # Citing superseded clause (payment_terms = 45 days from msa_base) -> RETRY
    v_sup = verify(
        [
            Assertion(
                subject="ACME",
                predicate="payment_terms",
                value="45 days",
                source_id="msa_base",
                quote="Payment terms are 45 days.",
            )
        ],
        ledger,
    )
    assert v_sup.status == "RETRY"
    assert v_sup.issues[0].code == "SOURCE_SUPERSEDED"

    # Citing untouched clause (governing_law = New York from msa_base) -> PASS!
    v_untouched = verify(
        [
            Assertion(
                subject="ACME",
                predicate="governing_law",
                value="New York",
                source_id="msa_base",
                quote="Governing law is New York.",
            )
        ],
        ledger,
    )
    assert v_untouched.status == "PASS"

    # Citing expired source as_of 2026-10-30 -> SOURCE_EXPIRED (RETRY)
    v_exp = verify(
        [
            Assertion(
                subject="ACME",
                predicate="discount",
                value="15%",
                source_id="promo_2025",
                quote="Promotional discount is 15%.",
            )
        ],
        ledger,
        as_of="2026-10-30",
    )
    assert v_exp.status == "RETRY"
    assert v_exp.issues[0].code == "SOURCE_EXPIRED"


def test_g5_coverage_gate_catches_omitted_clauses() -> None:
    ledger = Ledger(
        sources=[Source(id="spa", text="Cap is $2M. Survival is 18 months.", tier="authoritative")]
    )
    policy = Policy(required_predicates=["indemnity_cap", "survival_period"])

    v_incomplete = verify(
        [
            Assertion(
                subject="SPA",
                predicate="indemnity_cap",
                value="$2M",
                source_id="spa",
                quote="Cap is $2M.",
            )
        ],
        ledger,
        policy,
    )
    assert v_incomplete.status == "RETRY"
    assert any(i.code == "MISSING_REQUIRED_PREDICATE" for i in v_incomplete.issues)


def test_g6_peer_conflict_escalation_and_human_resolution_loop() -> None:
    ledger = Ledger(
        sources=[
            Source(
                id="indenture",
                text="Class C Note interest rate shall be 6.75% per annum.",
                tier="authoritative",
            ),
            Source(
                id=" final_supplement",
                text="Class C Note interest rate shall be 6.50% per annum.",
                tier="authoritative",
            ),
        ],
        facts=[
            FactRecord(
                subject="Class_C_Notes",
                predicate="interest_rate",
                value="6.50%",
                source_id=" final_supplement",
                quote="Class C Note interest rate shall be 6.50% per annum.",
            )
        ],
    )

    # Genuine conflict between two authoritative sources -> ESCALATE to human with diff!
    verdict = ledger.verify(
        [
            Assertion(
                subject="Class_C_Notes",
                predicate="interest_rate",
                value="6.75%",
                source_id="indenture",
                quote="Class C Note interest rate shall be 6.75% per annum.",
            )
        ],
        record=True,
    )
    assert verdict.status == "ESCALATE"
    assert verdict.requires_human is True
    assert verdict.allowed_to_proceed is False
    assert len(verdict.conflicts) == 1
    assert verdict.conflicts[0].proposed_value == "6.75%"
    assert verdict.conflicts[0].competing_value == "6.50%"

    # Human resolves conflict in 1 click selecting 6.75%
    ledger.resolve_escalation(
        verdict_id=verdict.verdict_id,
        subject="Class_C_Notes",
        predicate="interest_rate",
        selected_value="6.75%",
        resolver="general_counsel",
        note="Indenture controls over typographical error in supplement.",
    )

    # Agent re-verifies -> now PASS immediately!
    verdict_after = ledger.verify(
        [
            Assertion(
                subject="Class_C_Notes",
                predicate="interest_rate",
                value="6.75%",
                source_id="indenture",
                quote="Class C Note interest rate shall be 6.75% per annum.",
            )
        ],
        record=True,
    )
    assert verdict_after.status == "PASS"
    assert verdict_after.allowed_to_proceed is True


def test_retry_takes_precedence_over_escalate_to_protect_humans() -> None:
    ledger = Ledger(
        sources=[Source(id="policy_doc", text="Refund requested is $9,000.", tier="authoritative")]
    )
    policy = Policy(numeric_bounds={"refund_amount": (None, 5_000.0)})

    # Proposal has BOTH an above-cap value ($9,000 > $5,000 -> ESCALATE) AND a second assertion
    # with a hallucinated quote (-> RETRY). Overall status MUST be RETRY so no human is interrupted!
    v = verify(
        [
            Assertion(
                subject="Order_99",
                predicate="refund_amount",
                value="$9,000",
                source_id="policy_doc",
                quote="Refund requested is $9,000.",
            ),
            Assertion(
                subject="Order_99",
                predicate="reason",
                value="damaged",
                source_id="policy_doc",
                quote="Fabricated quote that does not exist.",
            ),
        ],
        ledger,
        policy,
    )
    assert v.status == "RETRY"
    assert v.requires_human is False


def test_g7_merkle_receipt_tamper_detection() -> None:
    ledger = Ledger(sources=[Source(id="s1", text="Limit is 100 days.", tier="authoritative")])
    v = verify(
        [
            Assertion(
                subject="X",
                predicate="limit",
                value="100 days",
                source_id="s1",
                quote="Limit is 100 days.",
            )
        ],
        ledger,
    )
    assert verify_receipt(v) is True

    tampered = v.to_dict()
    tampered["assertions"][0]["value"] = "999 days"
    assert verify_receipt(tampered) is False


def test_sqlite_persistence_mcp_and_cli(tmp_path: Path) -> None:
    db_file = tmp_path / "ledger.sqlite"
    ledger = Ledger(db_path=db_file)
    mcp = MCPVerificationServer(ledger)
    session = MCPSession()

    init_resp = mcp.handle_envelope(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25"},
        },
        session,
    )
    assert init_resp[0]["result"]["serverInfo"]["name"] == "claimlayer-mcp"
    mcp.handle_envelope({"jsonrpc": "2.0", "method": "notifications/initialized"}, session)

    reg_resp = mcp.handle_envelope(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "register_source",
                "arguments": {
                    "id": "sla_doc",
                    "text": "Response SLA is 4 hours.",
                    "tier": "authoritative",
                },
            },
        },
        session,
    )
    assert reg_resp[0]["result"]["structuredContent"]["registered"] is True

    ver_resp = mcp.handle_envelope(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "verify_proposal",
                "arguments": {
                    "agent_id": "ops_agent",
                    "assertions": [
                        {
                            "subject": "Support",
                            "predicate": "response_sla",
                            "value": "4 hours",
                            "source_id": "sla_doc",
                            "quote": "Response SLA is 4 hours.",
                        }
                    ],
                },
            },
        },
        session,
    )
    verdict_data = ver_resp[0]["result"]["structuredContent"]
    assert verdict_data["status"] == "PASS"

    # Rehydrate from SQLite in a fresh Ledger instance
    rehydrated = Ledger(db_path=db_file)
    metrics = rehydrated.get_metrics()
    assert metrics["total_verifications"] == 1
    assert metrics["auto_approved_pass"] == 1
    assert metrics["human_supervision_saved_pct"] == 100.0

    # CLI test
    bundle_file = tmp_path / "bundle.json"
    bundle_file.write_text(
        json.dumps(
            {
                "sources": [{"id": "s1", "text": "Fee is $250.", "tier": "authoritative"}],
                "assertions": [
                    {
                        "subject": "Item",
                        "predicate": "fee",
                        "value": "$250",
                        "source_id": "s1",
                        "quote": "Fee is $250.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli_main(["verify", "--bundle", str(bundle_file)])
    assert exit_code == 0


def test_g8_automated_document_comparison_policy_catches_skipped_sections() -> None:
    from claimlayer import build_comparison_policy

    indenture = Source(
        id="indenture",
        tier="authoritative",
        text=(
            "Section 2.04: Interest Rates. Class C Notes bear interest at 6.75% per annum.\n"
            "Section 5.04: Priority of Payments. Reserve Account replenishment is paid at Step 13, junior to Class B and Class C principal.\n"
            "Section 9.01: Clean-Up Call. Optional redemption is permitted at 10% pool factor."
        ),
    )
    offering_memo = Source(
        id="offering_memorandum",
        tier="standard",
        text=(
            "Section 2.04: Interest Rates. Class C Notes bear interest at 6.50% per annum.\n"
            "Section 5.04: Priority of Payments. Reserve Account replenishment is paid at Step 6, senior to Class B and Class C principal.\n"
            "Section 9.01: Clean-Up Call. Optional redemption is permitted at 10% pool factor."
        ),
    )

    policy, divergences = build_comparison_policy(indenture, offering_memo)
    # Section 2.04 and Section 5.04 diverge; Section 9.01 is identical!
    div_keys = [d.section_key for d in divergences]
    assert div_keys == ["section_2_04", "section_5_04"]

    ledger = Ledger(sources=[indenture, offering_memo])

    # Naive baseline agent only checks Section 2.04 and skips Section 5.04 -> RETRY!
    v_partial = verify(
        [
            Assertion(
                subject="Class_C_Notes",
                predicate="section_2_04",
                value="6.75%",
                source_id="indenture",
                quote="Class C Notes bear interest at 6.75% per annum.",
            )
        ],
        ledger,
        policy,
    )
    assert v_partial.status == "RETRY"
    assert any(
        i.code == "MISSING_REQUIRED_PREDICATE" and i.predicate == "section_5_04"
        for i in v_partial.issues
    )

    # Complete grounded audit citing the governing Indenture on both divergent sections -> PASS!
    v_complete = verify(
        [
            Assertion(
                subject="Class_C_Notes",
                predicate="section_2_04",
                value="6.75%",
                source_id="indenture",
                quote="Class C Notes bear interest at 6.75% per annum.",
            ),
            Assertion(
                subject="Reserve_Account",
                predicate="section_5_04",
                value="Step 13 junior to Class B and Class C principal",
                source_id="indenture",
                quote="Reserve Account replenishment is paid at Step 13, junior to Class B and Class C principal.",
            ),
        ],
        ledger,
        policy,
    )
    assert v_complete.status == "PASS"
    assert v_complete.allowed_to_proceed is True

