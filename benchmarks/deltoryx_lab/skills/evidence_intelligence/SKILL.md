---
name: evidence_intelligence
description: Deterministic Evidence Intelligence v2.0 workflow using ClaimLayer, OriginTier source hierarchy, EpistemicJudge, Jøsang Subjective Logic, Cross-Document Redline Diffing, and DELTORYX-MERKLE-SHA256-v2 audit certificates.
---

# Deltoryx Evidence Intelligence v2.0 (`evidence_intelligence`)

## Overview
This skill equips the legal agent with **Deltoryx v2.0**, a deterministic epistemic engine combining:
- **`OriginTier` Source Hierarchy**: Ranks primary controlling instruments (`PRIMARY_DOCUMENT`, rank 100), competing markups/annexes (`SECONDARY_ANNEX`, rank 50), and external emails/notes (`EXTERNAL_INJECTED`, rank 10).
- **Automated Cross-Document Diff & Redline Matrix**: Aligns baseline drafts against counterparty markups (or indentures against offering memoranda) to surface every modified number, percentage, ratio, date, definition, and clause.
- **Quantitative & Financial Reconciliation**: Extracts `.xlsx` financial tables and isolates units (`$`, `%`, `x` multiples, `days`) to prevent unit-mixing and arithmetic errors.
- **Cryptographic Audit Certificate (`DELTORYX-MERKLE-SHA256-v2`)**: Verifies deliverable completeness, section coverage, and SHA-256 Merkle integrity before task completion.

## Mandatory Execution Commands

1. **Corpus Indexing & Diff Generation (Run First)**:
   ```bash
   python3 scripts/deltoryx_audit.py index documents
   ```
   Inspect the printed Dossier and read `.deltoryx/parsed/*.txt` to ensure 100% coverage of all sections in both the baseline and competing documents.

2. **Deliverable Verification & Merkle Certification (Run Before Finishing)**:
   ```bash
   python3 scripts/deltoryx_audit.py verify output
   ```
   Confirm that every deliverable in `output/` parses cleanly, addresses all modified sections, and receives a `VERIFIED` `DELTORYX-MERKLE-SHA256-v2` certificate.
