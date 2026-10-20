#!/usr/bin/env python3
"""Direct LLM Tool-Calling Benchmark (No Agent Harness, No Bash):
Standard Chunk RAG Tools (`direct_rag`) vs. ClaimLayer/Deltoryx Evidence Tools (`direct_claimlayer`).

Implements the controlled comparison from Section 9.1 / Jose's methodology:
- Identical LLM (`nvidia/nemotron-3-super-120b-a12b`, temperature=0.0)
- Identical minimal system prompt (no 9,456-char harness prompt, no OpenCode, no bash)
- Identical tool-calling loop budget (max 6 tool rounds + final deliverable generation)
- Identical container generation (`pandoc` Markdown -> `.docx` with ZIP header verification)
- Identical judge across all 4 tasks (`evaluation.run_eval` with `nvidia/nemotron-3-super-120b-a12b`)
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import time
from collections import Counter
from typing import Any

import openai

DELTORYX_ROOT = pathlib.Path("/Users/franciscohdb/Documents/Deltoryx Platform v1")
CLAIMLAYER_REPO = pathlib.Path("/Users/franciscohdb/Documents/claim-layer")
HARNESS2_DIR = DELTORYX_ROOT / "benchmarks" / "harness2"
LAB_REPO = HARNESS2_DIR / "dependencies" / "harvey-labs"
LAB_PYTHON = LAB_REPO / ".venv" / "bin" / "python"
RESULTS_ROOT = CLAIMLAYER_REPO / "benchmarks" / "direct_tool_results"

for _p in (
    DELTORYX_ROOT,
    CLAIMLAYER_REPO / "src",
    CLAIMLAYER_REPO / "benchmarks" / "deltoryx_lab" / "scripts",
):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import deltoryx_audit as da  # noqa: E402

DEFAULT_TASKS = [
    "litigation-dispute-resolution/analyze-counterparty-motion-to-dismiss",
    "structured-finance-securitization/compare-offering-memorandum-against-indenture",
    "corporate-ma/analyze-counterparty-spa-markup",
    "banking-finance/analyze-counterparty-markup-of-senior-secured-credit-facility-term-sheet",
]

SYSTEM_PROMPT = """You are a senior legal and financial analyst.
You must complete the user's legal analysis task using ONLY the provided information-retrieval tools.
Do NOT invent facts, citations, numbers, or dates.

Workflow:
1. Call the provided tools across 2 to 5 rounds to inspect the case documents, compare provisions, check numerical/financial figures, and verify governing standards or instructions.
2. Once you have gathered comprehensive evidence covering all issues, write the complete, exhaustive final memorandum/report in well-structured Markdown (with clear headings, tables where helpful, exact section citations, exact dollar/percentage figures, and concrete recommendations/redline language).
3. Do NOT write a short summary or outline—write the full professional deliverable directly in your final response."""


def load_llm_env() -> dict[str, str]:
    env = os.environ.copy()
    env_file = pathlib.Path("/Users/franciscohdb/Documents/mathmentor2/.env")
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env["PYTHONPATH"] = f"{LAB_REPO}:{DELTORYX_ROOT}:{CLAIMLAYER_REPO / 'src'}"
    env["PATH"] = f"{LAB_PYTHON.parent}:/opt/homebrew/bin:{env.get('PATH', '')}"
    return env


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9§$%\.]+", text.lower())


def _bm25_score(
    query_tokens: list[str],
    doc_tokens_list: list[list[str]],
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    n_docs = len(doc_tokens_list)
    if n_docs == 0 or not query_tokens:
        return [0.0] * n_docs
    avgdl = sum(len(d) for d in doc_tokens_list) / max(1, n_docs)
    df: Counter[str] = Counter()
    for d in doc_tokens_list:
        for tok in set(d):
            df[tok] += 1
    scores = [0.0] * n_docs
    q_Unique = set(query_tokens)
    for i, d in enumerate(doc_tokens_list):
        dl = len(d)
        tf_map = Counter(d)
        s = 0.0
        for q in q_Unique:
            tf = tf_map.get(q, 0)
            if tf == 0:
                continue
            idf = math.log(1.0 + (n_docs - df[q] + 0.5) / (df[q] + 0.5))
            s += idf * (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * dl / max(1.0, avgdl)))
        scores[i] = s
    return scores


class DirectRagBackend:
    """Standard Chunk RAG backend: fixed-size overlapping chunks + BM25 search."""

    def __init__(self, docs_dir: pathlib.Path) -> None:
        self.docs_meta: list[dict[str, Any]] = []
        self.chunks: list[dict[str, Any]] = []
        self.chunk_tokens: list[list[str]] = []

        doc_files = sorted(
            p for p in docs_dir.rglob("*") if p.is_file() and not p.name.startswith(".")
        )
        for p in doc_files:
            rel = str(p.relative_to(docs_dir))
            text = da.extract_document_text(p)
            # Chunk into ~1200 char segments with 200 char overlap
            step = 1000
            size = 1200
            doc_chunks = []
            for idx, start in enumerate(range(0, max(1, len(text)), step)):
                snippet = text[start : start + size].strip()
                if not snippet:
                    continue
                c_obj = {
                    "filename": rel,
                    "chunk_index": idx,
                    "text": snippet,
                }
                doc_chunks.append(c_obj)
                self.chunks.append(c_obj)
                self.chunk_tokens.append(_tokenize(f"{rel} {snippet}"))
            self.docs_meta.append(
                {
                    "filename": rel,
                    "char_count": len(text),
                    "num_chunks": len(doc_chunks),
                }
            )

    def tools_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_documents",
                    "description": "List all source documents in the case and their chunk counts.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_chunks",
                    "description": "Search across document chunks using keyword/BM25 retrieval.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query terms."},
                            "filename_filter": {
                                "type": "string",
                                "description": "Optional substring to filter by document filename.",
                            },
                            "top_k": {
                                "type": "integer",
                                "description": "Max chunks to return (default 8, max 15).",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_chunk_window",
                    "description": "Read consecutive chunks from a specific document starting at start_chunk.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string", "description": "Exact document filename."},
                            "start_chunk": {"type": "integer", "description": "Starting chunk index (0-based)."},
                            "num_chunks": {"type": "integer", "description": "Number of chunks to read (max 5)."},
                        },
                        "required": ["filename", "start_chunk"],
                    },
                },
            },
        ]

    def execute_tool(self, name: str, args: dict[str, Any]) -> str:
        if name == "list_documents":
            return json.dumps({"documents": self.docs_meta}, indent=2)
        if name == "search_chunks":
            query = str(args.get("query", ""))
            flt = str(args.get("filename_filter", "")).lower().strip()
            top_k = min(15, max(1, int(args.get("top_k", 8) or 8)))
            q_toks = _tokenize(query)
            scores = _bm25_score(q_toks, self.chunk_tokens)
            ranked = sorted(
                range(len(self.chunks)),
                key=lambda i: scores[i],
                reverse=True,
            )
            results = []
            for i in ranked:
                c = self.chunks[i]
                if flt and flt not in c["filename"].lower():
                    continue
                results.append(
                    {
                        "filename": c["filename"],
                        "chunk_index": c["chunk_index"],
                        "score": round(scores[i], 3),
                        "text": c["text"],
                    }
                )
                if len(results) >= top_k:
                    break
            return json.dumps({"query": query, "results": results}, indent=2)
        if name == "read_chunk_window":
            fname = str(args.get("filename", "")).lower().strip()
            start = max(0, int(args.get("start_chunk", 0) or 0))
            count = min(5, max(1, int(args.get("num_chunks", 3) or 3)))
            matched = [
                c
                for c in self.chunks
                if c["filename"].lower() == fname or fname in c["filename"].lower()
            ]
            window = [c for c in matched if start <= c["chunk_index"] < start + count]
            return json.dumps({"filename": fname, "chunks": window}, indent=2)
        return json.dumps({"error": f"Unknown tool: {name}"})


class DirectClaimLayerBackend:
    """ClaimLayer / Deltoryx Structured Evidence Backend (OriginTier + Full Claim Units + Clause Diffs)."""

    def __init__(self, docs_dir: pathlib.Path) -> None:
        self.doc_meta: dict[str, dict[str, Any]] = {}
        self.claims: list[dict[str, Any]] = []
        self.claim_tokens: list[list[str]] = []
        self.diff_groups: list[dict[str, Any]] = []
        self.directives: dict[str, str] = {}

        docs_text: dict[str, str] = {}
        doc_files = sorted(
            p for p in docs_dir.rglob("*") if p.is_file() and not p.name.startswith(".")
        )
        cid_counter = 0
        for p in doc_files:
            rel = str(p.relative_to(docs_dir))
            text = da.extract_document_text(p)
            docs_text[rel] = text
            tier, tier_label = da.classify_origin_tier(rel)
            rank = {
                da.OriginTier.PRIMARY_DOCUMENT: 100,
                da.OriginTier.ANNEX: 50,
                da.OriginTier.SECONDARY_ANNEX: 50,
                da.OriginTier.EXTERNAL_INJECTED: 10,
            }.get(tier, 100)
            sections = sorted({m.group(1).strip() for m in da._SECTION_RX.finditer(text)})
            numbers = sorted({m.group(0).strip() for m in da._NUMBER_RX.finditer(text)})
            dates = sorted({m.group(0).strip() for m in da._DATE_RX.finditer(text)})

            paragraphs = da._split_paragraphs(text)
            for idx, para in enumerate(paragraphs):
                cid_counter += 1
                sec_m = da._SECTION_RX.search(para)
                sec = sec_m.group(1) if sec_m else "General"
                nums = da._NUMBER_RX.findall(para) + da._DATE_RX.findall(para)
                c_rec = {
                    "claim_id": f"CLM-{cid_counter:04d}",
                    "document": rel,
                    "origin_tier": tier.value,
                    "tier_label": tier_label,
                    "authority_rank": rank,
                    "paragraph_id": f"P{idx + 1}",
                    "section": sec,
                    "quantitative_values": nums[:10],
                    "text": para[:1500],
                }
                self.claims.append(c_rec)
                self.claim_tokens.append(
                    _tokenize(f"{rel} {sec} {' '.join(nums)} {para}")
                )

            self.doc_meta[rel] = {
                "filename": rel,
                "origin_tier": tier.value,
                "tier_label": tier_label,
                "authority_rank": rank,
                "paragraph_count": len(paragraphs),
                "sections_detected": sections[:35],
                "numbers_detected": numbers[:45],
                "dates_detected": dates[:25],
            }
            if any(
                k in rel.lower()
                for k in (
                    "playbook",
                    "email",
                    ".eml",
                    "instruction",
                    "cover-letter",
                    "xlsx",
                    "summary",
                    "cap-table",
                )
            ):
                self.directives[rel] = text[:14000]

        pairs = da._pair_documents_for_diff(docs_text)
        for base_name, comp_name, label in pairs:
            diffs = da.compute_clause_diffs(
                base_name, docs_text[base_name], comp_name, docs_text[comp_name]
            )
            self.diff_groups.append(
                {
                    "label": label,
                    "baseline_file": base_name,
                    "competing_file": comp_name,
                    "total_diffs": len(diffs),
                    "diffs": diffs,
                }
            )

    def tools_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_evidence_overview",
                    "description": (
                        "Return the ClaimLayer/Deltoryx source-authority inventory (OriginTier ranks, "
                        "detected sections, quantitative tokens), available redline diff pairs, and "
                        "controlling playbooks/directive emails/financial tables."
                    ),
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_clause_diffs",
                    "description": (
                        "Query the deterministic clause-by-clause redline diff matrix between "
                        "baseline governing agreements and counterparty markups/competing filings, "
                        "including exact quantitative deltas."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "filter_query": {
                                "type": "string",
                                "description": "Optional keyword or section filter (leave empty to get top material diffs).",
                            },
                            "offset": {
                                "type": "integer",
                                "description": "Starting diff index (default 0).",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Max diffs to return (default 30, max 50).",
                            },
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "query_claims_and_provisions",
                    "description": (
                        "Search structured claim units across documents with OriginTier source authority, "
                        "paragraph locators, section tags, and extracted numerical/date tokens."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query (section, concept, or figure)."},
                            "filename_filter": {
                                "type": "string",
                                "description": "Optional filename substring filter.",
                            },
                            "top_k": {
                                "type": "integer",
                                "description": "Number of claim units to return (default 10, max 20).",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
        ]

    def execute_tool(self, name: str, args: dict[str, Any]) -> str:
        if name == "get_evidence_overview":
            return json.dumps(
                {
                    "source_hierarchy_inventory": self.doc_meta,
                    "redline_diff_pairs": [
                        {
                            "label": g["label"],
                            "baseline_file": g["baseline_file"],
                            "competing_file": g["competing_file"],
                            "total_diffs": g["total_diffs"],
                        }
                        for g in self.diff_groups
                    ],
                    "controlling_playbooks_directives_and_tables": self.directives,
                },
                indent=2,
            )
        if name == "get_clause_diffs":
            fq = str(args.get("filter_query", "")).lower().strip()
            offset = max(0, int(args.get("offset", 0) or 0))
            limit = min(30, max(1, int(args.get("limit", 25) or 25)))
            out_groups = []
            for g in self.diff_groups:
                filtered = g["diffs"]
                if fq:
                    toks = _tokenize(fq)
                    filtered = [
                        d
                        for d in g["diffs"]
                        if any(
                            t in (d["section"] + " " + d["baseline_text"] + " " + d["competing_text"]).lower()
                            for t in toks
                        )
                    ]
                sliced = [
                    {
                        **d,
                        "baseline_text": d["baseline_text"][:700],
                        "competing_text": d["competing_text"][:700],
                    }
                    for d in filtered[offset : offset + limit]
                ]
                out_groups.append(
                    {
                        "label": g["label"],
                        "total_matching_diffs": len(filtered),
                        "returned_range": [offset, offset + len(sliced)],
                        "diffs": sliced,
                    }
                )
            return json.dumps({"diff_groups": out_groups}, indent=2)
        if name == "query_claims_and_provisions":
            query = str(args.get("query", ""))
            flt = str(args.get("filename_filter", "")).lower().strip()
            top_k = min(15, max(1, int(args.get("top_k", 10) or 10)))
            q_toks = _tokenize(query)
            scores = _bm25_score(q_toks, self.claim_tokens)
            ranked = sorted(
                range(len(self.claims)),
                key=lambda i: scores[i],
                reverse=True,
            )
            results = []
            for i in ranked:
                c = self.claims[i]
                if flt and flt not in c["document"].lower():
                    continue
                results.append({**c, "relevance_score": round(scores[i], 3)})
                if len(results) >= top_k:
                    break
            return json.dumps({"query": query, "claims": results}, indent=2)
        return json.dumps({"error": f"Unknown tool: {name}"})


def _chat_with_retry(client: openai.OpenAI, **kwargs: Any) -> Any:
    last_err: Exception | None = None
    for attempt in range(6):
        try:
            return client.chat.completions.create(
                **kwargs,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
        except Exception as exc:
            last_err = exc
            wait = min(25.0, 3.0 * (attempt + 1))
            time.sleep(wait)
    raise RuntimeError(f"LLM call failed after 6 attempts: {last_err}")


def convert_markdown_to_docx(md_text: str, out_docx: pathlib.Path) -> None:
    out_docx.parent.mkdir(parents=True, exist_ok=True)
    md_path = out_docx.with_suffix(".md")
    md_path.write_text(md_text, encoding="utf-8")
    subprocess.run(
        ["pandoc", str(md_path), "-o", str(out_docx)],
        check=True,
        capture_output=True,
    )
    # Verify ZIP header (PK\x03\x04)
    header = out_docx.read_bytes()[:4]
    if header != b"PK\x03\x04":
        raise RuntimeError(f"Generated {out_docx} is not a valid ZIP/DOCX container")


def run_direct_arm(
    task_id: str,
    arm: str,
    solver_model: str,
    judge_model: str,
    max_tool_rounds: int = 5,
    force: bool = False,
) -> dict[str, Any]:
    env = load_llm_env()
    slug = task_id.replace("/", "__")
    run_dir = RESULTS_ROOT / slug / arm
    output_dir = run_dir / "output"
    scores_file = run_dir / "scores.json"
    metrics_file = run_dir / "metrics.json"

    task_dir = LAB_REPO / "tasks" / task_id
    task_cfg = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    instructions = task_cfg["instructions"]
    deliverables = list(task_cfg.get("deliverables", {}).values())
    target_filename = deliverables[0] if deliverables else "report.docx"
    target_docx = output_dir / target_filename

    cached_valid = False
    if target_docx.is_file() and metrics_file.is_file() and not force:
        try:
            m_prev = json.loads(metrics_file.read_text(encoding="utf-8"))
            if m_prev.get("deliverable_chars", 0) >= 500:
                cached_valid = True
        except Exception:
            cached_valid = False

    if not cached_valid:
        if scores_file.exists():
            scores_file.unlink()
        print(f"[START DIRECT LLM] {task_id} | arm={arm} | model={solver_model}", flush=True)
        t0 = time.time()
        docs_dir = task_dir / "documents"
        backend: DirectRagBackend | DirectClaimLayerBackend
        if arm == "direct_rag":
            backend = DirectRagBackend(docs_dir)
        elif arm == "direct_claimlayer":
            backend = DirectClaimLayerBackend(docs_dir)
        else:
            raise ValueError(f"Unknown arm: {arm}")

        client = openai.OpenAI(
            base_url=env["LLM_BASE_URL"],
            api_key=env["LLM_API_KEY"],
            timeout=300.0,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"# Task Title: {task_cfg['title']}\n\n"
                    f"## Instructions\n{instructions}\n\n"
                    "Use the available tools to gather all relevant provisions, numbers, dates, and "
                    "discrepancies across the documents, then write the complete final memorandum in Markdown."
                ),
            },
        ]
        tools_schema = backend.tools_schema()
        input_tokens = 0
        output_tokens = 0
        tool_calls_count = 0
        rounds_used = 0
        trace_log: list[dict[str, Any]] = []
        final_markdown = ""

        for r_idx in range(max_tool_rounds):
            rounds_used = r_idx + 1
            resp = _chat_with_retry(
                client,
                model=solver_model,
                messages=messages,
                tools=tools_schema,
                tool_choice="auto",
                temperature=0.0,
                max_tokens=8192,
            )
            if resp.usage:
                input_tokens += resp.usage.prompt_tokens or 0
                output_tokens += resp.usage.completion_tokens or 0

            msg = resp.choices[0].message
            t_calls = msg.tool_calls or []
            if not t_calls:
                final_markdown = (msg.content or "").strip()
                trace_log.append(
                    {"round": r_idx + 1, "type": "final_answer", "chars": len(final_markdown)}
                )
                break

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in t_calls
                ],
            }
            messages.append(assistant_msg)

            for tc in t_calls:
                tool_calls_count += 1
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    fn_args = {}
                tool_out = backend.execute_tool(fn_name, fn_args)
                trace_log.append(
                    {
                        "round": r_idx + 1,
                        "tool": fn_name,
                        "args": fn_args,
                        "output_chars": len(tool_out),
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_out,
                    }
                )

        # If model used all tool rounds without emitting final prose, force final synthesis call
        if len(final_markdown) < 400:
            rounds_used += 1
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Now synthesize all gathered evidence and write the complete, exhaustive final "
                        "memorandum/report in Markdown covering every issue, section, numerical calculation, "
                        "and recommendation required by the instructions. Write only the Markdown report."
                    ),
                }
            )
            resp = _chat_with_retry(
                client,
                model=solver_model,
                messages=messages,
                tools=tools_schema,
                tool_choice="none",
                temperature=0.0,
                max_tokens=8192,
            )
            if resp.usage:
                input_tokens += resp.usage.prompt_tokens or 0
                output_tokens += resp.usage.completion_tokens or 0
            final_markdown = (resp.choices[0].message.content or "").strip()
            trace_log.append(
                {"round": rounds_used, "type": "forced_final_synthesis", "chars": len(final_markdown)}
            )

        elapsed = round(time.time() - t0, 2)
        run_dir.mkdir(parents=True, exist_ok=True)
        convert_markdown_to_docx(final_markdown, target_docx)

        metrics = {
            "task_id": task_id,
            "arm": arm,
            "solver_model": solver_model,
            "rounds_used": rounds_used,
            "tool_calls": tool_calls_count,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "wall_clock_seconds": elapsed,
            "deliverable_chars": len(final_markdown),
            "trace": trace_log,
        }
        metrics_file.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        print(
            f"[DONE DIRECT LLM]  {task_id} | arm={arm} | rounds={rounds_used} | tools={tool_calls_count} | "
            f"tokens={input_tokens + output_tokens:,} | chars={len(final_markdown):,} | {elapsed}s",
            flush=True,
        )
    else:
        print(f"[CACHED DIRECT LLM] {task_id} | arm={arm}", flush=True)

    # Grade with official LAB evaluator
    if not scores_file.is_file():
        print(f"[START JUDGE]      {task_id} | arm={arm} | judge={judge_model}", flush=True)
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
            "--parallel",
            "1",
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
            f"[DONE JUDGE]       {task_id} | arm={arm} | rc={j_proc.returncode}",
            flush=True,
        )

    metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
    scores = json.loads(scores_file.read_text(encoding="utf-8"))
    n_passed = scores.get("n_passed", 0)
    n_criteria = scores.get("n_criteria", 0)
    pct = round(100.0 * n_passed / n_criteria, 2) if n_criteria else 0.0

    return {
        "task_id": task_id,
        "arm": arm,
        "n_passed": n_passed,
        "n_criteria": n_criteria,
        "pass_pct": pct,
        "all_pass": scores.get("all_pass", False),
        "rounds_used": metrics.get("rounds_used", 0),
        "tool_calls": metrics.get("tool_calls", 0),
        "input_tokens": metrics.get("input_tokens", 0),
        "output_tokens": metrics.get("output_tokens", 0),
        "total_tokens": metrics.get("total_tokens", 0),
        "wall_clock_seconds": metrics.get("wall_clock_seconds", 0.0),
        "deliverable_chars": metrics.get("deliverable_chars", 0),
        "judge_model": judge_model,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tasks", nargs="*", default=DEFAULT_TASKS)
    ap.add_argument("--arms", nargs="*", default=["direct_rag", "direct_claimlayer"])
    ap.add_argument("--solver-model", default="nvidia/nemotron-3-super-120b-a12b")
    ap.add_argument("--judge-model", default="nvidia/nemotron-3-super-120b-a12b")
    ap.add_argument("--max-tool-rounds", type=int, default=5)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    jobs = [(t, arm) for t in args.tasks for arm in args.arms]
    results: list[dict[str, Any]] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {
            pool.submit(
                run_direct_arm,
                t,
                arm,
                args.solver_model,
                args.judge_model,
                args.max_tool_rounds,
                args.force,
            ): (t, arm)
            for t, arm in jobs
        }
        for fut in concurrent.futures.as_completed(futs):
            t, arm = futs[fut]
            try:
                res = fut.result()
                results.append(res)
                print(
                    f"==> RESULT [{t}] ({arm}): {res['n_passed']}/{res['n_criteria']} ({res['pass_pct']}%) | "
                    f"tools={res['tool_calls']} | tokens={res['total_tokens']:,} | time={res['wall_clock_seconds']}s",
                    flush=True,
                )
            except Exception as exc:
                print(f"==> ERROR [{t}] ({arm}): {exc}", file=sys.stderr, flush=True)

    summary_path = RESULTS_ROOT / "direct_tool_summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved summary to {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
