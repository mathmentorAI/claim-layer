#!/usr/bin/env python3
"""Controlled A/B Benchmark Runner for Harvey LAB: Baseline (Vanilla OpenCode/Harness2) vs. Deltoryx v2.0.

Executes paired rollouts on Harvey LAB tasks and grades them with LAB's official `evaluation.run_eval` judge.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import pathlib
import subprocess
import sys
import time
from typing import Any

ROOT = pathlib.Path("/Users/franciscohdb/Documents/Deltoryx Platform v1")
HARNESS2_DIR = ROOT / "benchmarks" / "harness2"
LAB_REPO = HARNESS2_DIR / "dependencies" / "harvey-labs"
LAB_PYTHON = LAB_REPO / ".venv" / "bin" / "python"
OPENCODE_DIR = HARNESS2_DIR / "dependencies" / "opencode"
BUN_BIN = HARNESS2_DIR / "dependencies" / "tools" / "node_modules" / ".bin" / "bun"
DELTORYX_HARNESS_DIR = ROOT / "benchmarks" / "deltoryx_lab"
RESULTS_ROOT = ROOT / "benchmarks" / "ab_results"

DEFAULT_TASKS = [
    "litigation-dispute-resolution/analyze-counterparty-motion-to-dismiss",
    "structured-finance-securitization/compare-offering-memorandum-against-indenture",
    "corporate-ma/analyze-counterparty-spa-markup",
    "banking-finance/analyze-counterparty-markup-of-senior-secured-credit-facility-term-sheet",
]


def load_openai_key() -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return os.environ["OPENAI_API_KEY"]
    env_file = pathlib.Path("/Users/franciscohdb/Documents/MathMentorEI/.env")
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            if line.strip().startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("OPENAI_API_KEY not found")


def get_env() -> dict[str, str]:
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = load_openai_key()
    env["PYTHONPATH"] = f"{LAB_REPO}:{ROOT}:{ROOT / 'claim-layer' / 'src'}"
    env["PATH"] = f"{LAB_PYTHON.parent}:{BUN_BIN.parent}:/opt/homebrew/bin:{env.get('PATH', '')}"
    env["LAB_DOC_PARSER"] = "host"
    return env


def run_single_arm(
    task_id: str,
    arm: str,
    model: str,
    judge_model: str,
    timeout: int = 900,
) -> dict[str, Any]:
    """Run one (task_id, arm) rollout and score it with evaluation.run_eval."""
    slug = task_id.replace("/", "__")
    run_id = f"{slug}/{arm}"
    run_dir = RESULTS_ROOT / run_id
    scores_file = run_dir / "scores.json"
    metrics_file = run_dir / "metrics.json"

    env = get_env()
    t0 = time.time()

    # 1. Execute rollout if not already completed with deliverable
    output_dir = run_dir / "output"
    has_deliverable = output_dir.is_dir() and any(
        p.is_file() for p in output_dir.rglob("*") if not p.name.startswith(".")
    )
    if not (metrics_file.is_file() and has_deliverable):
        print(f"[START ROLLOUT] {task_id} | arm={arm} | model={model}", flush=True)
        cmd = [
            str(LAB_PYTHON),
            "-u",
            str(LAB_REPO / "opencode" / "run_opencode.py"),
            "--task",
            task_id,
            "--run-id",
            run_id,
            "--results-root",
            str(RESULTS_ROOT),
            "--model",
            model,
            "--tool-mode",
            "base",
            "--skill-mode",
            "native",
            "--doc-parser",
            "host",
            "--timeout",
            str(timeout),
            "--max-turns",
            "80",
            "--max-continue",
            "1",
            "--opencode-dir",
            str(OPENCODE_DIR),
            "--bun",
            str(BUN_BIN),
        ]
        if arm == "deltoryx_v2":
            cmd += ["--harness-dir", str(DELTORYX_HARNESS_DIR)]

        run_dir.mkdir(parents=True, exist_ok=True)
        runner_log = run_dir / "runner_stdout.log"
        with runner_log.open("w", encoding="utf-8") as lf:
            proc = subprocess.run(
                cmd,
                cwd=str(LAB_REPO),
                env=env,
                stdout=lf,
                stderr=subprocess.STDOUT,
                timeout=timeout + 120,
            )
        print(
            f"[DONE ROLLOUT]  {task_id} | arm={arm} | rc={proc.returncode} | {time.time() - t0:.1f}s",
            flush=True,
        )
    else:
        print(f"[CACHED ROLLOUT] {task_id} | arm={arm}", flush=True)

    # If deltoryx_v2 arm produced deliverables, ensure post-hoc Merkle verification certificate is recorded
    cert_path = run_dir / "workspace" / ".deltoryx" / "merkle_certificate.json"
    if arm == "deltoryx_v2" and not cert_path.is_file() and output_dir.is_dir():
        subprocess.run(
            [
                str(LAB_PYTHON),
                str(DELTORYX_HARNESS_DIR / "scripts" / "deltoryx_audit.py"),
                "verify",
                str(output_dir),
            ],
            cwd=str(run_dir / "workspace"),
            env=env,
            capture_output=True,
        )

    # 2. Run official LAB Rubric Judge (evaluation.run_eval)
    if not scores_file.is_file():
        print(f"[START JUDGE]   {task_id} | arm={arm} | judge={judge_model}", flush=True)
        j_cmd = [
            str(LAB_PYTHON),
            "-u",
            "-m",
            "evaluation.run_eval",
            "--run-id",
            str(run_dir.resolve()),
            "--task",
            task_id,
            "--judge-model",
            judge_model,
        ]
        judge_log = run_dir / "judge.log"
        with judge_log.open("w", encoding="utf-8") as jf:
            j_proc = subprocess.run(
                j_cmd,
                cwd=str(LAB_REPO),
                env=env,
                stdout=jf,
                stderr=subprocess.STDOUT,
                timeout=900,
            )
        print(
            f"[DONE JUDGE]    {task_id} | arm={arm} | rc={j_proc.returncode}",
            flush=True,
        )

    metrics = json.loads(metrics_file.read_text()) if metrics_file.is_file() else {}
    scores = json.loads(scores_file.read_text()) if scores_file.is_file() else {}
    cert = json.loads(cert_path.read_text()) if cert_path.is_file() else None

    n_passed = scores.get("n_passed", 0)
    n_criteria = scores.get("n_criteria", 0)
    partial_rate = round(100.0 * n_passed / n_criteria, 2) if n_criteria else 0.0

    return {
        "task_id": task_id,
        "arm": arm,
        "n_passed": n_passed,
        "n_criteria": n_criteria,
        "partial_pct": partial_rate,
        "all_pass": scores.get("all_pass", False),
        "turn_count": metrics.get("turn_count", 0),
        "tool_calls": metrics.get("tool_calls", 0),
        "wall_clock_seconds": metrics.get("wall_clock_seconds", 0.0),
        "total_tokens": metrics.get("total_tokens", 0),
        "cost_usd": metrics.get("cost_usd", 0.0),
        "component_use": metrics.get("harness_component_use", {}),
        "merkle_root": cert.get("merkle_root") if cert else None,
        "merkle_verified": cert.get("verified") if cert else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tasks", nargs="*", default=DEFAULT_TASKS)
    ap.add_argument("--arms", nargs="*", default=["baseline", "deltoryx_v2"])
    ap.add_argument("--model", default="openai/gpt-4.1")
    ap.add_argument("--judge-model", default="gpt-4.1")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args()

    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    jobs = [(t, arm) for t in args.tasks for arm in args.arms]
    results: list[dict[str, Any]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {
            pool.submit(
                run_single_arm, t, arm, args.model, args.judge_model, args.timeout
            ): (t, arm)
            for t, arm in jobs
        }
        for fut in concurrent.futures.as_completed(futs):
            t, arm = futs[fut]
            try:
                res = fut.result()
                results.append(res)
                print(
                    f"==> RESULT [{t}] ({arm}): {res['n_passed']}/{res['n_criteria']} ({res['partial_pct']}%) | turns={res['turn_count']} | time={res['wall_clock_seconds']}s",
                    flush=True,
                )
            except Exception as exc:
                print(f"==> ERROR [{t}] ({arm}): {exc}", file=sys.stderr, flush=True)

    summary_path = RESULTS_ROOT / "ab_summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved summary to {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
