#!/usr/bin/env python3
"""Live A/B Harness² Runner for Harvey LAB Case 1 (`compare-offering-memorandum-against-indenture`).

Stages a self-contained `Harness²` surface (`guardrails.md` + `skills/claimlayer_verify/` +
`scripts/claimlayer_gate.py` + zero-dependency `claimlayer` stdlib engine) so OpenCode agents
inside Harvey LAB's sandbox execute deterministic `<1 ms` computable verification with zero
external pip installs.

Usage:
  # 1. Inspect staged Harness² surface & exact commands (no API key required)
  .venv/bin/python examples/harness2_securitization/run_harness2_ab.py --dry-run

  # 2. Run live Baseline vs. ClaimLayer v3 A/B benchmark on Harvey LAB
  export OPENAI_API_KEY="sk-..."
  .venv/bin/python examples/harness2_securitization/run_harness2_ab.py \
      --lab-root /path/to/harvey-labs \
      --model openai/gpt-5.4 \
      --run-eval
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CLAIMLAYER_ROOT = Path(__file__).resolve().parents[2]
SURFACE_SRC = Path(__file__).resolve().parent / "harness_surface"
CLAIMLAYER_PKG_SRC = CLAIMLAYER_ROOT / "src" / "claimlayer"

DEFAULT_TASK = "structured-finance-securitization/compare-offering-memorandum-against-indenture"


def stage_self_contained_harness(dest_dir: Path) -> Path:
    """Assemble an isolated Harness² directory containing `c2`, `c6`, and `c7` + pure-stdlib `claimlayer`."""
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(SURFACE_SRC, dest_dir)
    shutil.copytree(
        CLAIMLAYER_PKG_SRC,
        dest_dir / "scripts" / "claimlayer",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return dest_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lab-root",
        type=Path,
        default=Path(os.environ.get("LAB_BENCH_ROOT", "./harvey-labs")),
        help="Path to cloned `harveyai/harvey-labs` repository.",
    )
    parser.add_argument(
        "--task",
        default=DEFAULT_TASK,
        help="Harvey LAB task slug (`domain/workflow`).",
    )
    parser.add_argument(
        "--model",
        default="openai/gpt-5.4",
        help="OpenCode model identifier (e.g. `openai/gpt-5.4` or `anthropic/claude-sonnet-4-5`).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=CLAIMLAYER_ROOT / ".build" / "harness2_ab",
        help="Directory for staged Harness² surface and A/B run outputs.",
    )
    parser.add_argument(
        "--run-eval",
        action="store_true",
        help="Also invoke Harvey LAB `evaluation/run_eval.py` after both agent trajectories complete.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Stage the self-contained Harness² surface and print commands without calling LLM APIs.",
    )
    args = parser.parse_args()

    staged_harness = stage_self_contained_harness(args.output_dir / "claimlayer_harness_surface")
    baseline_out = args.output_dir / "runs" / "baseline"
    claimlayer_out = args.output_dir / "runs" / "claimlayer_v3"

    lab_root = args.lab_root.resolve()
    run_opencode = lab_root / "opencode" / "run_opencode.py"
    run_eval = lab_root / "evaluation" / "run_eval.py"

    baseline_cmd = [
        sys.executable,
        str(run_opencode),
        "--lab-root",
        str(lab_root),
        "--task",
        args.task,
        "--model",
        args.model,
        "--output-dir",
        str(baseline_out),
    ]
    claimlayer_cmd = [
        *baseline_cmd[:-1],
        str(claimlayer_out),
        "--harness-dir",
        str(staged_harness),
    ]

    summary = {
        "task": args.task,
        "staged_harness_dir": str(staged_harness),
        "bundled_files": sorted(
            str(p.relative_to(staged_harness)) for p in staged_harness.rglob("*") if p.is_file()
        ),
        "commands": {
            "baseline": " ".join(baseline_cmd),
            "claimlayer_v3": " ".join(claimlayer_cmd),
        },
    }

    if args.dry_run:
        print(json.dumps(summary, indent=2))
        return 0

    if not run_opencode.is_file():
        print(
            f"Error: Harvey LAB runner not found at '{run_opencode}'.\n"
            "Clone https://github.com/harveyai/harvey-labs and pass `--lab-root /path/to/harvey-labs`, "
            "or run `--dry-run` / `replay_om_vs_indenture.py` for offline verification.",
            file=sys.stderr,
        )
        return 1

    env = dict(os.environ)
    env["LAB_BENCH_ROOT"] = str(lab_root)
    env["CLAIMLAYER_ROOT"] = str(CLAIMLAYER_ROOT)

    print(f"[1/2] Running Baseline OpenCode agent on {args.task}...")
    subprocess.run(baseline_cmd, env=env, check=True)

    print(f"[2/2] Running ClaimLayer v3 Harness² surface on {args.task}...")
    subprocess.run(claimlayer_cmd, env=env, check=True)

    if args.run_eval and run_eval.is_file():
        for label, out_dir in [("baseline", baseline_out), ("claimlayer_v3", claimlayer_out)]:
            print(f"[eval] Scoring {label} outputs...")
            subprocess.run(
                [sys.executable, str(run_eval), "--lab-root", str(lab_root), "--run-dir", str(out_dir)],
                env=env,
                check=True,
            )

    print(json.dumps({"status": "completed", **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
