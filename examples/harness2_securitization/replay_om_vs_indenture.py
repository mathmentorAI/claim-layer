#!/usr/bin/env python3
"""Self-contained deterministic replay of Harvey LAB Case 1:
`structured-finance-securitization / compare-offering-memorandum-against-indenture`.

Runs offline in <20 ms with zero API keys, demonstrating how ClaimLayer v3 acts as an
executable `c7/c8` harness gate inside `google-research/harness2`:
  - Turn 1 (Vanilla Agent Failure Mode): Skips Waterfall & Coupon sections (only checks Clean-Up Call)
    and misstates a figure -> ClaimLayer returns RETRY in <0.3 ms (0 human time wasted).
  - Turn 2 (Authority Inversion Failure Mode): Cites the Offering Memorandum (6.50%) as governing
    instead of the executed Indenture (6.75%) -> ClaimLayer returns RETRY (HIGHER_TIER_OVERRIDE).
  - Turn 3 (Self-Corrected Proposal): All 4 divergent sections grounded in the governing Indenture ->
    PASS sealed with offline SHA-256 Merkle receipt (CLAIMLAYER-MERKLE-SHA256-v3).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_CLAIMLAYER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CLAIMLAYER_ROOT / "src"))

from claimlayer import (
    Assertion,
    FactRecord,
    Ledger,
    Source,
    build_comparison_policy,
    verify,
    verify_receipt,
)


def build_securitization_case() -> tuple[Ledger, Source, Source]:
    indenture = Source(
        id="executed_indenture_2026",
        title="Executed Master Trust Indenture (Controlling Instrument)",
        tier="authoritative",
        text=(
            "Section 2.04: Note Interest Rates. The Class A Notes bear interest at 5.10% per annum, "
            "Class B Notes at 5.85% per annum, and Class C Notes ($50,000,000 principal) bear interest at 6.75% per annum.\n"
            "Section 5.04: Priority of Payments (Waterfall). On each Payment Date, Available Funds shall distribute: "
            "Step 1 Trustee Fees; Steps 2-12 Class A, B, and C Interest and Principal; "
            "Step 13 Reserve Account Replenishment up to the Required Reserve Amount (junior to Class B and Class C principal).\n"
            "Section 7.01: Events of Default. Failure to pay interest continuing for 5 business days constitutes an Event of Default.\n"
            "Section 9.01: Optional Clean-Up Call. Servicer may redeem the Notes when Pool Balance falls to 10% of Initial Pool Balance.\n"
            "Section 11.03: Governing Law. This Indenture shall be governed by the laws of the State of New York."
        ),
    )

    offering_memorandum = Source(
        id="draft_offering_memorandum",
        title="Preliminary Offering Memorandum (Marketing Disclosure)",
        tier="standard",
        text=(
            "Section 2.04: Note Interest Rates. The Class A Notes bear interest at 5.10% per annum, "
            "Class B Notes at 5.85% per annum, and Class C Notes ($50,000,000 principal) bear interest at 6.50% per annum.\n"
            "Section 5.04: Priority of Payments (Waterfall). Available Funds pay Reserve Account Replenishment at Step 6, "
            "ahead of and senior to Class B and Class C principal payments.\n"
            "Section 7.01: Events of Default. Failure to pay interest continuing for 30 days constitutes an Event of Default.\n"
            "Section 9.01: Optional Clean-Up Call. Servicer may redeem the Notes when Pool Balance falls to 15% of Initial Pool Balance.\n"
            "Section 11.03: Governing Law. This Indenture shall be governed by the laws of the State of New York."
        ),
    )

    associate_email = Source(
        id="associate_instructions_eml",
        title="Associate Deal Email",
        tier="draft",
        text=(
            "Please compare the draft Offering Memorandum against the executed Indenture before printing. "
            "Remember the executed Indenture governs in any conflict. Check coupons, waterfall, cure periods, and redemption."
        ),
    )

    ledger = Ledger(
        sources=[indenture, offering_memorandum, associate_email],
        facts=[
            FactRecord(
                subject="Deal_Waterfall",
                predicate="section_2_04",
                value="6.75%",
                source_id="executed_indenture_2026",
                quote="Class C Notes ($50,000,000 principal) bear interest at 6.75% per annum.",
            ),
            FactRecord(
                subject="Deal_Waterfall",
                predicate="section_5_04",
                value="Step 13 junior to Class B and Class C principal",
                source_id="executed_indenture_2026",
                quote="Step 13 Reserve Account Replenishment up to the Required Reserve Amount (junior to Class B and Class C principal).",
            ),
            FactRecord(
                subject="Deal_Waterfall",
                predicate="section_7_01",
                value="5 business days",
                source_id="executed_indenture_2026",
                quote="Failure to pay interest continuing for 5 business days constitutes an Event of Default.",
            ),
            FactRecord(
                subject="Deal_Waterfall",
                predicate="section_9_01",
                value="10%",
                source_id="executed_indenture_2026",
                quote="Servicer may redeem the Notes when Pool Balance falls to 10% of Initial Pool Balance.",
            ),
        ],
    )
    return ledger, indenture, offering_memorandum


def main() -> int:
    t0 = time.perf_counter()
    ledger, indenture, offering_memo = build_securitization_case()

    # Deterministic diff discovers the exact 4 sections that diverge (Section 11.03 is identical!)
    policy, divergences = build_comparison_policy(
        indenture,
        offering_memo,
        policy_id="harvey_lab_om_vs_indenture",
        min_tier_rank=50,
    )

    print("=" * 78)
    print("HARNESS² × CLAIMLAYER v3 — CASE 1: OFFERING MEMORANDUM vs. INDENTURE")
    print("=" * 78)
    print(f"Divergent Sections Auto-Detected ({len(divergences)} of 5 total sections):")
    for div in divergences:
        print(f"  • [{div.section_key}] {div.reason}")

    # -------------------------------------------------------------------------
    # TURN 1: Vanilla Baseline Failure Mode (Agent only checks Clean-Up Call
    #         and hallucinates 12% instead of 10%, skipping Waterfall & Coupons)
    # -------------------------------------------------------------------------
    v_turn1 = verify(
        assertions=[
            Assertion(
                subject="Deal_Waterfall",
                predicate="section_9_01",
                value="12%",
                source_id="executed_indenture_2026",
                quote="Servicer may redeem the Notes when Pool Balance falls to 10% of Initial Pool Balance.",
            )
        ],
        ledger=ledger,
        policy=policy,
        agent_id="opencode-solver-k1",
    )
    print(f"\n[Turn 1] Baseline-style incomplete draft -> Verdict: {v_turn1.status} (Human Woken: {v_turn1.requires_human})")
    for iss in v_turn1.issues:
        print(f"   ✗ {iss.code}: {iss.message}")

    # -------------------------------------------------------------------------
    # TURN 2: Agent covers all 4 sections, but mistakenly treats the Offering
    #         Memorandum's 6.50% coupon as governing over the 6.75% Indenture!
    # -------------------------------------------------------------------------
    v_turn2 = verify(
        assertions=[
            Assertion(
                subject="Deal_Waterfall",
                predicate="section_2_04",
                value="6.50%",
                source_id="draft_offering_memorandum",
                quote="Class C Notes ($50,000,000 principal) bear interest at 6.50% per annum.",
            ),
            Assertion(
                subject="Deal_Waterfall",
                predicate="section_5_04",
                value="Step 13",
                source_id="executed_indenture_2026",
                quote="Step 13 Reserve Account Replenishment up to the Required Reserve Amount (junior to Class B and Class C principal).",
            ),
            Assertion(
                subject="Deal_Waterfall",
                predicate="section_7_01",
                value="5 business days",
                source_id="executed_indenture_2026",
                quote="Failure to pay interest continuing for 5 business days constitutes an Event of Default.",
            ),
            Assertion(
                subject="Deal_Waterfall",
                predicate="section_9_01",
                value="10%",
                source_id="executed_indenture_2026",
                quote="Servicer may redeem the Notes when Pool Balance falls to 10% of Initial Pool Balance.",
            ),
        ],
        ledger=ledger,
        policy=policy,
        agent_id="opencode-solver-k1",
    )
    print(f"\n[Turn 2] Agent inverts authority (cites OM 6.50%) -> Verdict: {v_turn2.status} (Human Woken: {v_turn2.requires_human})")
    for iss in v_turn2.issues:
        print(f"   ✗ {iss.code}: {iss.message}")
        print(f"     ↳ Auto-Remediation to Agent: {iss.remediation}")

    # -------------------------------------------------------------------------
    # TURN 3: Agent self-corrects Section 2.04 to governing Indenture 6.75%
    # -------------------------------------------------------------------------
    v_turn3 = verify(
        assertions=[
            Assertion(
                subject="Deal_Waterfall",
                predicate="section_2_04",
                value="6.75%",
                source_id="executed_indenture_2026",
                quote="Class C Notes ($50,000,000 principal) bear interest at 6.75% per annum.",
            ),
            Assertion(
                subject="Deal_Waterfall",
                predicate="section_5_04",
                value="Step 13",
                source_id="executed_indenture_2026",
                quote="Step 13 Reserve Account Replenishment up to the Required Reserve Amount (junior to Class B and Class C principal).",
            ),
            Assertion(
                subject="Deal_Waterfall",
                predicate="section_7_01",
                value="5 business days",
                source_id="executed_indenture_2026",
                quote="Failure to pay interest continuing for 5 business days constitutes an Event of Default.",
            ),
            Assertion(
                subject="Deal_Waterfall",
                predicate="section_9_01",
                value="10%",
                source_id="executed_indenture_2026",
                quote="Servicer may redeem the Notes when Pool Balance falls to 10% of Initial Pool Balance.",
            ),
        ],
        ledger=ledger,
        policy=policy,
        agent_id="opencode-solver-k1",
    )

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    print(f"\n[Turn 3] Agent self-corrected -> Verdict: {v_turn3.status} (Allowed to Proceed: {v_turn3.allowed_to_proceed})")
    print(f"   ✓ All 4 divergent sections verified in {elapsed_ms:.2f} ms total (0 LLM judge calls, 0 human wait)")
    print(f"   ✓ Merkle Root ({v_turn3.receipt.scheme}): {v_turn3.receipt.merkle_root}")
    print(f"   ✓ Offline Receipt Signature Valid: {verify_receipt(v_turn3)}")
    print("=" * 78)

    assert v_turn1.status == "RETRY"
    assert v_turn2.status == "RETRY"
    assert v_turn3.status == "PASS"
    assert verify_receipt(v_turn3) is True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
