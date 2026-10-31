"""Command-line interface for ClaimLayer computable verification."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from claimlayer.ledger import Ledger
from claimlayer.mcp_server import run_stdio_server
from claimlayer.models import Assertion, FactRecord, Policy, Source
from claimlayer.verify import verify


def _cmd_verify(bundle_path: Path, db_path: str | None) -> int:
    raw = json.loads(bundle_path.read_text(encoding="utf-8"))
    ledger = Ledger(
        sources=raw.get("sources") or [],
        facts=raw.get("facts") or [],
        db_path=db_path,
    )
    verdict = ledger.verify(
        assertions=raw.get("assertions") or [],
        policy=raw.get("policy"),
        as_of=raw.get("as_of"),
        agent_id=str(raw.get("agent_id") or "cli_agent"),
        record=bool(db_path),
    )
    print(json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False))
    if verdict.status == "PASS":
        return 0
    if verdict.status == "RETRY":
        return 2
    return 3


def _cmd_demo() -> int:
    print("=== ClaimLayer v3: Computable Verification Demo (Unblocking Agents) ===\n")
    ledger = Ledger(
        sources=[
            Source(
                id="msa_2024",
                title="Master Services Agreement (2024)",
                text="Section 4.1: ACME shall pay all undisputed invoices within 45 days. Governing law is Delaware.",
                tier="standard",
            ),
            Source(
                id="amendment_2026",
                title="Signed First Amendment (2026)",
                text="Section 4.1 is hereby amended: ACME shall pay all undisputed invoices within 30 days.",
                tier="authoritative",
                supersedes=["msa_2024"],
            ),
        ],
        facts=[
            FactRecord(
                subject="ACME",
                predicate="payment_terms",
                value="30 days",
                source_id="amendment_2026",
                quote="ACME shall pay all undisputed invoices within 30 days.",
            )
        ],
    )
    policy = Policy(
        policy_id="contract_ops_v1",
        required_predicates=["payment_terms", "governing_law"],
    )

    # Attempt 1: Agent cites obsolete MSA 45 days and misses governing_law -> RETRY (0 human time!)
    v1 = verify(
        assertions=[
            Assertion(
                subject="ACME",
                predicate="payment_terms",
                value="45 days",
                source_id="msa_2024",
                quote="ACME shall pay all undisputed invoices within 45 days.",
            )
        ],
        ledger=ledger,
        policy=policy,
        agent_id="contract_agent_01",
    )
    print(f"[Turn 1] Agent submits flawed draft -> Verdict: {v1.status} (Requires Human: {v1.requires_human})")
    for issue in v1.issues:
        print(f"   - [{issue.code}] {issue.message}")
        print(f"     Fix -> {issue.remediation}")

    # Attempt 2: Agent self-corrects in milliseconds -> PASS (Auto-approved with Merkle proof!)
    v2 = verify(
        assertions=[
            Assertion(
                subject="ACME",
                predicate="payment_terms",
                value="30 days",
                source_id="amendment_2026",
                quote="ACME shall pay all undisputed invoices within 30 days.",
            ),
            Assertion(
                subject="ACME",
                predicate="governing_law",
                value="Delaware",
                source_id="msa_2024",
                quote="Governing law is Delaware.",
            ),
        ],
        ledger=ledger,
        policy=policy,
        agent_id="contract_agent_01",
    )
    print(f"\n[Turn 2] Agent self-corrects -> Verdict: {v2.status} (Allowed to Proceed: {v2.allowed_to_proceed})")
    print(f"   - Confidence: {v2.confidence:.2f} | Merkle Root: {v2.receipt.merkle_root[:24]}...")
    print(f"   - Offline Cryptographic Verification: {v2.verify_receipt()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="claimlayer",
        description="ClaimLayer v3 — Deterministic Computable Verification for AI Agents",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_verify = sub.add_parser("verify", help="Verify an agent JSON proposal bundle")
    p_verify.add_argument("--bundle", "-b", required=True, type=Path, help="Path to JSON bundle")
    p_verify.add_argument("--db", default=None, help="Optional SQLite ledger path")

    p_mcp = sub.add_parser("mcp", help="Start ClaimLayer MCP server over stdio")
    p_mcp.add_argument("--db", default=None, help="Optional SQLite ledger path")

    sub.add_parser("demo", help="Run a quick self-contained verification loop demo")

    args = parser.parse_args(argv)
    if args.command == "verify":
        return _cmd_verify(args.bundle, args.db)
    if args.command == "mcp":
        return run_stdio_server(db_path=args.db)
    return _cmd_demo()


if __name__ == "__main__":
    raise SystemExit(main())
