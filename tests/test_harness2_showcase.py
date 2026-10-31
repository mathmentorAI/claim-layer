"""End-to-end tests for the Harness² × Harvey LAB Case 1 Computable Verification Showcase."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from claimlayer import build_comparison_policy, verify_receipt
from examples.harness2_securitization.replay_om_vs_indenture import (
    build_securitization_case,
    main as run_replay_main,
)
from examples.harness2_securitization.run_harness2_ab import stage_self_contained_harness


def test_replay_om_vs_indenture_three_turn_convergence() -> None:
    _, indenture, offering_memo = build_securitization_case()
    _, divergences = build_comparison_policy(indenture, offering_memo)
    assert len(divergences) == 4
    assert run_replay_main() == 0


def test_self_contained_harness2_c7_gate_in_isolated_sandbox(tmp_path: Path) -> None:
    """Verify staged `scripts/claimlayer_gate.py` runs inside an isolated workspace with zero PYTHONPATH."""
    staged = stage_self_contained_harness(tmp_path / "harness_surface")
    sandbox = tmp_path / "task_workspace"
    docs_dir = sandbox / "documents"
    docs_dir.mkdir(parents=True)
    # Copy c7 scripts into sandbox/scripts just as Harness² `run_opencode.py` does
    import shutil

    shutil.copytree(staged / "scripts", sandbox / "scripts")

    (docs_dir / "executed_indenture.txt").write_text(
        "Section 2.04: Class C Notes ($50,000,000 principal) bear interest at 6.75% per annum.\n"
        "Section 7.01: Failure to pay interest continuing for 5 business days is an Event of Default.\n",
        encoding="utf-8",
    )
    (docs_dir / "draft_offering-memorandum.txt").write_text(
        "Section 2.04: Class C Notes ($50,000,000 principal) bear interest at 6.50% per annum.\n"
        "Section 7.01: Failure to pay interest continuing for 30 days is an Event of Default.\n",
        encoding="utf-8",
    )
    (docs_dir / "associate_email.eml").write_text(
        "Team: please compare the OM against the Executed Indenture before printing.",
        encoding="utf-8",
    )

    clean_env = {"PATH": "/usr/bin:/bin"}

    # 1. `prepare` registers tiers & discovers mandatory divergent sections
    prep = subprocess.run(
        [sys.executable, "scripts/claimlayer_gate.py", "prepare", "documents"],
        cwd=sandbox,
        env=clean_env,
        capture_output=True,
        text=True,
        check=True,
    )
    prep_json = json.loads(prep.stdout)
    tiers = {s["id"]: s["tier"] for s in prep_json["sources_registered"]}
    assert tiers == {
        "associate_email.eml": "draft",
        "draft_offering-memorandum.txt": "standard",
        "executed_indenture.txt": "authoritative",
    }
    mandatory_keys = [d["section_key"] for d in prep_json["mandatory_divergent_sections"]]
    assert mandatory_keys == ["section_2_04", "section_7_01"]

    # 2. Incomplete / wrong-tier proposal bounces with exit code 2 (`RETRY`)
    bad_proposal = sandbox / "bad_proposal.json"
    bad_proposal.write_text(
        json.dumps(
            {
                "assertions": [
                    {
                        "subject": "Class_C_Notes",
                        "predicate": "section_2_04",
                        "value": "6.50%",
                        "source_id": "draft_offering-memorandum.txt",
                        "quote": "Class C Notes ($50,000,000 principal) bear interest at 6.50% per annum.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    res_bad = subprocess.run(
        [sys.executable, "scripts/claimlayer_gate.py", "verify", "bad_proposal.json"],
        cwd=sandbox,
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert res_bad.returncode == 2
    bad_verdict = json.loads(res_bad.stdout)
    assert bad_verdict["status"] == "RETRY"
    issue_codes = {i["code"] for i in bad_verdict["issues"]}
    assert "INSUFFICIENT_AUTHORITY_TIER" in issue_codes
    assert "MISSING_REQUIRED_PREDICATE" in issue_codes

    # 3. Self-corrected proposal citing Executed Indenture passes with exit code 0 (`PASS`)
    good_proposal = sandbox / "good_proposal.json"
    good_proposal.write_text(
        json.dumps(
            {
                "assertions": [
                    {
                        "subject": "Class_C_Notes",
                        "predicate": "section_2_04",
                        "value": "6.75% ($50,000,000)",
                        "source_id": "executed_indenture.txt",
                        "quote": "Class C Notes ($50,000,000 principal) bear interest at 6.75% per annum.",
                    },
                    {
                        "subject": "Deal_Default",
                        "predicate": "section_7_01",
                        "value": "5 business days",
                        "source_id": "executed_indenture.txt",
                        "quote": "Failure to pay interest continuing for 5 business days is an Event of Default.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    res_good = subprocess.run(
        [sys.executable, "scripts/claimlayer_gate.py", "verify", "good_proposal.json"],
        cwd=sandbox,
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert res_good.returncode == 0
    good_verdict = json.loads(res_good.stdout)
    assert good_verdict["status"] == "PASS"
    assert verify_receipt(good_verdict) is True
