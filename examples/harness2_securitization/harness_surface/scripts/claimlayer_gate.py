#!/usr/bin/env python3
"""Executable Harness² `c7` gate script (`claimlayer_gate.py`) for OpenCode / Harvey LAB agents.

Commands:
  1. `python3 scripts/claimlayer_gate.py prepare [documents_dir]`
     Extracts plain text from task documents, registers them in `.claimlayer/ledger.sqlite`
     with deterministic authority tiers (Indenture/MSA = authoritative, OM/Markup = standard,
     Email = draft), and prints every divergent section that MUST be verified before completion.

  2. `python3 scripts/claimlayer_gate.py verify <proposal.json>`
     Runs `claimlayer.verify()` against `.claimlayer/ledger.sqlite` and `.claimlayer/policy.json`.
     - Exit 0 (`PASS`): All divergent sections and quotes verified; writes `.claimlayer/receipt.json`.
     - Exit 2 (`RETRY`): Prints structured JSON remediation errors for immediate self-correction.
     - Exit 3 (`ESCALATE`): Genuine peer conflict or threshold exception documented for human sign-off.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Locate claimlayer package from bundled scripts/claimlayer, repo checkout, or CLAIMLAYER_ROOT
for candidate in [
    Path(__file__).resolve().parent,
    Path(__file__).resolve().parents[3] / "src",
    Path(__file__).resolve().parents[4] / "claim-layer" / "src",
    Path(os.environ.get("CLAIMLAYER_ROOT", "")) / "src",
    Path(os.environ.get("CLAIMLAYER_ROOT", "")) / "claim-layer" / "src",
]:
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from claimlayer import Ledger, Policy, Source, build_comparison_policy


def _read_doc_text(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    # Use Harvey LAB host parser if running inside harvey-labs sandbox
    lab_root = os.environ.get("LAB_BENCH_ROOT")
    if lab_root:
        parser_dir = Path(lab_root) / "sandbox" / "parsers"
        if (parser_dir / "parse_doc.py").is_file():
            if str(parser_dir) not in sys.path:
                sys.path.insert(0, str(parser_dir))
            import parse_doc  # type: ignore[import-not-found]

            if ext in parse_doc.PARSERS:
                return str(parse_doc.PARSERS[ext](str(path)))
    return path.read_text(encoding="utf-8", errors="replace")


def _classify_tier(filename: str) -> str:
    low = filename.lower()
    tokens = set(re.split(r"[^a-z0-9]+", Path(low).stem))
    if low.endswith(".eml") or tokens & {"email", "emails", "note", "notes", "instruction", "instructions"}:
        return "draft"
    if (
        "offering-memorandum" in low
        or "offering_memorandum" in low
        or "offering memorandum" in low
        or tokens & {"om", "prospectus", "markup", "redline", "proposed", "summary"}
    ):
        return "standard"
    return "authoritative"


def cmd_prepare(docs_dir: Path, workspace: Path) -> int:
    state_dir = workspace / ".claimlayer"
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "ledger.sqlite"
    if db_path.exists():
        db_path.unlink()

    ledger = Ledger(db_path=db_path)
    sources: list[Source] = []

    for f in sorted(docs_dir.iterdir()):
        if not f.is_file() or f.name.startswith("."):
            continue
        src = Source(
            id=f.name,
            title=f.name,
            text=_read_doc_text(f),
            tier=_classify_tier(f.name),
        )
        ledger.add_source(src)
        sources.append(src)

    auth_sources = [s for s in sources if s.tier == "authoritative"]
    std_sources = [s for s in sources if s.tier == "standard"]

    required_predicates: list[str] = []
    divergence_report: list[dict[str, Any]] = []

    if auth_sources and std_sources:
        _, divergences = build_comparison_policy(auth_sources[0], std_sources[0])
        required_predicates = [d.section_key for d in divergences]
        divergence_report = [d.to_dict() for d in divergences]

    policy = Policy(
        policy_id="harness2_computable_gate",
        min_tier_rank=100 if auth_sources else 50,
        required_predicates=required_predicates,
        required_source_ids=[s.id for s in auth_sources[:1]],
    )
    (state_dir / "policy.json").write_text(
        json.dumps(policy.to_dict(), indent=2), encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "sources_registered": [
                    {"id": s.id, "tier": s.tier, "rank": s.rank} for s in sources
                ],
                "mandatory_divergent_sections": divergence_report,
                "next_step": (
                    "Analyze every mandatory section, write structured assertions to proposal.json, "
                    "and run `python3 scripts/claimlayer_gate.py verify proposal.json` before finalizing output/."
                ),
            },
            indent=2,
        )
    )
    return 0


def cmd_verify(proposal_path: Path, workspace: Path) -> int:
    state_dir = workspace / ".claimlayer"
    ledger = Ledger(db_path=state_dir / "ledger.sqlite")
    policy_data = json.loads((state_dir / "policy.json").read_text(encoding="utf-8"))
    proposal = json.loads(proposal_path.read_text(encoding="utf-8"))

    verdict = ledger.verify(
        assertions=proposal.get("assertions") or [],
        policy=policy_data,
        agent_id="harness2_opencode_agent",
        record=True,
    )
    out = verdict.to_dict()
    (state_dir / "receipt.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))

    if verdict.status == "PASS":
        return 0
    if verdict.status == "RETRY":
        return 2
    return 3


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_prep = sub.add_parser("prepare")
    p_prep.add_argument("docs_dir", nargs="?", default="documents")
    p_ver = sub.add_parser("verify")
    p_ver.add_argument("proposal", help="Path to agent structured assertions JSON")

    args = ap.parse_args()
    ws = Path.cwd()
    if args.cmd == "prepare":
        return cmd_prepare((ws / args.docs_dir).resolve(), ws)
    return cmd_verify((ws / args.proposal).resolve(), ws)


if __name__ == "__main__":
    raise SystemExit(main())
