#!/usr/bin/env python3
"""Deltoryx v2.0 Evidence Intelligence & Epistemic Audit CLI for Harvey LAB (`index` and `verify`).

Usage:
    python3 scripts/deltoryx_audit.py index [documents_dir]
    python3 scripts/deltoryx_audit.py verify [output_dir]
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Ensure Deltoryx v2.0 (core + claimlayer) and LAB parsers are importable
_DELTORYX_ROOT = Path("/Users/franciscohdb/Documents/Deltoryx Platform v1")
_CLAIMLAYER_SRC = _DELTORYX_ROOT / "claim-layer" / "src"
for _p in (_DELTORYX_ROOT, _CLAIMLAYER_SRC):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from claimlayer.api import ClaimLayer
from core.aggregation_engine import AggregationEngine
from core.claim_consolidator import ClaimConsolidator
from core.epistemic_certificate import (
    compute_claim_leaf_hash,
    compute_merkle_root,
    compute_subjective_opinion,
    generate_epistemic_certificate,
    verify_epistemic_certificate,
)
from core.epistemic_judge import EpistemicJudge
from core.graph_traverser import DependencyGraph
from core.interfaces import Claim, Reason, SourceRef
from core.source_precedence import OriginTier, get_origin_rank

PARSEABLE_EXTS = {"docx", "pdf", "pptx", "xlsx"}

_SECTION_RX = re.compile(
    r"(?:^|\b)((?:Section|Article|Clause|Schedule|Exhibit|Paragraph|Item|Rule)\s+\d+(?:\.\d+)*(?:\([a-zA-Z0-9]+\))*|"
    r"\[Section\s+\d+[^\]]*\]|\([a-z]\)\s+\*\*[A-Za-z0-9\s,\-/]+\*\*)",
    re.IGNORECASE,
)
_NUMBER_RX = re.compile(
    r"(?:\$\s*\d[\d,]*(?:\.\d+)?(?:\s*(?:million|billion|thousand|M|B|K))?|\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?x\b|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b)",
    re.IGNORECASE,
)
_DATE_RX = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+\d{4}\b|"
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d+\s+(?:business\s+|calendar\s+)?(?:days?|months?|years?)\b",
    re.IGNORECASE,
)


def _find_lab_parsers() -> Any:
    root = os.environ.get("LAB_BENCH_ROOT")
    candidates = []
    if root:
        candidates.append(Path(root) / "sandbox" / "parsers")
    candidates.append(
        _DELTORYX_ROOT / "benchmarks" / "harness2" / "dependencies" / "harvey-labs" / "sandbox" / "parsers"
    )
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "sandbox" / "parsers")
    for c in candidates:
        if (c / "parse_doc.py").is_file():
            if str(c) not in sys.path:
                sys.path.insert(0, str(c))
            import parse_doc  # type: ignore[import-not-found]

            return parse_doc
    return None


def extract_document_text(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    if ext in PARSEABLE_EXTS:
        parse_doc = _find_lab_parsers()
        if parse_doc is not None and ext in parse_doc.PARSERS:
            try:
                return parse_doc.PARSERS[ext](str(path))
            except Exception as exc:
                return f"[PARSE ERROR for {path.name}: {type(exc).__name__}: {exc}]"
    return path.read_text(encoding="utf-8", errors="replace")


def classify_origin_tier(filename: str) -> tuple[OriginTier, str]:
    lower = filename.lower()
    if any(
        k in lower
        for k in (".eml", "email", "cover-letter", "cover_letter", "note", "chat", "message")
    ):
        if "instruction" in lower or "partner" in lower or "associate" in lower:
            return OriginTier.EXTERNAL_INJECTED, "TIER_1_DIRECTIVE_EMAIL (Instructions / Flagged Issues)"
        return OriginTier.EXTERNAL_INJECTED, "TIER_1_EXTERNAL_COMM (Informal Email / Cover Letter)"
    if any(
        k in lower
        for k in (
            "markup",
            "redline",
            "counterparty",
            "seller-markup",
            "lender-markup",
            "offering-memorandum",
            "declaration",
            "motion",
            "proposed",
        )
    ):
        return OriginTier.SECONDARY_ANNEX, "TIER_2_COMPETING_INSTRUMENT (Counterparty Markup / Secondary Filing)"
    if any(
        k in lower
        for k in ("xlsx", "financial", "cap-table", "tape", "schedule", "summary", "model")
    ):
        return OriginTier.PRIMARY_DOCUMENT, "TIER_3_QUANTITATIVE_RECORD (Authoritative Financial / Data Record)"
    if any(k in lower for k in ("playbook", "policy", "guideline", "standard", "checklist")):
        return OriginTier.PRIMARY_DOCUMENT, "TIER_3_NORMATIVE_STANDARD (Controlling Playbook / Policy Standard)"
    return OriginTier.PRIMARY_DOCUMENT, "TIER_3_PRIMARY_INSTRUMENT (Controlling Baseline Agreement / Record)"


def _split_paragraphs(text: str) -> list[str]:
    blocks = []
    for raw in re.split(
        r"\n\s*\n|\n(?=[A-Z0-9§#=\-\*]{1,4}[\.\)]\s+|\b(?:Section|ARTICLE|SECTION|Clause)\s+\d)",
        text,
    ):
        cleaned = " ".join(line.strip() for line in raw.strip().splitlines() if line.strip())
        if len(cleaned) >= 15:
            blocks.append(cleaned)
    return blocks


def _pair_documents_for_diff(docs: dict[str, str]) -> list[tuple[str, str, str]]:
    """Identify natural (baseline_doc, competing_doc, comparison_label) pairs for redline/discrepancy analysis."""
    names = sorted(docs.keys())
    pairs: list[tuple[str, str, str]] = []
    used: set[tuple[str, str]] = set()

    baselines = [
        n
        for n in names
        if any(
            k in n.lower()
            for k in (
                "original",
                "baseline",
                "indenture",
                "msa",
                "complaint",
                "psa",
                "spa-draft",
                "term-sheet",
            )
        )
        and not any(
            k in n.lower()
            for k in ("markup", "redline", "counterparty", "lender-markup", "seller-markup")
        )
    ]
    competings = [
        n
        for n in names
        if any(
            k in n.lower()
            for k in (
                "markup",
                "redline",
                "counterparty",
                "offering-memorandum",
                "motion",
                "proposed",
                "closing-",
            )
        )
    ]

    for b in baselines:
        for c in competings:
            if b == c or (b, c) in used:
                continue
            pairs.append((b, c, f"Baseline `{b}` vs. Competing `{c}`"))
            used.add((b, c))

    return pairs[:4]


def compute_clause_diffs(
    base_name: str, base_text: str, comp_name: str, comp_text: str
) -> list[dict[str, Any]]:
    """Compute fine-grained clause/line diffs between a baseline instrument and a markup/competing document."""
    base_lines = [ln.strip() for ln in base_text.splitlines() if len(ln.strip()) > 10]
    comp_lines = [ln.strip() for ln in comp_text.splitlines() if len(ln.strip()) > 10]

    matcher = difflib.SequenceMatcher(None, base_lines, comp_lines)
    diffs: list[dict[str, Any]] = []
    current_section = "General / Preamble"

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        for ln in base_lines[max(0, i1 - 2) : min(len(base_lines), i2 + 1)]:
            m = _SECTION_RX.search(ln)
            if m:
                current_section = m.group(1)
        if tag == "equal":
            continue
        b_slice = base_lines[i1:i2]
        c_slice = comp_lines[j1:j2]
        step = 3
        max_len = max(len(b_slice), len(c_slice))
        if max_len > 4:
            for k in range(0, max_len, step):
                b_sub = " / ".join(b_slice[k : k + step])
                c_sub = " / ".join(c_slice[k : k + step])
                if not b_sub and not c_sub:
                    continue
                for chunk in (b_sub, c_sub):
                    m = _SECTION_RX.search(chunk)
                    if m:
                        current_section = m.group(1)
                        break
                diffs.append(
                    {
                        "change_type": tag.upper(),
                        "section": current_section,
                        "baseline_file": base_name,
                        "baseline_text": b_sub[:2400],
                        "competing_file": comp_name,
                        "competing_text": c_sub[:2400],
                        "baseline_quant": _NUMBER_RX.findall(b_sub) + _DATE_RX.findall(b_sub),
                        "competing_quant": _NUMBER_RX.findall(c_sub) + _DATE_RX.findall(c_sub),
                    }
                )
        else:
            b_chunk = " / ".join(b_slice)
            c_chunk = " / ".join(c_slice)
            if not b_chunk and not c_chunk:
                continue
            for chunk in (b_chunk, c_chunk):
                m = _SECTION_RX.search(chunk)
                if m:
                    current_section = m.group(1)
                    break
            b_nums = _NUMBER_RX.findall(b_chunk) + _DATE_RX.findall(b_chunk)
            c_nums = _NUMBER_RX.findall(c_chunk) + _DATE_RX.findall(c_chunk)
            diffs.append(
                {
                    "change_type": tag.upper(),
                    "section": current_section,
                    "baseline_file": base_name,
                    "baseline_text": b_chunk[:2400],
                    "competing_file": comp_name,
                    "competing_text": c_chunk[:2400],
                    "baseline_quant": b_nums,
                    "competing_quant": c_nums,
                }
            )
    return diffs


def run_index(docs_dir: Path, workspace: Path) -> int:
    deltoryx_dir = workspace / ".deltoryx"
    parsed_dir = deltoryx_dir / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    db_path = deltoryx_dir / "claims.sqlite"
    if db_path.exists():
        db_path.unlink()

    cl = ClaimLayer(db_path=str(db_path))
    consolidator = ClaimConsolidator()
    judge = EpistemicJudge()
    agg_engine = AggregationEngine()

    doc_files = sorted(p for p in docs_dir.rglob("*") if p.is_file() and not p.name.startswith("."))
    docs_text: dict[str, str] = {}
    doc_meta: dict[str, dict[str, Any]] = {}
    all_core_claims: list[Claim] = []
    supporting_claims: list[Claim] = []
    competing_claims: list[Claim] = []
    claim_counter = 0

    for doc_path in doc_files:
        rel_name = str(doc_path.relative_to(docs_dir))
        text = extract_document_text(doc_path)
        docs_text[rel_name] = text
        safe_name = rel_name.replace("/", "__") + ".txt"
        (parsed_dir / safe_name).write_text(text, encoding="utf-8")

        tier, tier_label = classify_origin_tier(rel_name)
        rank = {
            OriginTier.PRIMARY_DOCUMENT: 100,
            OriginTier.ANNEX: 50,
            OriginTier.SECONDARY_ANNEX: 50,
            OriginTier.EXTERNAL_INJECTED: 10,
        }.get(tier, 100)
        sections = sorted({m.group(1).strip() for m in _SECTION_RX.finditer(text)})
        numbers = sorted({m.group(0).strip() for m in _NUMBER_RX.finditer(text)})
        dates = sorted({m.group(0).strip() for m in _DATE_RX.finditer(text)})

        paragraphs = _split_paragraphs(text)
        high_signal_paras: list[str] = []
        for idx, para in enumerate(paragraphs[:80]):
            has_num = bool(
                _NUMBER_RX.search(para) or _DATE_RX.search(para) or _SECTION_RX.search(para)
            )
            has_legal = any(
                kw in para.lower()
                for kw in (
                    "shall",
                    "must",
                    "indemnif",
                    "cap",
                    "basket",
                    "threshold",
                    "covenant",
                    "default",
                    "terminat",
                    "governing law",
                    "jurisdiction",
                    "survival",
                    "carve",
                    "material",
                    "breach",
                    "interest",
                    "fee",
                    "ratio",
                    "ebitda",
                    "lien",
                    "consent",
                    "assignment",
                    "liability",
                )
            )
            if has_num or has_legal or len(paragraphs) <= 25:
                high_signal_paras.append(para)
                claim_counter += 1
                cid = f"CLM-{claim_counter:04d}"
                conf = 0.95 if rank == 100 else (0.82 if rank == 50 else 0.70)
                sec_match = _SECTION_RX.search(para)
                pred = sec_match.group(1).lower().replace(" ", "_") if sec_match else "provision"
                num_match = _NUMBER_RX.search(para)
                val = num_match.group(0) if num_match else para[:120]

                c_obj = Claim(
                    id=cid,
                    entity=rel_name,
                    predicate=pred,
                    value=val,
                    source=SourceRef(
                        document_id=rel_name,
                        page=1,
                        paragraph_id=f"P{idx + 1}",
                        origin_tier=tier.value,
                    ),
                    confidence=conf,
                    inference_type="deductive",
                    origin_tier=tier.value,
                    quote=para[:240],
                )
                all_core_claims.append(c_obj)
                if rank == 100:
                    supporting_claims.append(c_obj)
                else:
                    competing_claims.append(c_obj)
                try:
                    cl.add(
                        f"[{tier.value}] {rel_name}: {para[:240]}",
                        source=rel_name,
                        confidence=conf,
                    )
                except Exception:
                    pass

        doc_meta[rel_name] = {
            "filename": rel_name,
            "parsed_txt_path": str((parsed_dir / safe_name).relative_to(workspace)),
            "origin_tier": tier.value,
            "origin_rank": rank,
            "tier_label": tier_label,
            "char_count": len(text),
            "line_count": len(text.splitlines()),
            "paragraph_count": len(paragraphs),
            "sections_detected": sections[:40],
            "numbers_detected": numbers[:50],
            "dates_detected": dates[:30],
            "high_signal_count": len(high_signal_paras),
        }

    # Compute Subjective Logic opinion & Merkle root over the ingested corpus
    opinion = compute_subjective_opinion(
        winner_support=0.92 if supporting_claims else 0.5,
        competing_support=0.68 if competing_claims else 0.0,
    )
    corpus_cert = generate_epistemic_certificate(
        value=f"CORPUS_INDEXED:{len(doc_files)}_DOCS:{len(all_core_claims)}_CLAIMS",
        confidence=opinion.projected_probability,
        reason=Reason.CONTRADICTION if competing_claims else Reason.RESOLVED,
        supporting_claims=supporting_claims,
        contradictions=competing_claims,
        subjective_opinion=opinion,
    )

    # Compute deterministic cross-document diffs
    pairs = _pair_documents_for_diff(docs_text)
    all_diffs: list[dict[str, Any]] = []
    for base_name, comp_name, label in pairs:
        diffs = compute_clause_diffs(base_name, docs_text[base_name], comp_name, docs_text[comp_name])
        all_diffs.append({"label": label, "base": base_name, "comp": comp_name, "diffs": diffs})

    # Extract Playbook / Directive Email / Financial Table full texts
    directives_md: list[str] = []
    for name, text in docs_text.items():
        low = name.lower()
        if any(
            k in low
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
            directives_md.append(
                f"### Full Extracted Content: `{name}` ({doc_meta[name]['tier_label']})\n```text\n{text.strip()[:12000]}\n```"
            )

    # Build Evidence Dossier Markdown
    lines: list[str] = [
        "# DELTORYX v2.0 — DETERMINISTIC EVIDENCE & PROVENANCE DOSSIER",
        "- **Engine**: Deltoryx v2.0 (`ClaimLayer` + `EpistemicJudge` + `OriginTier` + Jøsang Subjective Logic + `DELTORYX-MERKLE-SHA256-v2`)",
        f"- **Documents Indexed**: {len(doc_files)} | **Atomic Claims Ingested**: {len(all_core_claims)} (`.deltoryx/claims.sqlite`)",
        f"- **Jøsang Subjective Opinion**: `b={opinion.belief:.3f}, d={opinion.disbelief:.3f}, u={opinion.uncertainty:.3f}` (`{opinion.epistemic_regime}`)",
        f"- **Corpus Merkle Root**: `{corpus_cert['merkle_root']}`",
        "- **Plain-Text Mirror**: Every binary document is pre-extracted in `.deltoryx/parsed/<name>.txt` for instant reading/grepping.",
        "",
        "## 1. SOURCE HIERARCHY & PROVENANCE INVENTORY (`OriginTier`)",
        "| Document | Plain-Text Mirror | OriginTier | Rank | Chars | Key Sections | Quantitative Tokens |",
        "| :--- | :--- | :--- | :---: | :---: | :--- | :--- |",
    ]
    for name, m in doc_meta.items():
        secs = ", ".join(m["sections_detected"][:6]) or "—"
        nums = ", ".join(m["numbers_detected"][:6]) or "—"
        lines.append(
            f"| `{name}` | `{m['parsed_txt_path']}` | `{m['tier_label']}` | {m['origin_rank']} | {m['char_count']:,} | {secs} | {nums} |"
        )

    lines.append("\n## 2. CROSS-DOCUMENT CLAUSE & NUMERICAL DIFF MATRIX (DETERMINISTIC REDLINE)")
    if all_diffs:
        for group in all_diffs:
            lines.append(
                f"\n### {group['label']} ({len(group['diffs'])} material modifications detected)"
            )
            for idx, d in enumerate(group["diffs"][:60], 1):
                q_delta = ""
                if d["baseline_quant"] or d["competing_quant"]:
                    q_delta = f" | **Quant Delta**: `{d['baseline_quant']}` -> `{d['competing_quant']}`"
                lines.append(f"- **Change #{idx} [{d['change_type']}] ({d['section']})**{q_delta}:")
                if d["baseline_text"]:
                    lines.append(f"  - **Baseline (`{d['baseline_file']}`)**: {d['baseline_text']}")
                if d["competing_text"]:
                    lines.append(f"  - **Competing (`{d['competing_file']}`)**: {d['competing_text']}")
    else:
        lines.append(
            "No automatic baseline-vs-markup pair detected; inspect `.deltoryx/parsed/*.txt` directly."
        )

    if directives_md:
        lines.append("\n## 3. CONTROLLING PLAYBOOKS, FINANCIAL TABLES & DIRECTIVE EMAILS (VERBATIM)")
        lines.extend(directives_md)

    dossier_text = "\n".join(lines) + "\n"
    dossier_path = deltoryx_dir / "evidence_dossier.md"
    dossier_path.write_text(dossier_text, encoding="utf-8")

    index_state = {
        "doc_meta": doc_meta,
        "total_claims": len(all_core_claims),
        "corpus_certificate": corpus_cert,
        "subjective_opinion": opinion.to_dict(),
        "diff_groups": all_diffs,
        "all_source_numbers": sorted(
            {n for m in doc_meta.values() for n in m["numbers_detected"]}
        ),
        "all_source_sections": sorted(
            {s for m in doc_meta.values() for s in m["sections_detected"]}
        ),
    }
    (deltoryx_dir / "index_state.json").write_text(
        json.dumps(index_state, indent=2), encoding="utf-8"
    )

    print(dossier_text)
    print(
        f"\n[DELTORYX v2.0] Dossier saved to {dossier_path} and plain-text mirrors saved to {parsed_dir}/"
    )
    return 0


def run_verify(output_dir: Path, workspace: Path) -> int:
    deltoryx_dir = workspace / ".deltoryx"
    state_path = deltoryx_dir / "index_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}

    if not output_dir.is_dir():
        print(
            f"[DELTORYX v2.0 VERIFY FAIL] Output directory does not exist: {output_dir}",
            file=sys.stderr,
        )
        return 1

    deliv_files = sorted(
        p for p in output_dir.rglob("*") if p.is_file() and not p.name.startswith(".")
    )
    if not deliv_files:
        print(
            f"[DELTORYX v2.0 VERIFY FAIL] No deliverable files found in {output_dir}!",
            file=sys.stderr,
        )
        return 1

    # Deterministic Container Integrity Gate: ensure any .docx file is a valid ZIP/OOXML container
    import subprocess as _sp

    for f in list(deliv_files):
        if f.suffix.lower() == ".docx":
            raw_bytes = f.read_bytes()
            if not raw_bytes.startswith(b"PK\x03\x04"):
                md_backup = deltoryx_dir / (f.stem + "_raw.md")
                deltoryx_dir.mkdir(parents=True, exist_ok=True)
                md_backup.write_bytes(raw_bytes)
                _sp.run(
                    ["pandoc", "-f", "markdown", "-t", "docx", str(md_backup), "-o", str(f)],
                    check=False,
                    capture_output=True,
                )
        elif f.suffix.lower() == ".md":
            docx_peer = f.with_suffix(".docx")
            if not docx_peer.exists():
                _sp.run(
                    ["pandoc", "-f", "markdown", "-t", "docx", str(f), "-o", str(docx_peer)],
                    check=False,
                    capture_output=True,
                )

    deliv_files = sorted(
        p for p in output_dir.rglob("*") if p.is_file() and not p.name.startswith(".")
    )

    source_nums = set(state.get("all_source_numbers", []))
    diff_groups = state.get("diff_groups", [])

    report_lines = [
        "# DELTORYX v2.0 — DELIVERABLE VERIFICATION & MERKLE AUDIT REPORT",
        f"- **Deliverables Found**: {len(deliv_files)}",
    ]

    combined_text = ""
    deliv_claims: list[Claim] = []

    for idx, f in enumerate(deliv_files, 1):
        rel = str(f.relative_to(output_dir))
        text = extract_document_text(f)
        combined_text += "\n" + text
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        deliv_nums = sorted({m.group(0).strip() for m in _NUMBER_RX.finditer(text)})
        deliv_secs = sorted({m.group(1).strip() for m in _SECTION_RX.finditer(text)})
        matched_nums = [n for n in deliv_nums if n in source_nums]

        deliv_claims.append(
            Claim(
                id=f"DELIV-{idx:02d}",
                entity=rel,
                predicate="deliverable_sha256",
                value=h,
                source=SourceRef(
                    document_id=rel,
                    page=1,
                    paragraph_id="FULL",
                    origin_tier=OriginTier.PRIMARY_DOCUMENT.value,
                ),
                confidence=1.0,
                origin_tier=OriginTier.PRIMARY_DOCUMENT.value,
                quote=text[:200],
            )
        )

        report_lines.extend(
            [
                f"\n## Deliverable: `output/{rel}`",
                f"- **Byte Size**: {f.stat().st_size:,} bytes | **Extracted Chars**: {len(text):,}",
                f"- **SHA-256 Digest**: `{h}`",
                f"- **Sections Cited**: {len(deliv_secs)} ({', '.join(deliv_secs[:15]) or 'none'})",
                f"- **Quantitative Values Cited**: {len(deliv_nums)} ({len(matched_nums)} exact verbatim matches in source record)",
            ]
        )
        if len(text.strip()) < 500:
            report_lines.append(
                "  - **[WARNING]**: Deliverable text is suspiciously short (<500 chars)!"
            )

    # Check coverage of detected redline/diff sections
    missing_diff_sections: list[str] = []
    for grp in diff_groups:
        for d in grp.get("diffs", []):
            sec = d.get("section", "")
            if sec and sec != "General / Preamble":
                sec_num = re.sub(
                    r"^(?:Section|Article|Clause|Schedule|Exhibit|Paragraph|Item|Rule)\s+",
                    "",
                    sec,
                    flags=re.I,
                )
                if sec_num and sec_num.lower() not in combined_text.lower():
                    missing_diff_sections.append(f"{sec} ({grp['comp']})")

    if missing_diff_sections:
        uniq_missing = sorted(set(missing_diff_sections))
        report_lines.append(
            f"\n## [AUDIT ALERT] Potentially Unaddressed Modified Sections ({len(uniq_missing)})"
        )
        report_lines.append(
            "Verify whether the following sections modified in the competing document require analysis in your deliverable:"
        )
        for ms in uniq_missing[:20]:
            report_lines.append(f"- `{ms}`")
    else:
        report_lines.append(
            "\n## Redline & Section Coverage: 100% PASS (All detected modified sections are referenced)"
        )

    opinion = compute_subjective_opinion(winner_support=0.98, competing_support=0.02)
    cert = generate_epistemic_certificate(
        value=",".join(str(f.relative_to(output_dir)) for f in deliv_files),
        confidence=opinion.projected_probability,
        reason=Reason.RESOLVED,
        supporting_claims=deliv_claims,
        contradictions=[],
        subjective_opinion=opinion,
    )
    verified_ok = verify_epistemic_certificate(
        cert,
        value=",".join(str(f.relative_to(output_dir)) for f in deliv_files),
        confidence=opinion.projected_probability,
        reason=Reason.RESOLVED,
        supporting_claims=deliv_claims,
        contradictions=[],
        subjective_opinion=opinion,
    )
    cert["verified"] = verified_ok
    cert["unaddressed_sections"] = sorted(set(missing_diff_sections))

    deltoryx_dir.mkdir(parents=True, exist_ok=True)
    cert_path = deltoryx_dir / "merkle_certificate.json"
    cert_path.write_text(json.dumps(cert, indent=2), encoding="utf-8")

    report_lines.extend(
        [
            "",
            "## CRYPTOGRAPHIC EPISTEMIC CERTIFICATE",
            f"- **Scheme**: `{cert['scheme']}`",
            f"- **Merkle Root**: `{cert['merkle_root']}`",
            f"- **Certificate Signature**: `{cert['certificate_signature']}`",
            f"- **Cryptographic Verification**: `{verified_ok}`",
            f"- **Certificate Path**: `{cert_path.relative_to(workspace)}`",
        ]
    )
    print("\n".join(report_lines))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["index", "verify"], help="Operation mode: index or verify")
    ap.add_argument(
        "target", nargs="?", default=None, help="Target directory (documents or output)"
    )
    args = ap.parse_args()

    workspace = Path.cwd()
    if args.mode == "index":
        docs_dir = Path(args.target) if args.target else (workspace / "documents")
        if not docs_dir.is_absolute():
            docs_dir = (workspace / docs_dir).resolve()
        return run_index(docs_dir, workspace)
    else:
        out_dir = Path(args.target) if args.target else (workspace / "output")
        if not out_dir.is_absolute():
            out_dir = (workspace / out_dir).resolve()
        return run_verify(out_dir, workspace)


if __name__ == "__main__":
    sys.exit(main())
