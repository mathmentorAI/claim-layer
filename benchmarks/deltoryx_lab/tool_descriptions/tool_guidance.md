# Tool & Epistemic Verification Workflow

1. **Step 1 — Run Deltoryx v2.0 Corpus Indexing (`deltoryx_audit.py index`)**:
   - Start every task by running:
     ```bash
     python3 scripts/deltoryx_audit.py index documents
     ```
   - This single command:
     - Extracts all binary (`.docx`, `.pdf`, `.xlsx`, `.pptx`) and text (`.eml`, `.txt`) files in `documents/` into plain-text mirrors under `.deltoryx/parsed/<filename>.txt`.
     - Ranks every source by Deltoryx v2.0 `OriginTier` authority and ingests atomic claims into `.deltoryx/claims.sqlite`.
     - Prints the **Cross-Document Clause & Numerical Diff Matrix** and verbatim **Playbooks, Financial Tables, and Directive Emails**.
   - After running `deltoryx_audit.py index documents`, you can read any long document directly from `.deltoryx/parsed/<filename>.txt` using `read` or `grep` (or via the workspace's `read_doc.py` utility). Always read the complete text of `.deltoryx/parsed/*.txt` for any long agreement or motion so no clause is missed.

2. **Step 2 — Deliverable Generation (`output/<filename>`)**:
   - Write the requested deliverable(s) to `output/<filename>` using clean, well-structured formatting (using `python-docx` / `openpyxl` via a Python script when generating `.docx` or `.xlsx` deliverables).
   - Include executive summary tables, a complete provision-by-provision deviation/issue table, detailed section-by-section analysis, quantitative financial calculations from the `.xlsx` data, and specific recommended counter-language.

3. **Step 3 — Run Deltoryx v2.0 Deliverable Verification (`deltoryx_audit.py verify`)**:
   - After creating the deliverable(s) in `output/`, run:
     ```bash
     python3 scripts/deltoryx_audit.py verify output
     ```
   - If `deltoryx_audit.py verify output` flags any unaddressed modified sections or formatting issues, update the deliverable in `output/` and re-run `python3 scripts/deltoryx_audit.py verify output` until verified with a `DELTORYX-MERKLE-SHA256-v2` certificate.
