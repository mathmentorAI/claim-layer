#!/usr/bin/env python3
"""Smoke-test helper for the `integrate-claimlayer` skill.

Verifies that `claimlayer` v3.0+ is importable and deterministically enforces:
  1. RETRY (`requires_human=False`) on superseded or ungrounded agent assertions.
  2. PASS (`allowed_to_proceed=True`) + valid offline SHA-256 Merkle receipt on self-corrected assertions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Auto-discover `src/claimlayer` when run from inside a `claim-layer` checkout
for candidate in [
    Path(__file__).resolve().parents[3] / "src",
    Path(__file__).resolve().parents[4] / "claim-layer" / "src",
]:
    if (candidate / "claimlayer" / "__init__.py").is_file() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from claimlayer import (
    Assertion,
    FactRecord,
    Ledger,
    Policy,
    Source,
    __version__,
    verify_receipt,
)


def main() -> int:
    ledger = Ledger(
        sources=[
            Source(
                id="base_msa",
                text="Section 4.1: Payment terms are forty-five (45) days. Cap is $100,000.",
                tier="standard",
            ),
            Source(
                id="signed_amendment",
                text="Section 4.1 is amended: Payment terms are thirty (30) days.",
                tier="authoritative",
                supersedes=["base_msa"],
            ),
        ],
        facts=[
            FactRecord(
                subject="Customer",
                predicate="payment_terms",
                value="30 days",
                source_id="signed_amendment",
                quote="Payment terms are thirty (30) days.",
            )
        ],
    )
    policy = Policy(
        policy_id="smoke_test_policy",
        min_tier_rank=50,
        required_predicates=["payment_terms"],
        numeric_bounds={"liability_cap": (None, 250_000.0)},
    )

    # 1. Superseded / wrong value MUST bounce to agent via RETRY (0 human wait)
    bad = ledger.verify(
        assertions=[
            Assertion(
                subject="Customer",
                predicate="payment_terms",
                value="45 days",
                source_id="base_msa",
                quote="Payment terms are forty-five (45) days.",
            )
        ],
        policy=policy,
    )
    assert bad.status == "RETRY", f"Expected RETRY, got {bad.status}"
    assert bad.requires_human is False

    # 2. Grounded governing assertion MUST PASS with valid Merkle receipt
    good = ledger.verify(
        assertions=[
            Assertion(
                subject="Customer",
                predicate="payment_terms",
                value="30 days",
                source_id="signed_amendment",
                quote="Payment terms are thirty (30) days.",
            )
        ],
        policy=policy,
    )
    assert good.status == "PASS", f"Expected PASS, got {good.status}"
    assert good.allowed_to_proceed is True
    assert verify_receipt(good) is True

    print(
        json.dumps(
            {
                "status": "ok",
                "claimlayer_version": __version__,
                "retry_gate_verified": True,
                "pass_merkle_receipt": good.receipt.merkle_root,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
