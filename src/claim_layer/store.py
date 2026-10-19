from __future__ import annotations
from typing import Optional

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .models import IngestedClaim, IngestedDocument, IngestedEntity, IngestedFact, IngestedSource, IngestedSegment

SCHEMA_VERSION = 2
_DEBUG_INGEST = os.environ.get("DELTORYX_DEBUG_INGESTION", "false").lower() == "true"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extraction_configs (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    mode TEXT NOT NULL,
    policy TEXT NOT NULL,
    version TEXT NOT NULL,
    endpoint TEXT,
    api_key TEXT,
    profile TEXT NOT NULL DEFAULT 'custom',
    focus TEXT NOT NULL DEFAULT '[]',
    interpreter TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    hash TEXT NOT NULL DEFAULT '',
    pipeline_version TEXT NOT NULL DEFAULT '',
    extraction_config_id TEXT NOT NULL DEFAULT 'legacy_default',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, filename)
);

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL COLLATE NOCASE,
    type TEXT NOT NULL DEFAULT 'custom',
    UNIQUE(project_id, name, type)
);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    external_id TEXT,
    text TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    page INTEGER,
    paragraph_id TEXT,
    pipeline_version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    embedding TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    fact_type TEXT NOT NULL,
    value TEXT NOT NULL,
    verified TEXT NOT NULL DEFAULT 'pending',
    valid_from TEXT DEFAULT NULL,
    valid_until TEXT DEFAULT NULL,
    inference_type TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS fact_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER,
    paragraph_id TEXT,
    text TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    canonical_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    reviewer_note TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(canonical_entity_id, alias_entity_id)
);

CREATE TABLE IF NOT EXISTS evidence_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    trigger_document TEXT NOT NULL DEFAULT '',
    trigger_action TEXT NOT NULL DEFAULT 'ingest',
    facts_count INTEGER NOT NULL DEFAULT 0,
    entities_count INTEGER NOT NULL DEFAULT 0,
    claims_count INTEGER NOT NULL DEFAULT 0,
    contradictions_count INTEGER NOT NULL DEFAULT 0,
    document_count INTEGER NOT NULL DEFAULT 0,
    avg_confidence REAL NOT NULL DEFAULT 0.0,
    max_confidence REAL NOT NULL DEFAULT 0.0,
    min_confidence REAL NOT NULL DEFAULT 0.0,
    verified_count INTEGER NOT NULL DEFAULT 0,
    contradicted_count INTEGER NOT NULL DEFAULT 0,
    pending_count INTEGER NOT NULL DEFAULT 0,
    fact_types_distribution TEXT NOT NULL DEFAULT '{}',
    entity_types_distribution TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);
CREATE INDEX IF NOT EXISTS idx_entities_project ON entities(project_id);
CREATE INDEX IF NOT EXISTS idx_claims_document ON claims(document_id);
CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity_id);
CREATE INDEX IF NOT EXISTS idx_facts_type ON facts(fact_type);
CREATE INDEX IF NOT EXISTS idx_fact_sources_fact ON fact_sources(fact_id);
CREATE INDEX IF NOT EXISTS idx_entity_aliases_project ON entity_aliases(project_id);
CREATE INDEX IF NOT EXISTS idx_evidence_snapshots_project ON evidence_snapshots(project_id, created_at);

CREATE TABLE IF NOT EXISTS human_resolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    entity_name TEXT NOT NULL COLLATE NOCASE,
    fact_type TEXT NOT NULL,
    selected_value TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT 'auditor',
    reasoning TEXT NOT NULL DEFAULT '',
    resolved_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, entity_name, fact_type)
);

CREATE INDEX IF NOT EXISTS idx_human_resolutions_lookup
    ON human_resolutions(project_id, entity_name, fact_type);

CREATE TABLE IF NOT EXISTS knowledge_state_versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    parent_id TEXT,
    claim_set_id TEXT NOT NULL,
    extraction_config_version TEXT NOT NULL,
    normalization_version TEXT NOT NULL,
    state_signature TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (parent_id) REFERENCES knowledge_state_versions(id)
);

CREATE TABLE IF NOT EXISTS evidence_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    segment_id TEXT NOT NULL,
    text TEXT NOT NULL,
    page_number INTEGER,
    start_offset INTEGER,
    end_offset INTEGER,
    section_title TEXT,
    embedding TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(document_id, segment_id)
);

CREATE INDEX IF NOT EXISTS idx_segments_document ON evidence_segments(document_id);

CREATE INDEX IF NOT EXISTS idx_ksv_project_created
    ON knowledge_state_versions(project_id, created_at);

CREATE TABLE IF NOT EXISTS query_executions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    state_version_id TEXT NOT NULL,
    protocol_id TEXT,
    query TEXT NOT NULL,
    result_value TEXT,
    confidence REAL NOT NULL,
    supporting_claims TEXT NOT NULL DEFAULT '[]',
    contradictions TEXT NOT NULL DEFAULT '[]',
    evidence_selection TEXT NOT NULL DEFAULT '[]',
    weighting TEXT NOT NULL DEFAULT '[]',
    query_mode TEXT NOT NULL DEFAULT 'explicit_only',
    used_knowledge_levels TEXT NOT NULL DEFAULT '[]',
    grounding_status TEXT,
    supporting_fact_ids TEXT NOT NULL DEFAULT '[]',
    contradiction_fact_ids TEXT NOT NULL DEFAULT '[]',
    answer_type TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (state_version_id) REFERENCES knowledge_state_versions(id)
);

CREATE INDEX IF NOT EXISTS idx_query_exec_project_created
    ON query_executions(project_id, created_at);

CREATE TABLE IF NOT EXISTS scenario_specific_evidence (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    query_execution_id TEXT NOT NULL,
    trace_id TEXT,
    evidence_type TEXT NOT NULL,
    subject TEXT,
    predicate TEXT,
    object TEXT,
    value TEXT,
    confidence REAL NOT NULL DEFAULT 0.0,
    source TEXT NOT NULL DEFAULT 'llm_scenario_extractor',
    derived_from TEXT NOT NULL DEFAULT '[]',
    used_by_inference_ids TEXT NOT NULL DEFAULT '[]',
    promotion_policy TEXT NOT NULL DEFAULT 'never_automatic',
    lineage TEXT NOT NULL DEFAULT '{}',
    quote TEXT,
    critical INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (query_execution_id) REFERENCES query_executions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_scenario_evidence_query_execution
    ON scenario_specific_evidence(query_execution_id, created_at);

CREATE INDEX IF NOT EXISTS idx_scenario_evidence_project
    ON scenario_specific_evidence(project_id, created_at);

CREATE TABLE IF NOT EXISTS query_source_evidence_candidates (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    query_execution_id TEXT NOT NULL,
    trace_id TEXT,
    evidence_candidate_level TEXT NOT NULL,
    entity TEXT,
    predicate TEXT NOT NULL,
    value TEXT,
    confidence REAL NOT NULL DEFAULT 0.0,
    source TEXT NOT NULL DEFAULT 'inline_query_source',
    source_ref TEXT NOT NULL DEFAULT '{}',
    quote TEXT,
    promotion_policy TEXT NOT NULL DEFAULT 'never_automatic',
    lineage TEXT NOT NULL DEFAULT '{}',
    inference_type TEXT NOT NULL DEFAULT 'deductive',
    inference_form_code TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (query_execution_id) REFERENCES query_executions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_query_source_candidates_execution
    ON query_source_evidence_candidates(query_execution_id, created_at);

CREATE TABLE IF NOT EXISTS query_preflight_contradictions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    query_execution_id TEXT NOT NULL,
    trace_id TEXT,
    contradiction_type TEXT NOT NULL,
    message TEXT NOT NULL,
    left_evidence_id TEXT,
    right_evidence_id TEXT,
    left_scope TEXT,
    right_scope TEXT,
    left_value TEXT,
    right_value TEXT,
    lineage TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (query_execution_id) REFERENCES query_executions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_query_preflight_execution
    ON query_preflight_contradictions(query_execution_id, created_at);

CREATE TABLE IF NOT EXISTS state_claim_snapshots (
    state_version_id TEXT NOT NULL,
    canonical_claim_id TEXT NOT NULL,
    entity TEXT NOT NULL,
    predicate TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL,
    PRIMARY KEY (state_version_id, canonical_claim_id),
    FOREIGN KEY (state_version_id) REFERENCES knowledge_state_versions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_state_claim_snapshots_state
    ON state_claim_snapshots(state_version_id);

CREATE INDEX IF NOT EXISTS idx_state_claim_snapshots_semantic
    ON state_claim_snapshots(state_version_id, entity, predicate);

CREATE TRIGGER IF NOT EXISTS trg_ksv_no_update
BEFORE UPDATE ON knowledge_state_versions
BEGIN
    SELECT RAISE(FAIL, 'knowledge_state_versions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_ksv_no_delete
BEFORE DELETE ON knowledge_state_versions
BEGIN
    SELECT RAISE(FAIL, 'knowledge_state_versions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_qe_no_update
BEFORE UPDATE ON query_executions
BEGIN
    SELECT RAISE(FAIL, 'query_executions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_qe_no_delete
BEFORE DELETE ON query_executions
BEGIN
    SELECT RAISE(FAIL, 'query_executions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_sse_no_update
BEFORE UPDATE ON scenario_specific_evidence
BEGIN
    SELECT RAISE(FAIL, 'scenario_specific_evidence is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_sse_no_delete
BEFORE DELETE ON scenario_specific_evidence
BEGIN
    SELECT RAISE(FAIL, 'scenario_specific_evidence is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_qsec_no_update
BEFORE UPDATE ON query_source_evidence_candidates
BEGIN
    SELECT RAISE(FAIL, 'query_source_evidence_candidates is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_qsec_no_delete
BEFORE DELETE ON query_source_evidence_candidates
BEGIN
    SELECT RAISE(FAIL, 'query_source_evidence_candidates is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_qpfc_no_update
BEFORE UPDATE ON query_preflight_contradictions
BEGIN
    SELECT RAISE(FAIL, 'query_preflight_contradictions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_qpfc_no_delete
BEFORE DELETE ON query_preflight_contradictions
BEGIN
    SELECT RAISE(FAIL, 'query_preflight_contradictions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_scs_no_update
BEFORE UPDATE ON state_claim_snapshots
BEGIN
    SELECT RAISE(FAIL, 'state_claim_snapshots is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_scs_no_delete
BEFORE DELETE ON state_claim_snapshots
BEGIN
    SELECT RAISE(FAIL, 'state_claim_snapshots is append-only');
END;

CREATE TABLE IF NOT EXISTS protocol_comparisons (
    id TEXT PRIMARY KEY,
    protocol_id_a TEXT NOT NULL,
    protocol_id_b TEXT NOT NULL,
    query TEXT NOT NULL,
    diff_result TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_protocol_comparisons_created
    ON protocol_comparisons(created_at);
"""


def _as_entity(value: IngestedEntity | dict[str, Any]) -> IngestedEntity:
    if isinstance(value, IngestedEntity):
        return value
    return IngestedEntity(
        entity_id=str(value.get("entity_id") or value.get("id") or value.get("name") or ""),
        name=str(value.get("name") or value.get("normalized") or value.get("text") or ""),
        entity_type=str(value.get("entity_type") or value.get("type") or "custom"),
    )


def _as_claim(value: IngestedClaim | dict[str, Any]) -> IngestedClaim:
    if isinstance(value, IngestedClaim):
        return value
    return IngestedClaim(
        claim_id=str(value.get("claim_id") or value.get("id") or ""),
        text=str(value.get("text") or value.get("statement") or ""),
        confidence=float(value.get("confidence") or 0.0),
        page=value.get("page"),
        paragraph_id=value.get("paragraph_id"),
        embedding=value.get("embedding"),
    )


def _as_source(value: IngestedSource | dict[str, Any]) -> IngestedSource:
    if isinstance(value, IngestedSource):
        return value
    return IngestedSource(
        page=value.get("page"),
        paragraph_id=value.get("paragraph_id"),
        text=str(value.get("text") or ""),
    )


def _encode_embedding(vec: list[float]) -> str:
    return json.dumps(vec)


def _decode_embedding(raw: Optional[str]) -> list[float] | None:
    if raw is None:
        return None
    return json.loads(raw)


def _as_segment(value: IngestedSegment | dict[str, Any]) -> IngestedSegment:
    if isinstance(value, IngestedSegment):
        return value
    return IngestedSegment(
        segment_id=str(value.get("segment_id") or ""),
        text=str(value.get("text") or ""),
        page_number=value.get("page_number"),
        start_offset=value.get("start_offset"),
        end_offset=value.get("end_offset"),
        section_title=value.get("section_title"),
        embedding=value.get("embedding"),
    )


def _as_fact(value: IngestedFact | dict[str, Any]) -> IngestedFact:
    if isinstance(value, IngestedFact):
        return value
    return IngestedFact(
        claim_ref=str(value.get("claim_ref") or value.get("claim_id") or ""),
        entity_ref=str(value.get("entity_ref") or value.get("entity_id") or value.get("entity") or ""),
        fact_type=str(value.get("fact_type") or "general"),
        value=str(value.get("value") or ""),
        verified=str(value.get("verified") or "pending"),
        sources=[_as_source(item) for item in value.get("sources", [])],
        valid_from=value.get("valid_from"),
        valid_until=value.get("valid_until"),
        inference_type=value.get("inference_type"),
    )


class ClaimLayerStore:
    def __init__(self, db_path: str | Path, *, enable_semantic: bool = False) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.enable_semantic = enable_semantic
        self._ensure_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA_SQL)
            try:
                fact_fks = conn.execute("PRAGMA foreign_key_list(facts)").fetchall()
                claim_fk_tables = {row["table"] for row in fact_fks if row["from"] == "claim_id"}
                if claim_fk_tables and claim_fk_tables != {"claims"}:
                    conn.execute("ALTER TABLE fact_sources RENAME TO fact_sources_legacy")
                    conn.execute("ALTER TABLE facts RENAME TO facts_legacy")
                    conn.executescript(
                        """
                        CREATE TABLE IF NOT EXISTS facts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            claim_id INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
                            entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                            fact_type TEXT NOT NULL,
                            value TEXT NOT NULL,
                            verified TEXT NOT NULL DEFAULT 'pending'
                        );

                        CREATE TABLE IF NOT EXISTS fact_sources (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            fact_id INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
                            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                            page INTEGER,
                            paragraph_id TEXT,
                            text TEXT NOT NULL DEFAULT ''
                        );

                        CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity_id);
                        CREATE INDEX IF NOT EXISTS idx_facts_type ON facts(fact_type);
                        CREATE INDEX IF NOT EXISTS idx_fact_sources_fact ON fact_sources(fact_id);
                        """
                    )
            except sqlite3.OperationalError:
                pass
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            # Migration: add embedding column to existing databases (idempotent).
            try:
                conn.execute("ALTER TABLE claims ADD COLUMN embedding TEXT DEFAULT NULL")
            except sqlite3.OperationalError:
                pass  # column already exists

            # Migration: temporal validity window + typed inference on facts (idempotent).
            for column in ("valid_from TEXT DEFAULT NULL",
                           "valid_until TEXT DEFAULT NULL",
                           "inference_type TEXT DEFAULT NULL"):
                try:
                    conn.execute(f"ALTER TABLE facts ADD COLUMN {column}")
                except sqlite3.OperationalError:
                    pass  # column already exists
            
            # Migration: add extraction_config_id to existing documents
            try:
                conn.execute("ALTER TABLE documents ADD COLUMN extraction_config_id TEXT DEFAULT 'legacy_default'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE extraction_configs ADD COLUMN endpoint TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE extraction_configs ADD COLUMN api_key TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE extraction_configs ADD COLUMN profile TEXT NOT NULL DEFAULT 'custom'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE extraction_configs ADD COLUMN focus TEXT NOT NULL DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE extraction_configs ADD COLUMN interpreter TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE query_executions ADD COLUMN protocol_id TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE query_executions ADD COLUMN query_mode TEXT NOT NULL DEFAULT 'explicit_only'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE query_executions ADD COLUMN used_knowledge_levels TEXT NOT NULL DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE query_executions ADD COLUMN grounding_status TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE query_executions ADD COLUMN supporting_fact_ids TEXT NOT NULL DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE query_executions ADD COLUMN contradiction_fact_ids TEXT NOT NULL DEFAULT '[]'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE query_executions ADD COLUMN answer_type TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE scenario_specific_evidence ADD COLUMN quote TEXT")
            except sqlite3.OperationalError:
                pass

    @staticmethod
    def _similarity_score(left: str, right: str) -> float:
        return SequenceMatcher(None, left.lower().strip(), right.lower().strip()).ratio()

    @staticmethod
    def _normalize_value(value: str) -> str:
        import re

        return re.sub(r"[^\w\s]", "", value or "").lower().strip()

    @staticmethod
    def _aggregate_support(confidences: list[float]) -> float:
        if not confidences:
            return 0.0
        product = 1.0
        for confidence in confidences:
            bounded = max(0.0, min(1.0, float(confidence)))
            product *= 1.0 - bounded
        return round(1.0 - product, 4)

    def upsert_extraction_config(self, config_dict: dict[str, Any]) -> str:
        config_id = config_dict.get("id", "legacy_default")
        focus = config_dict.get("focus", [])
        if not isinstance(focus, list):
            focus = []
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO extraction_configs (
                    id, provider, model, mode, policy, version,
                    endpoint, api_key, profile, focus, interpreter, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    config_id,
                    config_dict.get("provider", "unknown"),
                    config_dict.get("model", "unknown"),
                    config_dict.get("mode", "unknown"),
                    config_dict.get("policy", "unknown"),
                    str(config_dict.get("version", "unknown")),
                    config_dict.get("endpoint"),
                    config_dict.get("api_key"),
                    config_dict.get("profile", "custom"),
                    json.dumps(focus),
                    config_dict.get("interpreter"),
                    config_dict.get("created_at") or datetime.now(timezone.utc).isoformat(),
                ),
            )
        return config_id

    def upsert_document(
        self,
        project_id: str,
        filename: str,
        file_hash: str = "",
        pipeline_version: str = "0.1.0",
        extraction_config_id: str = "legacy_default",
    ) -> int:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO documents (project_id, filename, hash, pipeline_version, extraction_config_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, filename) DO UPDATE SET
                    hash = excluded.hash,
                    pipeline_version = excluded.pipeline_version,
                    extraction_config_id = excluded.extraction_config_id
                """,
                (project_id, filename, file_hash, pipeline_version, extraction_config_id),
            )
            row = conn.execute(
                "SELECT id FROM documents WHERE project_id = ? AND filename = ?",
                (project_id, filename),
            ).fetchone()
            return int(row["id"])

    def get_document_id(self, project_id: str, filename: str) -> Optional[int]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM documents WHERE project_id = ? AND filename = ?",
                (project_id, filename),
            ).fetchone()
            return int(row["id"]) if row else None

    def get_extraction_config(self, config_id: str) -> dict[str, Any] | None:
        """Return a single extraction config by id, or None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, provider, model, mode, policy, version, endpoint, api_key, profile, focus, interpreter, created_at "
                "FROM extraction_configs WHERE id = ?",
                (config_id,),
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["focus"] = json.loads(data.get("focus") or "[]")
        return data

    def list_extraction_configs(self) -> list[dict[str, Any]]:
        """Return all extraction configs ordered by creation date descending."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, provider, model, mode, policy, version, endpoint, api_key, profile, focus, interpreter, created_at "
                "FROM extraction_configs ORDER BY created_at DESC"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["focus"] = json.loads(data.get("focus") or "[]")
            result.append(data)
        return result

    def get_documents(self, project_id: str) -> list[dict[str, Any]]:
        """Return all documents for a project ordered by creation date descending."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT filename, created_at,
                       COALESCE(
                           (SELECT COUNT(*) FROM claims cl
                            JOIN documents d2 ON d2.id = cl.document_id
                            WHERE d2.project_id = ? AND d2.filename = documents.filename),
                           0
                       ) AS claim_count
                FROM documents
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id, project_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_segments(self, project_id: str) -> list[dict[str, Any]]:
        """Return all segments for a project."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT s.*, d.filename 
                FROM evidence_segments s
                JOIN documents d ON d.id = s.document_id
                WHERE d.project_id = ?
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_claims_by_segment(self, document_id: int, paragraph_id: str) -> list[dict[str, Any]]:
        """Return all claims/facts associated with a specific segment."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT f.id AS fact_id, f.fact_type, f.value, f.verified, 
                       c.id AS claim_id, c.text AS claim_text, c.confidence, 
                       e.name AS entity_name, e.type AS entity_type,
                       c.page, c.paragraph_id
                FROM facts f
                JOIN claims c ON c.id = f.claim_id
                JOIN entities e ON e.id = f.entity_id
                WHERE c.document_id = ? AND c.paragraph_id = ?
                """,
                (document_id, paragraph_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_document_by_filename(self, project_id: str, filename: str) -> bool:
        document_id = self.get_document_id(project_id, filename)
        if document_id is None:
            return False
        with self._conn() as conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        self._prune_orphan_entities(project_id)
        self.capture_snapshot(project_id, trigger_document=filename, trigger_action="delete")
        return True

    def _prune_orphan_entities(self, project_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                DELETE FROM entities
                WHERE project_id = ?
                  AND id NOT IN (
                    SELECT DISTINCT f.entity_id
                    FROM facts f
                    JOIN claims c ON c.id = f.claim_id
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.project_id = ?
                  )
                """,
                (project_id, project_id),
            )

    def upsert_entity(self, project_id: str, name: str, entity_type: str = "custom") -> int:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO entities (project_id, name, type) VALUES (?, ?, ?)",
                (project_id, name, entity_type),
            )
            row = conn.execute(
                "SELECT id FROM entities WHERE project_id = ? AND name = ? COLLATE NOCASE AND type = ?",
                (project_id, name, entity_type),
            ).fetchone()
            return int(row["id"])

    def get_entities(self, project_id: str, entity_type: Optional[str] = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if entity_type:
                rows = conn.execute(
                    "SELECT * FROM entities WHERE project_id = ? AND type = ? ORDER BY name",
                    (project_id, entity_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM entities WHERE project_id = ? ORDER BY name",
                    (project_id,),
                ).fetchall()
            return [dict(row) for row in rows]

    def create_alias(
        self,
        project_id: str,
        canonical_entity_id: int,
        alias_entity_id: int,
        reviewer_note: str = "",
    ) -> Optional[int]:
        if canonical_entity_id == alias_entity_id:
            return None
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO entity_aliases
                (project_id, canonical_entity_id, alias_entity_id, reviewer_note)
                VALUES (?, ?, ?, ?)
                """,
                (project_id, canonical_entity_id, alias_entity_id, reviewer_note),
            )
            return int(cursor.lastrowid) if cursor.rowcount > 0 else None

    def upsert_entity_with_dedup(
        self,
        project_id: str,
        name: str,
        entity_type: str = "custom",
        similarity_threshold: float = 0.85,
    ) -> int:
        entity_id = self.upsert_entity(project_id, name, entity_type)
        existing = self.get_entities(project_id, entity_type=entity_type)
        best_match: dict[str, Any] | None = None
        best_score = 0.0
        for item in existing:
            if int(item["id"]) == entity_id:
                continue
            score = self._similarity_score(name, str(item["name"]))
            if score >= similarity_threshold and score > best_score:
                best_score = score
                best_match = item
        if best_match:
            if len(str(best_match["name"])) >= len(name):
                canonical_id, alias_id = int(best_match["id"]), entity_id
            else:
                canonical_id, alias_id = entity_id, int(best_match["id"])
            self.create_alias(
                project_id,
                canonical_id,
                alias_id,
                reviewer_note=f"auto_dedup: score={best_score:.2f}",
            )
        return entity_id

    def get_entity_group(self, project_id: str, entity_id: int) -> list[int]:
        with self._conn() as conn:
            visited: set[int] = set()
            queue = [entity_id]
            while queue:
                current = queue.pop()
                if current in visited:
                    continue
                visited.add(current)
                rows = conn.execute(
                    """
                    SELECT canonical_entity_id AS eid FROM entity_aliases
                    WHERE project_id = ? AND alias_entity_id = ?
                    UNION
                    SELECT alias_entity_id AS eid FROM entity_aliases
                    WHERE project_id = ? AND canonical_entity_id = ?
                    """,
                    (project_id, current, project_id, current),
                ).fetchall()
                for row in rows:
                    next_id = int(row["eid"])
                    if next_id not in visited:
                        queue.append(next_id)
            return sorted(visited)

    def get_alias_groups(self, project_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT ea.canonical_entity_id, ea.alias_entity_id, ea.reviewer_note,
                       canonical.name AS canonical_name, canonical.type AS canonical_type,
                       alias.name AS alias_name, alias.type AS alias_type
                FROM entity_aliases ea
                JOIN entities canonical ON canonical.id = ea.canonical_entity_id
                JOIN entities alias ON alias.id = ea.alias_entity_id
                WHERE ea.project_id = ?
                ORDER BY ea.canonical_entity_id, ea.alias_entity_id
                """,
                (project_id,),
            ).fetchall()
        groups: dict[int, dict[str, Any]] = {}
        for row in rows:
            canonical_id = int(row["canonical_entity_id"])
            groups.setdefault(
                canonical_id,
                {
                    "canonical": {
                        "id": canonical_id,
                        "name": row["canonical_name"],
                        "type": row["canonical_type"],
                    },
                    "aliases": [],
                },
            )
            groups[canonical_id]["aliases"].append(
                {
                    "id": int(row["alias_entity_id"]),
                    "name": row["alias_name"],
                    "type": row["alias_type"],
                    "reviewer_note": row["reviewer_note"],
                }
            )
        return list(groups.values())

    def insert_claim(
        self,
        document_id: int,
        text: str,
        confidence: float = 0.0,
        page: Optional[int] = None,
        paragraph_id: Optional[str] = None,
        external_id: Optional[str] = None,
        pipeline_version: str = "0.1.0",
    ) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO claims (document_id, external_id, text, confidence, page, paragraph_id, pipeline_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (document_id, external_id, text, confidence, page, paragraph_id, pipeline_version),
            )
            return int(cursor.lastrowid)

    def _update_claim_embedding(self, claim_id: int, embedding: list[float]) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE claims SET embedding = ? WHERE id = ?",
                (_encode_embedding(embedding), claim_id),
            )

    def get_claim_embedding(self, claim_id: int) -> list[float] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT embedding FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
        if row is None:
            return None
        return _decode_embedding(row["embedding"])

    def get_claims_with_embeddings(self, project_id: str) -> list[dict[str, Any]]:
        """Return all claims that have a stored embedding, for future vector indexing."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT c.id, c.text, c.embedding
                FROM claims c
                JOIN documents d ON d.id = c.document_id
                WHERE d.project_id = ? AND c.embedding IS NOT NULL
                ORDER BY c.id
                """,
                (project_id,),
            ).fetchall()
        return [
            {"id": row["id"], "text": row["text"], "embedding": _decode_embedding(row["embedding"])}
            for row in rows
        ]

    def get_claims(self, document_id: Optional[int] = None, project_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if document_id is not None:
                rows = conn.execute("SELECT * FROM claims WHERE document_id = ? ORDER BY id", (document_id,)).fetchall()
            elif project_id is not None:
                rows = conn.execute(
                    """
                    SELECT c.* FROM claims c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.project_id = ?
                    ORDER BY c.id
                    """,
                    (project_id,),
                ).fetchall()
            else:
                rows = []
            return [dict(row) for row in rows]

    def insert_fact(self, claim_id: int, entity_id: int, fact_type: str, value: str, verified: str = "pending") -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO facts (claim_id, entity_id, fact_type, value, verified) VALUES (?, ?, ?, ?, ?)",
                (claim_id, entity_id, fact_type, value, verified),
            )
            return int(cursor.lastrowid)

    def insert_fact_source(
        self,
        fact_id: int,
        document_id: int,
        page: Optional[int] = None,
        paragraph_id: Optional[str] = None,
        text: str = "",
    ) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO fact_sources (fact_id, document_id, page, paragraph_id, text) VALUES (?, ?, ?, ?, ?)",
                (fact_id, document_id, page, paragraph_id, text),
            )
            return int(cursor.lastrowid)

    def clear_document_evidence(self, document_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM claims WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM evidence_segments WHERE document_id = ?", (document_id,))

    def ingest_document(self, document: IngestedDocument | dict[str, Any]) -> dict[str, int]:
        payload = document if isinstance(document, IngestedDocument) else IngestedDocument(**document)
        
        extraction_config_id = "legacy_default"
        if getattr(payload, "extraction_config", None):
            # Dict cast handled dynamically, saving the config snapshot permanently
            extraction_config_id = self.upsert_extraction_config(payload.extraction_config)
            
        doc_id = self.upsert_document(
            payload.project_id, 
            payload.filename, 
            payload.file_hash, 
            payload.pipeline_version,
            extraction_config_id,
        )
        self.clear_document_evidence(doc_id)

        entity_map: dict[str, int] = {}
        for raw_entity in payload.entities:
            entity = _as_entity(raw_entity)
            if not entity.name:
                continue
            entity_map[entity.entity_id or entity.name] = self.upsert_entity_with_dedup(
                payload.project_id,
                entity.name,
                entity.entity_type,
            )

        claim_map: dict[str, int] = {}
        facts_inserted = 0
        skipped_claims_missing_text = 0
        skipped_facts_missing_claim = 0
        skipped_facts_missing_entity = 0
        skipped_facts_missing_value = 0
        with self._conn() as conn:
            for raw_claim in payload.claims:
                claim = _as_claim(raw_claim)
                if not claim.text:
                    skipped_claims_missing_text += 1
                    continue
                cursor = conn.execute(
                    """
                    INSERT INTO claims (document_id, external_id, text, confidence, page, paragraph_id, pipeline_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        claim.claim_id or None,
                        claim.text,
                        claim.confidence,
                        claim.page,
                        claim.paragraph_id,
                        payload.pipeline_version,
                    ),
                )
                claim_db_id = int(cursor.lastrowid)
                claim_map[claim.claim_id or claim.text] = claim_db_id

                if self.enable_semantic:
                    from .semantic.embeddings import embed  # lazy — cached after first import
                    vec = claim.embedding if claim.embedding is not None else embed(claim.text)
                    if vec:
                        conn.execute(
                            "UPDATE claims SET embedding = ? WHERE id = ?",
                            (_encode_embedding(vec), claim_db_id),
                        )

            for raw_segment in payload.segments:
                seg = _as_segment(raw_segment)
                if not seg.text:
                    continue
                conn.execute(
                    """
                    INSERT INTO evidence_segments (
                        document_id, segment_id, text, page_number, 
                        start_offset, end_offset, section_title, embedding
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        seg.segment_id,
                        seg.text,
                        seg.page_number,
                        seg.start_offset,
                        seg.end_offset,
                        seg.section_title,
                        _encode_embedding(seg.embedding) if seg.embedding else None,
                    ),
                )

            for raw_fact in payload.facts:
                fact = _as_fact(raw_fact)
                claim_id = claim_map.get(fact.claim_ref)
                entity_id = entity_map.get(fact.entity_ref)
                if claim_id is None:
                    skipped_facts_missing_claim += 1
                    continue
                if entity_id is None:
                    skipped_facts_missing_entity += 1
                    continue
                if not fact.value:
                    skipped_facts_missing_value += 1
                    continue
                try:
                    cursor = conn.execute(
                        """
                        INSERT INTO facts (claim_id, entity_id, fact_type, value, verified,
                                           valid_from, valid_until, inference_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (claim_id, entity_id, fact.fact_type, fact.value, fact.verified,
                         fact.valid_from, fact.valid_until, fact.inference_type),
                    )
                except sqlite3.IntegrityError:
                    if _DEBUG_INGEST:
                        claim_exists = conn.execute("SELECT id, document_id, text FROM claims WHERE id = ?", (claim_id,)).fetchone()
                        entity_exists = conn.execute("SELECT id, project_id, name FROM entities WHERE id = ?", (entity_id,)).fetchone()
                        print(
                            "[claim-layer:fact-insert-error]",
                            {
                                "fact_claim_ref": fact.claim_ref,
                                "fact_entity_ref": fact.entity_ref,
                                "resolved_claim_id": claim_id,
                                "resolved_entity_id": entity_id,
                                "claim_exists": dict(claim_exists) if claim_exists else None,
                                "entity_exists": dict(entity_exists) if entity_exists else None,
                                "fact_type": fact.fact_type,
                                "value_preview": fact.value[:200],
                            },
                        )
                    raise
                fact_id = int(cursor.lastrowid)
                facts_inserted += 1
                for source in fact.sources:
                    conn.execute(
                        "INSERT INTO fact_sources (fact_id, document_id, page, paragraph_id, text) VALUES (?, ?, ?, ?, ?)",
                        (fact_id, doc_id, source.page, source.paragraph_id, source.text[:500]),
                    )

        if _DEBUG_INGEST:
            print(
                "[claim-layer:ingest-summary]",
                {
                    "document": payload.filename,
                    "payload_entities": len(payload.entities),
                    "payload_claims": len(payload.claims),
                    "payload_facts": len(payload.facts),
                    "resolved_entities": len(entity_map),
                    "inserted_claims": len(claim_map),
                    "inserted_facts": facts_inserted,
                    "skipped_claims_missing_text": skipped_claims_missing_text,
                    "skipped_facts_missing_claim": skipped_facts_missing_claim,
                    "skipped_facts_missing_entity": skipped_facts_missing_entity,
                    "skipped_facts_missing_value": skipped_facts_missing_value,
                },
            )

        self.capture_snapshot(payload.project_id, trigger_document=payload.filename, trigger_action="ingest")
        return {"documents": 1, "entities": len(entity_map), "claims": len(claim_map), "facts": facts_inserted}

    def get_facts(
        self,
        project_id: Optional[str] = None,
        document_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        entity_id: Optional[int] = None,
        fact_type: Optional[str] = None,
        include_aliases: bool = False,
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            conditions: list[str] = []
            params: list[Any] = []
            sql = """
                SELECT
                    f.id AS fact_id,
                    f.fact_type,
                    f.value,
                    f.verified,
                    f.valid_from,
                    f.valid_until,
                    f.inference_type,
                    e.id AS entity_id,
                    e.name AS entity_name,
                    e.type AS entity_type,
                    c.text AS claim_text,
                    c.confidence,
                    c.page,
                    c.paragraph_id,
                    d.filename
                FROM facts f
                JOIN claims c ON c.id = f.claim_id
                JOIN entities e ON e.id = f.entity_id
                JOIN documents d ON d.id = c.document_id
            """
            if project_id:
                conditions.append("d.project_id = ?")
                params.append(project_id)
            if document_id is not None:
                conditions.append("d.id = ?")
                params.append(document_id)
            if fact_type:
                conditions.append("f.fact_type = ?")
                params.append(fact_type)

            if entity_id is not None:
                if include_aliases and project_id:
                    group_ids = self.get_entity_group(project_id, entity_id)
                    placeholders = ",".join("?" for _ in group_ids)
                    conditions.append(f"f.entity_id IN ({placeholders})")
                    params.extend(group_ids)
                else:
                    conditions.append("f.entity_id = ?")
                    params.append(entity_id)
            elif entity_name:
                conditions.append("LOWER(e.name) = LOWER(?)")
                params.append(entity_name)

            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY f.id"
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def get_project_summary(self, project_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            facts_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM facts f JOIN claims c ON c.id = f.claim_id JOIN documents d ON d.id = c.document_id WHERE d.project_id = ?",
                (project_id,),
            ).fetchone()["cnt"]
            entities_count = conn.execute("SELECT COUNT(*) AS cnt FROM entities WHERE project_id = ?", (project_id,)).fetchone()["cnt"]
            documents_count = conn.execute("SELECT COUNT(*) AS cnt FROM documents WHERE project_id = ?", (project_id,)).fetchone()["cnt"]
            
            contradictions = self.get_contradictions(project_id)
            
            return {
                "project_id": project_id,
                "facts_count": facts_count,
                "entities_count": entities_count,
                "documents_count": documents_count,
                "contradictions_count": len(contradictions),
                "last_updated": datetime.now().isoformat()
            }

    def get_lineage(self, fact_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            fact_row = conn.execute(
                """
                SELECT f.*, e.name AS entity_name, e.type AS entity_type
                FROM facts f
                JOIN entities e ON e.id = f.entity_id
                WHERE f.id = ?
                """,
                (fact_id,),
            ).fetchone()
            if not fact_row:
                return None
            
            fact = dict(fact_row)
            claim_row = conn.execute(
                "SELECT * FROM claims WHERE id = ?", (fact["claim_id"],)
            ).fetchone()
            claim = dict(claim_row) if claim_row else {}
            
            doc_row = conn.execute(
                "SELECT * FROM documents WHERE id = ?", (claim.get("document_id"),)
            ).fetchone() if claim.get("document_id") else None
            document = dict(doc_row) if doc_row else {}
            
            source_rows = conn.execute(
                "SELECT * FROM fact_sources WHERE fact_id = ?", (fact_id,)
            ).fetchall()
            sources = [dict(s) for s in source_rows]
            
            return {
                "fact": fact,
                "claim": claim,
                "document": document,
                "sources": sources
            }

    def get_contradictions(self, project_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT entity_name, fact_type,
                       GROUP_CONCAT(value, '|||') AS distinct_values,
                       COUNT(*) AS value_count
                FROM (
                    SELECT DISTINCT
                        COALESCE(canonical.name, e.name) AS entity_name,
                        f.fact_type,
                        f.value,
                        COALESCE(ea.canonical_entity_id, e.id) AS group_id
                    FROM facts f
                    JOIN entities e ON e.id = f.entity_id
                    JOIN claims c ON c.id = f.claim_id
                    JOIN documents d ON d.id = c.document_id
                    LEFT JOIN entity_aliases ea ON ea.alias_entity_id = e.id
                    LEFT JOIN entities canonical ON canonical.id = ea.canonical_entity_id
                    WHERE d.project_id = ?
                )
                GROUP BY entity_name, fact_type
                HAVING COUNT(*) > 1
                ORDER BY entity_name, fact_type
                """,
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def resolve_conflict(
        self,
        project_id: str,
        entity_name: str,
        fact_type: str,
        selected_value: str,
        user_id: str = "auditor",
        reasoning: str = "",
    ) -> str:
        """
        Elevate selected_value as human-verified truth for entity+fact_type.

        PRECEDENCE INVARIANTS:
        human_verified > system_aggregation > raw_claims

        CRITICAL OVERRIDE GUARANTEES:
        - DO NOT delete conflicting claims.
        - DO NOT modify original evidence or provenance coordinates.
        - DO NOT collapse value sets (incertitude must be auditable).

        - Upserts a row in human_resolutions (re-resolving overwrites the old record).
        - Sets facts.verified = 'human' for matching facts; resets others to 'pending'.
        - confidence column retains its original algorithmically computed support for audit.
        - Returns resolved_at as an ISO-8601 UTC timestamp string.
        """
        resolved_at = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO human_resolutions
                    (project_id, entity_name, fact_type, selected_value, user_id, reasoning, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, entity_name, fact_type)
                DO UPDATE SET
                    selected_value = excluded.selected_value,
                    user_id        = excluded.user_id,
                    reasoning      = excluded.reasoning,
                    resolved_at    = excluded.resolved_at
                """,
                (project_id, entity_name, fact_type, selected_value, user_id, reasoning, resolved_at),
            )
            conn.execute(
                """
                UPDATE facts
                SET verified = CASE WHEN value = ? THEN 'human' ELSE 'pending' END
                WHERE fact_type = ?
                  AND entity_id IN (
                      SELECT e.id FROM entities e
                      WHERE e.project_id = ? AND e.name = ? COLLATE NOCASE
                  )
                """,
                (selected_value, fact_type, project_id, entity_name),
            )
        return resolved_at

    def get_resolution(
        self, project_id: str, entity_name: str, fact_type: str
    ) -> dict[str, Any] | None:
        """Return the human resolution record for entity+fact_type, or None."""
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT selected_value, user_id, reasoning, resolved_at
                FROM human_resolutions
                WHERE project_id = ? AND entity_name = ? AND fact_type = ?
                """,
                (project_id, entity_name, fact_type),
            ).fetchone()
            return dict(row) if row else None

    def get_cross_document_entities(self, project_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    e.name AS entity_name,
                    e.type AS entity_type,
                    COUNT(DISTINCT c.document_id) AS document_count,
                    GROUP_CONCAT(DISTINCT d.filename) AS documents
                FROM entities e
                JOIN facts f ON f.entity_id = e.id
                JOIN claims c ON c.id = f.claim_id
                JOIN documents d ON d.id = c.document_id
                WHERE e.project_id = ?
                GROUP BY e.id
                HAVING COUNT(DISTINCT c.document_id) > 1
                ORDER BY document_count DESC, entity_name
                """,
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_fact_types_summary(self, project_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT f.fact_type, COUNT(*) AS count
                FROM facts f
                JOIN claims c ON c.id = f.claim_id
                JOIN documents d ON d.id = c.document_id
                WHERE d.project_id = ?
                GROUP BY f.fact_type
                ORDER BY count DESC, f.fact_type
                """,
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def detect_gaps(
        self,
        project_id: str,
        expected_fact_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            documents = conn.execute(
                "SELECT id, filename FROM documents WHERE project_id = ?",
                (project_id,),
            ).fetchall()
            if not documents:
                return []
            if expected_fact_types is None:
                rows = conn.execute(
                    """
                    SELECT DISTINCT f.fact_type
                    FROM facts f
                    JOIN claims c ON c.id = f.claim_id
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.project_id = ?
                    """,
                    (project_id,),
                ).fetchall()
                expected_fact_types = sorted(row["fact_type"] for row in rows)
            if not expected_fact_types:
                return []
            expected_set = set(expected_fact_types)
            result = []
            for document in documents:
                found_rows = conn.execute(
                    """
                    SELECT DISTINCT f.fact_type
                    FROM facts f
                    JOIN claims c ON c.id = f.claim_id
                    WHERE c.document_id = ?
                    """,
                    (document["id"],),
                ).fetchall()
                found_set = {row["fact_type"] for row in found_rows}
                result.append(
                    {
                        "filename": document["filename"],
                        "found": sorted(found_set & expected_set),
                        "missing": sorted(expected_set - found_set),
                        "coverage": round(len(found_set & expected_set) / len(expected_set), 2) if expected_set else 1.0,
                    }
                )
        result.sort(key=lambda item: item["coverage"])
        return result

    def benchmark_facts(self, project_id: str, fact_type: Optional[str] = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            conditions = ["d.project_id = ?"]
            params: list[Any] = [project_id]
            if fact_type:
                conditions.append("f.fact_type = ?")
                params.append(fact_type)
            rows = conn.execute(
                f"""
                SELECT
                    e.name AS entity_name,
                    f.fact_type,
                    f.value,
                    d.filename
                FROM facts f
                JOIN claims c ON c.id = f.claim_id
                JOIN entities e ON e.id = f.entity_id
                JOIN documents d ON d.id = c.document_id
                WHERE {' AND '.join(conditions)}
                ORDER BY e.name, f.fact_type, d.filename
                """,
                params,
            ).fetchall()
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = f"{row['entity_name']}|{row['fact_type']}"
            groups.setdefault(
                key,
                {
                    "entity_name": row["entity_name"],
                    "fact_type": row["fact_type"],
                    "values_by_document": {},
                },
            )
            groups[key]["values_by_document"].setdefault(row["filename"], []).append(row["value"])
        result = []
        for item in groups.values():
            unique_values = set()
            for values in item["values_by_document"].values():
                unique_values.update(values)
            item["unique_value_count"] = len(unique_values)
            item["is_consistent"] = len(unique_values) <= 1
            result.append(item)
        result.sort(key=lambda item: (item["is_consistent"], item["entity_name"]))
        return result

    def compute_value_confidences(self, project_id: str, entity_name: str, fact_type: str) -> dict[str, Any]:
        facts = self.get_facts(project_id=project_id, entity_name=entity_name, fact_type=fact_type)
        if not facts:
            return {"values": {}, "contradiction_detected": False, "contradiction_penalty": 1.0}
        grouped: dict[str, list[dict[str, Any]]] = {}
        for fact in facts:
            key = self._normalize_value(str(fact.get("value") or ""))
            grouped.setdefault(key, []).append(fact)
        penalty = 1.0 / len(grouped) if len(grouped) > 1 else 1.0
        result: dict[str, Any] = {}
        for _, items in grouped.items():
            display_value = str(items[0]["value"])
            raw_conf = self._aggregate_support([float(item.get("confidence") or 0.0) for item in items])
            result[display_value] = {
                "raw_confidence": raw_conf,
                "adjusted_confidence": round(raw_conf * penalty, 4),
                "source_count": len(items),
                "sources": [
                    {
                        "filename": item.get("filename", ""),
                        "page": item.get("page"),
                        "paragraph_id": item.get("paragraph_id", ""),
                        "claim_text": item.get("claim_text", ""),
                        "confidence": item.get("confidence", 0.0),
                    }
                    for item in items
                ],
            }
        return {
            "values": result,
            "contradiction_detected": len(grouped) > 1,
            "contradiction_penalty": round(penalty, 4),
        }

    def query_evidence(self, project_id: str, entity_name: str, fact_type: str) -> dict[str, Any]:
        data = self.compute_value_confidences(project_id, entity_name, fact_type)
        candidate_values = []
        all_sources: list[dict[str, Any]] = []
        total_source_count = 0
        for value, value_data in data["values"].items():
            candidate_values.append(
                {
                    "value": value,
                    "confidence": value_data["adjusted_confidence"],
                    "source_count": value_data["source_count"],
                }
            )
            total_source_count += value_data["source_count"]
            all_sources.extend(value_data["sources"])
        candidate_values.sort(key=lambda item: item["confidence"], reverse=True)
        aggregate_confidence = self._aggregate_support([item["confidence"] for item in candidate_values])
        return {
            "entity": entity_name,
            "fact_type": fact_type,
            "candidate_values": candidate_values,
            "total_source_count": total_source_count,
            "contradiction_detected": data["contradiction_detected"],
            "aggregate_confidence": aggregate_confidence,
            "sources": all_sources,
        }

    def capture_snapshot(self, project_id: str, trigger_document: str = "", trigger_action: str = "ingest") -> int:
        contradictions = self.get_contradictions(project_id)
        with self._conn() as conn:
            facts_count = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM facts f
                JOIN claims c ON c.id = f.claim_id
                JOIN documents d ON d.id = c.document_id
                WHERE d.project_id = ?
                """,
                (project_id,),
            ).fetchone()["cnt"]
            entities_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM entities WHERE project_id = ?",
                (project_id,),
            ).fetchone()["cnt"]
            claims_count = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM claims c JOIN documents d ON d.id = c.document_id
                WHERE d.project_id = ?
                """,
                (project_id,),
            ).fetchone()["cnt"]
            document_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM documents WHERE project_id = ?",
                (project_id,),
            ).fetchone()["cnt"]
            confidence_row = conn.execute(
                """
                SELECT AVG(c.confidence) AS avg_c, MAX(c.confidence) AS max_c, MIN(c.confidence) AS min_c
                FROM claims c JOIN documents d ON d.id = c.document_id
                WHERE d.project_id = ?
                """,
                (project_id,),
            ).fetchone()
            verification_rows = conn.execute(
                """
                SELECT f.verified, COUNT(*) AS cnt
                FROM facts f
                JOIN claims c ON c.id = f.claim_id
                JOIN documents d ON d.id = c.document_id
                WHERE d.project_id = ?
                GROUP BY f.verified
                """,
                (project_id,),
            ).fetchall()
            verification_map = {row["verified"]: row["cnt"] for row in verification_rows}
            fact_type_rows = conn.execute(
                """
                SELECT f.fact_type, COUNT(*) AS cnt
                FROM facts f
                JOIN claims c ON c.id = f.claim_id
                JOIN documents d ON d.id = c.document_id
                WHERE d.project_id = ?
                GROUP BY f.fact_type
                """,
                (project_id,),
            ).fetchall()
            entity_type_rows = conn.execute(
                "SELECT type, COUNT(*) AS cnt FROM entities WHERE project_id = ? GROUP BY type",
                (project_id,),
            ).fetchall()
            cursor = conn.execute(
                """
                INSERT INTO evidence_snapshots (
                    project_id, trigger_document, trigger_action, facts_count, entities_count,
                    claims_count, contradictions_count, document_count, avg_confidence,
                    max_confidence, min_confidence, verified_count, contradicted_count,
                    pending_count, fact_types_distribution, entity_types_distribution
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    trigger_document,
                    trigger_action,
                    facts_count,
                    entities_count,
                    claims_count,
                    len(contradictions),
                    document_count,
                    round(confidence_row["avg_c"] or 0.0, 4),
                    round(confidence_row["max_c"] or 0.0, 4),
                    round(confidence_row["min_c"] or 0.0, 4),
                    int(verification_map.get("supported", 0)),
                    int(verification_map.get("contradicted", 0)),
                    int(verification_map.get("pending", 0)),
                    json.dumps({row["fact_type"]: row["cnt"] for row in fact_type_rows}),
                    json.dumps({row["type"]: row["cnt"] for row in entity_type_rows}),
                ),
            )
            return int(cursor.lastrowid)

    def get_state_history(self, project_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence_snapshots WHERE project_id = ? ORDER BY created_at ASC, id ASC",
                (project_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["fact_types_distribution"] = json.loads(item["fact_types_distribution"] or "{}")
            item["entity_types_distribution"] = json.loads(item["entity_types_distribution"] or "{}")
            result.append(item)
        return result

    def get_evidence_state(self, project_id: str) -> dict[str, Any]:
        facts = self.get_facts(project_id=project_id)
        contradictions = self.get_contradictions(project_id)
        unique_sources = []
        seen = set()
        for fact in facts:
            key = (fact.get("filename"), fact.get("page"), fact.get("paragraph_id"))
            if key in seen:
                continue
            seen.add(key)
            unique_sources.append(
                {
                    "document": fact.get("filename", ""),
                    "page": fact.get("page"),
                    "paragraph_id": fact.get("paragraph_id"),
                }
            )
        confidence_by_fact_type: dict[str, list[float]] = {}
        for fact in facts:
            confidence_by_fact_type.setdefault(str(fact["fact_type"]), []).append(float(fact.get("confidence") or 0.0))
        aggregate = round(
            sum(float(fact.get("confidence") or 0.0) for fact in facts) / len(facts),
            4,
        ) if facts else 0.0
        return {
            "Et": {
                "facts": [
                    {
                        "entity": fact["entity_name"],
                        "predicate": fact["fact_type"],
                        "value": fact["value"],
                        "confidence": fact["confidence"],
                        "verified": fact["verified"],
                    }
                    for fact in facts
                ],
                "sources": unique_sources,
                "contradictions": [
                    {
                        "entity": row["entity_name"],
                        "predicate": row["fact_type"],
                        "values": str(row["distinct_values"] or "").split(","),
                        "value_count": row["value_count"],
                    }
                    for row in contradictions
                ],
                "confidence": {
                    "aggregate": aggregate,
                    "by_fact_type": {
                        fact_type: round(sum(values) / len(values), 4)
                        for fact_type, values in confidence_by_fact_type.items()
                    },
                },
            },
            "metadata": {
                "document_count": len({fact.get("filename") for fact in facts if fact.get("filename")}),
                "facts_count": len(facts),
                "sources_count": len(unique_sources),
                "contradictions_count": len(contradictions),
            },
        }

    def compute_delta(self, project_id: str, snapshot_id_before: int, snapshot_id_after: int) -> dict[str, Any]:
        with self._conn() as conn:
            before = conn.execute(
                "SELECT * FROM evidence_snapshots WHERE id = ? AND project_id = ?",
                (snapshot_id_before, project_id),
            ).fetchone()
            after = conn.execute(
                "SELECT * FROM evidence_snapshots WHERE id = ? AND project_id = ?",
                (snapshot_id_after, project_id),
            ).fetchone()
        if not before or not after:
            return {"error": "Snapshot not found", "delta": None}
        before_ft = json.loads(before["fact_types_distribution"] or "{}")
        after_ft = json.loads(after["fact_types_distribution"] or "{}")
        new_fact_types = [fact_type for fact_type in after_ft if fact_type not in before_ft]
        return {
            "before_snapshot_id": snapshot_id_before,
            "after_snapshot_id": snapshot_id_after,
            "delta": {
                "facts_added": max(0, after["facts_count"] - before["facts_count"]),
                "facts_removed": max(0, before["facts_count"] - after["facts_count"]),
                "entities_added": max(0, after["entities_count"] - before["entities_count"]),
                "entities_removed": max(0, before["entities_count"] - after["entities_count"]),
                "claims_added": max(0, after["claims_count"] - before["claims_count"]),
                "contradictions_added": max(0, after["contradictions_count"] - before["contradictions_count"]),
                "contradictions_resolved": max(0, before["contradictions_count"] - after["contradictions_count"]),
                "confidence_change": round(after["avg_confidence"] - before["avg_confidence"], 4),
                "documents_added": max(0, after["document_count"] - before["document_count"]),
                "new_fact_types": new_fact_types,
                "trigger": after["trigger_document"],
            },
        }

    def get_evidence_units(
        self,
        project_id: str,
        entity_name: Optional[str] = None,
        fact_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            conditions = ["d.project_id = ?"]
            params: list[Any] = [project_id]
            if entity_name:
                conditions.append("LOWER(e.name) = LOWER(?)")
                params.append(entity_name)
            if fact_type:
                conditions.append("f.fact_type = ?")
                params.append(fact_type)
            rows = conn.execute(
                f"""
                SELECT
                    f.id AS fact_id,
                    e.name AS entity,
                    f.fact_type AS predicate,
                    f.value,
                    f.verified,
                    d.filename AS source_document,
                    fs.page AS source_page,
                    fs.paragraph_id AS source_paragraph,
                    fs.text AS source_text,
                    c.page AS claim_page,
                    c.paragraph_id AS claim_paragraph,
                    c.confidence AS kappa
                FROM facts f
                JOIN claims c ON c.id = f.claim_id
                JOIN entities e ON e.id = f.entity_id
                JOIN documents d ON d.id = c.document_id
                LEFT JOIN fact_sources fs ON fs.fact_id = f.id
                WHERE {' AND '.join(conditions)}
                ORDER BY f.id
                LIMIT ?
                """,
                params + [limit],
            ).fetchall()
        return [
            {
                "claim": {
                    "entity": row["entity"],
                    "predicate": row["predicate"],
                    "value": row["value"],
                },
                "source": {
                    "document": row["source_document"],
                    "page": row["source_page"],
                    "paragraph_id": row["source_paragraph"],
                    "text": (row["source_text"] or "")[:200],
                },
                "context": {
                    "claim_page": row["claim_page"],
                    "claim_paragraph": row["claim_paragraph"],
                },
                "confidence": row["kappa"],
                "verified": row["verified"],
                "fact_id": row["fact_id"],
            }
            for row in rows
        ]

    def get_paragraphs_for_entity(self, project_id: str, entity_name: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT
                    c.paragraph_id,
                    c.page,
                    c.text AS claim_text,
                    d.filename
                FROM facts f
                JOIN claims c ON c.id = f.claim_id
                JOIN entities e ON e.id = f.entity_id
                JOIN documents d ON d.id = c.document_id
                WHERE d.project_id = ?
                  AND LOWER(e.name) = LOWER(?)
                  AND c.paragraph_id IS NOT NULL
                  AND c.paragraph_id != ''
                ORDER BY d.filename, c.page
                """,
                (project_id, entity_name),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_paragraphs_for_fact_type(self, project_id: str, fact_type: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT
                    c.paragraph_id,
                    c.page,
                    c.text AS claim_text,
                    e.name AS entity_name,
                    f.value,
                    d.filename
                FROM facts f
                JOIN claims c ON c.id = f.claim_id
                JOIN entities e ON e.id = f.entity_id
                JOIN documents d ON d.id = c.document_id
                WHERE d.project_id = ?
                  AND f.fact_type = ?
                  AND c.paragraph_id IS NOT NULL
                  AND c.paragraph_id != ''
                ORDER BY d.filename, c.page
                """,
                (project_id, fact_type),
            ).fetchall()
        return [dict(row) for row in rows]

    def derive_knowledge(self, project_id: str) -> dict[str, Any]:
        from collections import defaultdict

        facts = self.get_facts(project_id=project_id)
        contradictions = self.get_contradictions(project_id)
        entity_facts: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        entity_types: dict[str, str] = {}
        contradiction_map: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for fact in facts:
            entity_name = str(fact.get("entity_name") or "")
            entity_types[entity_name] = str(fact.get("entity_type") or "custom")
            entity_facts[entity_name][str(fact.get("fact_type") or "general")].append(fact)

        for contradiction in contradictions:
            entity_name = str(contradiction.get("entity_name") or "")
            contradiction_map[entity_name].append(
                {
                    "predicate": contradiction.get("fact_type", ""),
                    "values": str(contradiction.get("distinct_values") or "").split(","),
                    "confidence_spread": 0.0,
                }
            )

        expected_by_type = {
            "organization": ["party", "jurisdiction", "governing_law", "payment_term", "payment_amount", "liability_cap", "termination", "renewal"],
            "person": ["role", "contact", "location"],
        }

        entities_knowledge = []
        total_items = 0
        high_conf_count = 0
        source_counts: list[int] = []

        for entity_name, fact_map in entity_facts.items():
            entity_type = entity_types.get(entity_name, "custom")
            known_facts = []
            for fact_type, items in fact_map.items():
                best = max(items, key=lambda item: float(item.get("confidence") or 0.0))
                confidence = float(best.get("confidence") or 0.0)
                source_count = len(items)
                known_facts.append(
                    {
                        "predicate": fact_type,
                        "value": best.get("value", ""),
                        "confidence": confidence,
                        "sources": source_count,
                        "status": "high_confidence" if confidence >= 0.7 else "low_confidence",
                    }
                )
                total_items += 1
                if confidence >= 0.7:
                    high_conf_count += 1
                source_counts.append(source_count)

            expected = expected_by_type.get(entity_type, [])
            known_types = set(fact_map.keys())
            completeness = len(known_types & set(expected)) / len(expected) if expected else 1.0
            missing = [fact_type for fact_type in expected if fact_type not in known_types]

            entities_knowledge.append(
                {
                    "entity": entity_name,
                    "type": entity_type,
                    "known_facts": sorted(known_facts, key=lambda item: -item["confidence"]),
                    "unresolved_contradictions": contradiction_map.get(entity_name, []),
                    "completeness": round(completeness, 2),
                    "missing_predicates": missing,
                }
            )

        entities_knowledge.sort(key=lambda item: (-item["completeness"], item["entity"]))
        knowledge_gaps = [
            {
                "entity": item["entity"],
                "missing_predicates": item["missing_predicates"],
                "gap_severity": "high" if len(item["missing_predicates"]) >= 3 else "medium",
            }
            for item in entities_knowledge
            if item["missing_predicates"]
        ]
        avg_sources = round(sum(source_counts) / len(source_counts), 1) if source_counts else 0.0
        contradiction_count = len(contradictions)

        return {
            "knowledge": {
                "entities": entities_knowledge,
                "global_metrics": {
                    "total_knowledge_items": total_items,
                    "high_confidence_ratio": round(high_conf_count / total_items, 2) if total_items else 0.0,
                    "contradiction_ratio": round(contradiction_count / total_items, 2) if total_items else 0.0,
                    "avg_sources_per_fact": avg_sources,
                },
            },
            "knowledge_gaps": knowledge_gaps,
        }

    def get_confidence_accumulation(
        self,
        project_id: str,
        entity_name: Optional[str] = None,
        fact_type: Optional[str] = None,
    ) -> dict[str, Any]:
        from collections import defaultdict

        with self._conn() as conn:
            conditions = ["d.project_id = ?"]
            params: list[Any] = [project_id]
            if entity_name:
                conditions.append("LOWER(e.name) = LOWER(?)")
                params.append(entity_name)
            if fact_type:
                conditions.append("f.fact_type = ?")
                params.append(fact_type)
            rows = conn.execute(
                f"""
                SELECT
                    e.name AS entity_name,
                    f.fact_type,
                    f.value,
                    c.confidence,
                    c.created_at,
                    d.filename
                FROM facts f
                JOIN claims c ON c.id = f.claim_id
                JOIN entities e ON e.id = f.entity_id
                JOIN documents d ON d.id = c.document_id
                WHERE {' AND '.join(conditions)}
                ORDER BY e.name, f.fact_type, c.created_at ASC
                """,
                params,
            ).fetchall()

        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            key = f"{row['entity_name']}|{row['fact_type']}"
            groups[key].append(dict(row))

        curves = []
        for key, records in groups.items():
            entity, fact_type_value = key.split("|", 1)
            value_confidences: dict[str, list[float]] = defaultdict(list)
            curve = []
            for record in records:
                normalized_value = str(record["value"] or "").strip().lower()
                value_confidences[normalized_value].append(float(record["confidence"] or 0.0))
                value_count = len(value_confidences)
                penalty = 1.0 / value_count if value_count > 1 else 1.0
                aggregate = self._aggregate_support([self._aggregate_support(values) * penalty for values in value_confidences.values()])
                point = {
                    "document": record["filename"],
                    "claim_confidence": record["confidence"],
                    "aggregate_after": round(aggregate, 4),
                    "timestamp": record["created_at"],
                }
                if value_count > 1:
                    point["note"] = f"contradiction ({value_count} distinct values)"
                curve.append(point)
            curves.append({"entity": entity, "fact_type": fact_type_value, "curve": curve})
        return {"accumulation_curves": curves}

    def get_entity_clusters(self, project_id: str, entity_name: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    f.fact_type,
                    COUNT(*) AS fact_count,
                    ROUND(AVG(c.confidence), 3) AS avg_confidence,
                    COUNT(DISTINCT LOWER(f.value)) AS distinct_values,
                    GROUP_CONCAT(DISTINCT d.filename) AS source_documents
                FROM facts f
                JOIN entities e ON e.id = f.entity_id
                JOIN claims c ON c.id = f.claim_id
                JOIN documents d ON d.id = c.document_id
                WHERE e.project_id = ? AND e.name = ? COLLATE NOCASE
                GROUP BY f.fact_type
                ORDER BY fact_count DESC
                """,
                (project_id, entity_name),
            ).fetchall()
            clusters = []
            for row in rows:
                item = dict(row)
                item["has_contradictions"] = item["distinct_values"] > 1
                top_value = conn.execute(
                    """
                    SELECT f.value, COUNT(*) AS cnt
                    FROM facts f
                    JOIN entities e ON e.id = f.entity_id
                    JOIN claims c ON c.id = f.claim_id
                    JOIN documents d ON d.id = c.document_id
                    WHERE e.project_id = ? AND e.name = ? COLLATE NOCASE AND f.fact_type = ?
                    GROUP BY LOWER(f.value)
                    ORDER BY cnt DESC
                    LIMIT 1
                    """,
                    (project_id, entity_name, item["fact_type"]),
                ).fetchone()
                item["top_value"] = top_value["value"] if top_value else ""
                clusters.append(item)
        return clusters

    def get_cluster_facts(self, project_id: str, entity_name: str, fact_type: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    f.id AS fact_id,
                    f.fact_type,
                    f.value,
                    f.verified,
                    e.name AS entity_name,
                    c.confidence,
                    c.page,
                    d.filename,
                    c.text AS claim_text
                FROM facts f
                JOIN entities e ON e.id = f.entity_id
                JOIN claims c ON c.id = f.claim_id
                JOIN documents d ON d.id = c.document_id
                WHERE e.project_id = ? AND e.name = ? COLLATE NOCASE AND f.fact_type = ?
                ORDER BY c.confidence DESC
                LIMIT ?
                """,
                (project_id, entity_name, fact_type, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_knowledge_state(self, project_id: str) -> dict[str, Any]:
        """
        Returns the computed knowledge state for a given project context.

        The state is:
        - derived from all available claims
        - computed (not stored as absolute truth)
        - inclusive of contradictions
        """
        facts = self.get_facts(project_id=project_id)
        contradictions = self.get_contradictions(project_id)
        alias_groups = self.get_alias_groups(project_id)
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        seen_nodes: set[str] = set()
        seen_edges: set[tuple[str, str, str]] = set()
        for fact in facts:
            entity_node = f"entity:{fact['entity_name']}"
            doc_node = f"doc:{fact['filename']}"
            fact_node = f"fact:{fact['fact_id']}"
            if entity_node not in seen_nodes:
                nodes.append({"id": entity_node, "type": "entity", "label": fact["entity_name"]})
                seen_nodes.add(entity_node)
            if doc_node not in seen_nodes:
                nodes.append({"id": doc_node, "type": "document", "label": fact["filename"]})
                seen_nodes.add(doc_node)
            if fact_node not in seen_nodes:
                nodes.append(
                    {
                        "id": fact_node,
                        "type": "fact",
                        "label": f"{fact['fact_type']} = {fact['value']}",
                        "confidence": fact["confidence"],
                    }
                )
                seen_nodes.add(fact_node)
            for source, target, edge_type in [
                (entity_node, fact_node, "has_fact"),
                (fact_node, doc_node, "sourced_from"),
            ]:
                key = (source, target, edge_type)
                if key not in seen_edges:
                    edges.append({"source": source, "target": target, "type": edge_type})
                    seen_edges.add(key)
        for row in contradictions:
            values = str(row["distinct_values"] or "").split(",")
            for value in values:
                fact_nodes = [f"fact:{fact['fact_id']}" for fact in facts if fact["entity_name"] == row["entity_name"] and fact["fact_type"] == row["fact_type"] and fact["value"] == value]
                for fact_node in fact_nodes:
                    for other in [f"fact:{fact['fact_id']}" for fact in facts if fact["entity_name"] == row["entity_name"] and fact["fact_type"] == row["fact_type"] and fact["value"] != value]:
                        key = (fact_node, other, "contradicts")
                        if key not in seen_edges:
                            edges.append({"source": fact_node, "target": other, "type": "contradicts"})
                            seen_edges.add(key)
        for group in alias_groups:
            canonical = f"entity:{group['canonical']['name']}"
            for alias in group["aliases"]:
                alias_node = f"entity:{alias['name']}"
                key = (alias_node, canonical, "alias_of")
                if key not in seen_edges:
                    edges.append({"source": alias_node, "target": canonical, "type": "alias_of"})
                    seen_edges.add(key)
        return {
            "nodes": nodes,
            "edges": edges,
            "metrics": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "entity_count": len([node for node in nodes if node["type"] == "entity"]),
                "fact_count": len([node for node in nodes if node["type"] == "fact"]),
                "document_count": len([node for node in nodes if node["type"] == "document"]),
            },
        }

    # ------------------------------------------------------------------
    # Knowledge Ledger (append-only)
    # ------------------------------------------------------------------

    def _canonical_claim_set(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.get_facts(project_id=project_id)
        canonical = [
            {
                "entity": row["entity_name"],
                "predicate": row["fact_type"],
                "value": row["value"],
                "confidence": round(float(row["confidence"] or 0.0), 6),
                "document": row["filename"],
                "page": row["page"],
                "paragraph_id": row["paragraph_id"] or "",
                "verified": row["verified"],
                "fact_id": int(row["fact_id"]),
            }
            for row in rows
        ]
        canonical.sort(
            key=lambda item: (
                item["entity"],
                item["predicate"],
                item["value"],
                item["document"],
                item["page"] if item["page"] is not None else -1,
                item["paragraph_id"],
                item["fact_id"],
            )
        )
        return canonical

    def _hash_payload(self, payload: Any) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _canonical_claim_snapshot(self, project_id: str) -> list[dict[str, Any]]:
        claim_set = self._canonical_claim_set(project_id)
        snapshot_by_id: dict[str, dict[str, Any]] = {}

        for item in claim_set:
            canonical = {
                "entity": str(item["entity"]),
                "predicate": str(item["predicate"]),
                "value": str(item["value"]),
                "confidence": round(float(item["confidence"]), 6),
            }
            canonical_claim_id = self._hash_payload(canonical)
            snapshot_by_id[canonical_claim_id] = {
                "canonical_claim_id": canonical_claim_id,
                **canonical,
            }

        snapshot = list(snapshot_by_id.values())

        snapshot.sort(
            key=lambda item: (
                item["entity"],
                item["predicate"],
                item["value"],
                item["confidence"],
                item["canonical_claim_id"],
            )
        )
        return snapshot

    def get_latest_knowledge_state_version(self, project_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, project_id, parent_id, claim_set_id, extraction_config_version,
                       normalization_version, state_signature, created_at
                FROM knowledge_state_versions
                WHERE project_id = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_knowledge_state_versions(self, project_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, project_id, parent_id, claim_set_id, extraction_config_version,
                       normalization_version, state_signature, created_at
                FROM knowledge_state_versions
                WHERE project_id = ?
                ORDER BY rowid DESC
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_knowledge_state_version(self, version_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, project_id, parent_id, claim_set_id, extraction_config_version,
                       normalization_version, state_signature, created_at
                FROM knowledge_state_versions
                WHERE id = ?
                """,
                (version_id,),
            ).fetchone()
        return dict(row) if row else None

    def create_knowledge_state_version(
        self,
        project_id: str,
        extraction_config_version: str,
        normalization_version: str,
    ) -> dict[str, Any]:
        parent = self.get_latest_knowledge_state_version(project_id)
        parent_signature = parent["state_signature"] if parent else ""

        claim_set = self._canonical_claim_set(project_id)
        claim_set_id = self._hash_payload(claim_set)

        state_signature = self._hash_payload(
            {
                "claim_set": claim_set,
                "extraction_config": extraction_config_version,
                "normalization": normalization_version,
                "parent_signature": parent_signature,
            }
        )

        version_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        claim_snapshot = self._canonical_claim_snapshot(project_id)

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_state_versions (
                    id, project_id, parent_id, claim_set_id,
                    extraction_config_version, normalization_version,
                    state_signature, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    project_id,
                    parent["id"] if parent else None,
                    claim_set_id,
                    str(extraction_config_version),
                    str(normalization_version),
                    state_signature,
                    created_at,
                ),
            )

            conn.executemany(
                """
                INSERT INTO state_claim_snapshots (
                    state_version_id, canonical_claim_id, entity, predicate, value, confidence
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        version_id,
                        row["canonical_claim_id"],
                        row["entity"],
                        row["predicate"],
                        row["value"],
                        float(row["confidence"]),
                    )
                    for row in claim_snapshot
                ],
            )

        return {
            "id": version_id,
            "project_id": project_id,
            "parent_id": parent["id"] if parent else None,
            "claim_set_id": claim_set_id,
            "extraction_config_version": str(extraction_config_version),
            "normalization_version": str(normalization_version),
            "state_signature": state_signature,
            "created_at": created_at,
        }

    def get_state_claim_snapshots(self, version_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT state_version_id, canonical_claim_id, entity, predicate, value, confidence
                FROM state_claim_snapshots
                WHERE state_version_id = ?
                ORDER BY entity, predicate, value, confidence, canonical_claim_id
                """,
                (version_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def diff_knowledge_state_versions(self, state_a: str, state_b: str) -> dict[str, Any]:
        version_a = self.get_knowledge_state_version(state_a)
        version_b = self.get_knowledge_state_version(state_b)
        if version_a is None:
            raise ValueError(f"knowledge_state_version '{state_a}' not found")
        if version_b is None:
            raise ValueError(f"knowledge_state_version '{state_b}' not found")
        if version_a["project_id"] != version_b["project_id"]:
            raise ValueError("Cannot diff states from different projects")

        rows_a = self.get_state_claim_snapshots(state_a)
        rows_b = self.get_state_claim_snapshots(state_b)

        by_id_a = {row["canonical_claim_id"]: row for row in rows_a}
        by_id_b = {row["canonical_claim_id"]: row for row in rows_b}

        def key_fn(row: dict[str, Any]) -> tuple[str, str]:
            return (str(row["entity"]), str(row["predicate"]))

        grouped_a: dict[tuple[str, str], list[dict[str, Any]]] = {}
        grouped_b: dict[tuple[str, str], list[dict[str, Any]]] = {}

        for row in rows_a:
            grouped_a.setdefault(key_fn(row), []).append(row)
        for row in rows_b:
            grouped_b.setdefault(key_fn(row), []).append(row)

        consumed_a: set[str] = set()
        consumed_b: set[str] = set()
        changed: list[dict[str, Any]] = []

        for semantic_key in sorted(set(grouped_a.keys()) & set(grouped_b.keys())):
            left = sorted(
                grouped_a[semantic_key],
                key=lambda row: (row["value"], float(row["confidence"]), row["canonical_claim_id"]),
            )
            right = sorted(
                grouped_b[semantic_key],
                key=lambda row: (row["value"], float(row["confidence"]), row["canonical_claim_id"]),
            )

            for before, after in zip(left, right):
                value_changed = str(before["value"]) != str(after["value"])
                confidence_changed = float(before["confidence"]) != float(after["confidence"])
                if value_changed or confidence_changed:
                    consumed_a.add(before["canonical_claim_id"])
                    consumed_b.add(after["canonical_claim_id"])
                    changed.append(
                        {
                            "entity": str(before["entity"]),
                            "predicate": str(before["predicate"]),
                            "before": {
                                "canonical_claim_id": before["canonical_claim_id"],
                                "entity": str(before["entity"]),
                                "predicate": str(before["predicate"]),
                                "value": str(before["value"]),
                                "confidence": float(before["confidence"]),
                            },
                            "after": {
                                "canonical_claim_id": after["canonical_claim_id"],
                                "entity": str(after["entity"]),
                                "predicate": str(after["predicate"]),
                                "value": str(after["value"]),
                                "confidence": float(after["confidence"]),
                            },
                        }
                    )

        added = [
            {
                "canonical_claim_id": row["canonical_claim_id"],
                "entity": str(row["entity"]),
                "predicate": str(row["predicate"]),
                "value": str(row["value"]),
                "confidence": float(row["confidence"]),
            }
            for claim_id, row in sorted(by_id_b.items(), key=lambda item: item[0])
            if claim_id not in by_id_a and claim_id not in consumed_b
        ]

        removed = [
            {
                "canonical_claim_id": row["canonical_claim_id"],
                "entity": str(row["entity"]),
                "predicate": str(row["predicate"]),
                "value": str(row["value"]),
                "confidence": float(row["confidence"]),
            }
            for claim_id, row in sorted(by_id_a.items(), key=lambda item: item[0])
            if claim_id not in by_id_b and claim_id not in consumed_a
        ]

        return {
            "state_a": state_a,
            "state_b": state_b,
            "added": added,
            "removed": removed,
            "changed": changed,
        }

    def verify_knowledge_state_signature(self, version_id: str) -> bool:
        row = self.get_knowledge_state_version(version_id)
        if row is None:
            return False

        parent_signature = ""
        if row["parent_id"]:
            parent = self.get_knowledge_state_version(row["parent_id"])
            if parent is None:
                return False
            parent_signature = parent["state_signature"]

        claim_set = self._canonical_claim_set(row["project_id"])
        claim_set_id = self._hash_payload(claim_set)
        if claim_set_id != row["claim_set_id"]:
            return False

        recomputed_signature = self._hash_payload(
            {
                "claim_set": claim_set,
                "extraction_config": row["extraction_config_version"],
                "normalization": row["normalization_version"],
                "parent_signature": parent_signature,
            }
        )
        return recomputed_signature == row["state_signature"]

    def log_query_execution(
        self,
        project_id: str,
        state_version_id: str,
        protocol_id: str | None,
        query: str,
        result_value: Any,
        confidence: float,
        supporting_claims: list[str],
        contradictions: list[str],
        evidence_selection: list[str],
        weighting: list[float],
        query_mode: str = "explicit_only",
        used_knowledge_levels: list[str] | None = None,
        grounding_status: str | None = None,
        supporting_fact_ids: list[str] | None = None,
        contradiction_fact_ids: list[str] | None = None,
        answer_type: str | None = None,
    ) -> dict[str, Any]:
        execution_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO query_executions (
                    id, project_id, state_version_id, protocol_id, query, result_value,
                    confidence, supporting_claims, contradictions,
                    evidence_selection, weighting, query_mode, used_knowledge_levels,
                    grounding_status, supporting_fact_ids, contradiction_fact_ids,
                    answer_type, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    project_id,
                    state_version_id,
                    protocol_id,
                    query,
                    None if result_value is None else json.dumps(result_value),
                    float(confidence),
                    json.dumps(supporting_claims),
                    json.dumps(contradictions),
                    json.dumps(evidence_selection),
                    json.dumps(weighting),
                    str(query_mode or "explicit_only"),
                    json.dumps(list(used_knowledge_levels or [])),
                    grounding_status,
                    json.dumps(list(supporting_fact_ids or supporting_claims)),
                    json.dumps(list(contradiction_fact_ids or contradictions)),
                    answer_type,
                    created_at,
                ),
            )

        return {
            "id": execution_id,
            "project_id": project_id,
            "state_version_id": state_version_id,
            "protocol_id": protocol_id,
            "query": query,
            "result_value": result_value,
            "confidence": float(confidence),
            "supporting_claims": supporting_claims,
            "contradictions": contradictions,
            "evidence_selection": evidence_selection,
            "weighting": weighting,
            "query_mode": str(query_mode or "explicit_only"),
            "used_knowledge_levels": list(used_knowledge_levels or []),
            "grounding_status": grounding_status,
            "supporting_fact_ids": list(supporting_fact_ids or supporting_claims),
            "contradiction_fact_ids": list(contradiction_fact_ids or contradictions),
            "answer_type": answer_type,
            "created_at": created_at,
        }

    def log_scenario_specific_evidence(
        self,
        *,
        project_id: str,
        query_execution_id: str,
        trace_id: str | None,
        scenario_specific_evidence: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        scenario_id = f"scenario:{query_execution_id}"
        created: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc).isoformat()

        with self._conn() as conn:
            for index, unit in enumerate(scenario_specific_evidence, start=1):
                evidence_id = str(unit.get("id") or uuid.uuid4())
                derived_from = list(unit.get("derived_from") or [])
                used_by_inference_ids = list(unit.get("used_by_inference_ids") or [])
                lineage = dict(unit.get("lineage") or {})
                lineage.setdefault("query_execution_id", query_execution_id)
                lineage.setdefault("source_index", index)
                row = {
                    "id": evidence_id,
                    "scenario_id": scenario_id,
                    "project_id": project_id,
                    "query_execution_id": query_execution_id,
                    "trace_id": trace_id,
                    "evidence_type": str(unit.get("evidence_type") or "scenario_observation"),
                    "subject": unit.get("subject"),
                    "predicate": unit.get("predicate"),
                    "object": unit.get("object"),
                    "value": unit.get("value"),
                    "confidence": float(unit.get("confidence") or 0.0),
                    "source": str(unit.get("source") or "llm_scenario_extractor"),
                    "derived_from": derived_from,
                    "used_by_inference_ids": used_by_inference_ids,
                    "promotion_policy": "never_automatic",
                    "lineage": lineage,
                    "quote": unit.get("quote"),
                    "critical": bool(unit.get("critical", False)),
                    "created_at": now,
                }
                conn.execute(
                    """
                    INSERT INTO scenario_specific_evidence (
                        id, scenario_id, project_id, query_execution_id, trace_id,
                        evidence_type, subject, predicate, object, value, confidence,
                        source, derived_from, used_by_inference_ids, promotion_policy,
                        lineage, quote, critical, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["scenario_id"],
                        row["project_id"],
                        row["query_execution_id"],
                        row["trace_id"],
                        row["evidence_type"],
                        row["subject"],
                        row["predicate"],
                        row["object"],
                        None if row["value"] is None else json.dumps(row["value"]),
                        row["confidence"],
                        row["source"],
                        json.dumps(row["derived_from"]),
                        json.dumps(row["used_by_inference_ids"]),
                        row["promotion_policy"],
                        json.dumps(row["lineage"], sort_keys=True),
                        row["quote"],
                        1 if row["critical"] else 0,
                        row["created_at"],
                    ),
                )
                created.append(row)

        return created

    def list_scenario_specific_evidence(self, query_execution_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM scenario_specific_evidence
                WHERE query_execution_id = ?
                ORDER BY rowid ASC
                """,
                (query_execution_id,),
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            raw_value = data.get("value")
            data["value"] = None if raw_value is None else json.loads(raw_value)
            data["derived_from"] = json.loads(data.get("derived_from") or "[]")
            data["used_by_inference_ids"] = json.loads(data.get("used_by_inference_ids") or "[]")
            data["lineage"] = json.loads(data.get("lineage") or "{}")
            data["critical"] = bool(data.get("critical"))
            result.append(data)
        return result

    def log_source_evidence_candidates(
        self,
        *,
        project_id: str,
        query_execution_id: str,
        trace_id: str | None,
        source_evidence_candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            for index, candidate in enumerate(source_evidence_candidates, start=1):
                lineage = dict(candidate.get("lineage") or {})
                lineage.setdefault("query_execution_id", query_execution_id)
                lineage.setdefault("source_index", index)
                row = {
                    "id": str(candidate.get("id") or uuid.uuid4()),
                    "project_id": project_id,
                    "query_execution_id": query_execution_id,
                    "trace_id": trace_id,
                    "evidence_candidate_level": str(candidate.get("evidence_candidate_level") or "L1_evidence_candidate"),
                    "entity": candidate.get("entity"),
                    "predicate": str(candidate.get("predicate") or ""),
                    "value": candidate.get("value"),
                    "confidence": float(candidate.get("confidence") or 0.0),
                    "source": str(candidate.get("source") or "inline_query_source"),
                    "source_ref": dict(candidate.get("source_ref") or {}),
                    "quote": candidate.get("quote"),
                    "promotion_policy": "never_automatic",
                    "lineage": lineage,
                    "inference_type": str(candidate.get("inference_type") or "deductive"),
                    "inference_form_code": candidate.get("inference_form_code"),
                    "created_at": now,
                }
                conn.execute(
                    """
                    INSERT INTO query_source_evidence_candidates (
                        id, project_id, query_execution_id, trace_id,
                        evidence_candidate_level, entity, predicate, value, confidence,
                        source, source_ref, quote, promotion_policy, lineage,
                        inference_type, inference_form_code, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["project_id"],
                        row["query_execution_id"],
                        row["trace_id"],
                        row["evidence_candidate_level"],
                        row["entity"],
                        row["predicate"],
                        None if row["value"] is None else json.dumps(row["value"]),
                        row["confidence"],
                        row["source"],
                        json.dumps(row["source_ref"], sort_keys=True),
                        row["quote"],
                        row["promotion_policy"],
                        json.dumps(row["lineage"], sort_keys=True),
                        row["inference_type"],
                        row["inference_form_code"],
                        row["created_at"],
                    ),
                )
                created.append(row)
        return created

    def list_source_evidence_candidates(self, query_execution_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM query_source_evidence_candidates
                WHERE query_execution_id = ?
                ORDER BY rowid ASC
                """,
                (query_execution_id,),
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            raw_value = data.get("value")
            data["value"] = None if raw_value is None else json.loads(raw_value)
            data["source_ref"] = json.loads(data.get("source_ref") or "{}")
            data["lineage"] = json.loads(data.get("lineage") or "{}")
            result.append(data)
        return result

    def log_preflight_contradictions(
        self,
        *,
        project_id: str,
        query_execution_id: str,
        trace_id: str | None,
        preflight_contradictions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        created: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            for index, contradiction in enumerate(preflight_contradictions, start=1):
                lineage = dict(contradiction.get("lineage") or {})
                lineage.setdefault("query_execution_id", query_execution_id)
                lineage.setdefault("source_index", index)
                row = {
                    "id": str(contradiction.get("id") or uuid.uuid4()),
                    "project_id": project_id,
                    "query_execution_id": query_execution_id,
                    "trace_id": trace_id,
                    "contradiction_type": str(contradiction.get("contradiction_type") or "preflight_conflict"),
                    "message": str(contradiction.get("message") or "Preflight evidence contradiction detected."),
                    "left_evidence_id": contradiction.get("left_evidence_id"),
                    "right_evidence_id": contradiction.get("right_evidence_id"),
                    "left_scope": contradiction.get("left_scope"),
                    "right_scope": contradiction.get("right_scope"),
                    "left_value": contradiction.get("left_value"),
                    "right_value": contradiction.get("right_value"),
                    "lineage": lineage,
                    "created_at": now,
                }
                conn.execute(
                    """
                    INSERT INTO query_preflight_contradictions (
                        id, project_id, query_execution_id, trace_id, contradiction_type,
                        message, left_evidence_id, right_evidence_id, left_scope,
                        right_scope, left_value, right_value, lineage, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["project_id"],
                        row["query_execution_id"],
                        row["trace_id"],
                        row["contradiction_type"],
                        row["message"],
                        row["left_evidence_id"],
                        row["right_evidence_id"],
                        row["left_scope"],
                        row["right_scope"],
                        None if row["left_value"] is None else json.dumps(row["left_value"]),
                        None if row["right_value"] is None else json.dumps(row["right_value"]),
                        json.dumps(row["lineage"], sort_keys=True),
                        row["created_at"],
                    ),
                )
                created.append(row)
        return created

    def list_preflight_contradictions(self, query_execution_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM query_preflight_contradictions
                WHERE query_execution_id = ?
                ORDER BY rowid ASC
                """,
                (query_execution_id,),
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["left_value"] = None if data.get("left_value") is None else json.loads(data["left_value"])
            data["right_value"] = None if data.get("right_value") is None else json.loads(data["right_value"])
            data["lineage"] = json.loads(data.get("lineage") or "{}")
            result.append(data)
        return result

    def get_query_execution(self, execution_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id, project_id, state_version_id, query, result_value,
                      protocol_id,
                       confidence, supporting_claims, contradictions,
                       evidence_selection, weighting, query_mode, used_knowledge_levels,
                       grounding_status, supporting_fact_ids, contradiction_fact_ids,
                       answer_type, created_at
                FROM query_executions
                WHERE id = ?
                """,
                (execution_id,),
            ).fetchone()
        if row is None:
            return None

        data = dict(row)
        data["result_value"] = None if data["result_value"] is None else json.loads(data["result_value"])
        data["supporting_claims"] = json.loads(data["supporting_claims"])
        data["contradictions"] = json.loads(data["contradictions"])
        data["evidence_selection"] = json.loads(data["evidence_selection"])
        data["weighting"] = json.loads(data["weighting"])
        data["used_knowledge_levels"] = json.loads(data.get("used_knowledge_levels") or "[]")
        data["supporting_fact_ids"] = json.loads(data.get("supporting_fact_ids") or "[]")
        data["contradiction_fact_ids"] = json.loads(data.get("contradiction_fact_ids") or "[]")
        data["scenario_specific_evidence"] = self.list_scenario_specific_evidence(execution_id)
        data["source_evidence_candidates"] = self.list_source_evidence_candidates(execution_id)
        data["preflight_contradictions"] = self.list_preflight_contradictions(execution_id)
        return data

    def list_query_executions(self, project_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT id, project_id, state_version_id, query, result_value,
                      protocol_id,
                       confidence, supporting_claims, contradictions,
                       evidence_selection, weighting, query_mode, used_knowledge_levels,
                       grounding_status, supporting_fact_ids, contradiction_fact_ids,
                       answer_type, created_at
                FROM query_executions
                WHERE project_id = ?
                ORDER BY rowid DESC
                """,
                (project_id,),
            ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["result_value"] = None if data["result_value"] is None else json.loads(data["result_value"])
            data["supporting_claims"] = json.loads(data["supporting_claims"])
            data["contradictions"] = json.loads(data["contradictions"])
            data["evidence_selection"] = json.loads(data["evidence_selection"])
            data["weighting"] = json.loads(data["weighting"])
            data["used_knowledge_levels"] = json.loads(data.get("used_knowledge_levels") or "[]")
            data["supporting_fact_ids"] = json.loads(data.get("supporting_fact_ids") or "[]")
            data["contradiction_fact_ids"] = json.loads(data.get("contradiction_fact_ids") or "[]")
            execution_id = str(data["id"])
            data["scenario_specific_evidence"] = self.list_scenario_specific_evidence(execution_id)
            data["source_evidence_candidates"] = self.list_source_evidence_candidates(execution_id)
            data["preflight_contradictions"] = self.list_preflight_contradictions(execution_id)
            result.append(data)
        return result

    def create_protocol_comparison(
        self,
        protocol_id_a: str,
        protocol_id_b: str,
        query: str,
        diff_result: dict[str, Any],
    ) -> dict[str, Any]:
        comparison_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO protocol_comparisons (id, protocol_id_a, protocol_id_b, query, diff_result, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    comparison_id,
                    protocol_id_a,
                    protocol_id_b,
                    query,
                    json.dumps(diff_result),
                    created_at,
                ),
            )
        return {
            "id": comparison_id,
            "protocol_id_a": protocol_id_a,
            "protocol_id_b": protocol_id_b,
            "query": query,
            "diff_result": diff_result,
            "created_at": created_at,
        }
