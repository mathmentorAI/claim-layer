from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .models import IngestedClaim, IngestedDocument, IngestedEntity, IngestedFact, IngestedSource

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    hash TEXT NOT NULL DEFAULT '',
    pipeline_version TEXT NOT NULL DEFAULT '',
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
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

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
    )


def _as_source(value: IngestedSource | dict[str, Any]) -> IngestedSource:
    if isinstance(value, IngestedSource):
        return value
    return IngestedSource(
        page=value.get("page"),
        paragraph_id=value.get("paragraph_id"),
        text=str(value.get("text") or ""),
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
    )


class ClaimLayerStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    @staticmethod
    def _similarity_score(left: str, right: str) -> float:
        return SequenceMatcher(None, left.lower().strip(), right.lower().strip()).ratio()

    @staticmethod
    def _normalize_value(value: str) -> str:
        import re

        return re.sub(r"[^\w\s]", "", value or "").lower().strip()

    @staticmethod
    def _noisy_or(confidences: list[float]) -> float:
        if not confidences:
            return 0.0
        product = 1.0
        for confidence in confidences:
            bounded = max(0.0, min(1.0, float(confidence)))
            product *= 1.0 - bounded
        return round(1.0 - product, 4)

    def upsert_document(
        self,
        project_id: str,
        filename: str,
        file_hash: str = "",
        pipeline_version: str = "0.1.0",
    ) -> int:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO documents (project_id, filename, hash, pipeline_version)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id, filename) DO UPDATE SET
                    hash = excluded.hash,
                    pipeline_version = excluded.pipeline_version
                """,
                (project_id, filename, file_hash, pipeline_version),
            )
            row = conn.execute(
                "SELECT id FROM documents WHERE project_id = ? AND filename = ?",
                (project_id, filename),
            ).fetchone()
            return int(row["id"])

    def get_document_id(self, project_id: str, filename: str) -> int | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM documents WHERE project_id = ? AND filename = ?",
                (project_id, filename),
            ).fetchone()
            return int(row["id"]) if row else None

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

    def get_entities(self, project_id: str, entity_type: str | None = None) -> list[dict[str, Any]]:
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
    ) -> int | None:
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
        page: int | None = None,
        paragraph_id: str | None = None,
        external_id: str | None = None,
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

    def get_claims(self, document_id: int | None = None, project_id: str | None = None) -> list[dict[str, Any]]:
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
        page: int | None = None,
        paragraph_id: str | None = None,
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

    def ingest_document(self, document: IngestedDocument | dict[str, Any]) -> dict[str, int]:
        payload = document if isinstance(document, IngestedDocument) else IngestedDocument(**document)
        doc_id = self.upsert_document(payload.project_id, payload.filename, payload.file_hash, payload.pipeline_version)
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
        for raw_claim in payload.claims:
            claim = _as_claim(raw_claim)
            if not claim.text:
                continue
            claim_map[claim.claim_id or claim.text] = self.insert_claim(
                document_id=doc_id,
                text=claim.text,
                confidence=claim.confidence,
                page=claim.page,
                paragraph_id=claim.paragraph_id,
                external_id=claim.claim_id or None,
                pipeline_version=payload.pipeline_version,
            )

        facts_inserted = 0
        for raw_fact in payload.facts:
            fact = _as_fact(raw_fact)
            claim_id = claim_map.get(fact.claim_ref)
            entity_id = entity_map.get(fact.entity_ref)
            if claim_id is None or entity_id is None or not fact.value:
                continue
            fact_id = self.insert_fact(claim_id, entity_id, fact.fact_type, fact.value, verified=fact.verified)
            facts_inserted += 1
            for source in fact.sources:
                self.insert_fact_source(
                    fact_id=fact_id,
                    document_id=doc_id,
                    page=source.page,
                    paragraph_id=source.paragraph_id,
                    text=source.text[:500],
                )

        self.capture_snapshot(payload.project_id, trigger_document=payload.filename, trigger_action="ingest")
        return {"documents": 1, "entities": len(entity_map), "claims": len(claim_map), "facts": facts_inserted}

    def get_facts(
        self,
        project_id: str | None = None,
        document_id: int | None = None,
        entity_name: str | None = None,
        fact_type: str | None = None,
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
            if entity_name:
                conditions.append("LOWER(e.name) = LOWER(?)")
                params.append(entity_name)
            if fact_type:
                conditions.append("f.fact_type = ?")
                params.append(fact_type)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY f.id"
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def get_contradictions(self, project_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT
                    COALESCE(canonical.name, e.name) AS entity_name,
                    f.fact_type,
                    GROUP_CONCAT(DISTINCT f.value) AS distinct_values,
                    COUNT(DISTINCT LOWER(f.value)) AS value_count
                FROM facts f
                JOIN entities e ON e.id = f.entity_id
                JOIN claims c ON c.id = f.claim_id
                JOIN documents d ON d.id = c.document_id
                LEFT JOIN entity_aliases ea ON ea.alias_entity_id = e.id
                LEFT JOIN entities canonical ON canonical.id = ea.canonical_entity_id
                WHERE d.project_id = ?
                GROUP BY COALESCE(ea.canonical_entity_id, e.id), f.fact_type
                HAVING COUNT(DISTINCT LOWER(f.value)) > 1
                ORDER BY entity_name, f.fact_type
                """,
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]

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

    def benchmark_facts(self, project_id: str, fact_type: str | None = None) -> list[dict[str, Any]]:
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
            raw_conf = self._noisy_or([float(item.get("confidence") or 0.0) for item in items])
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
        aggregate_confidence = self._noisy_or([item["confidence"] for item in candidate_values])
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
        entity_name: str | None = None,
        fact_type: str | None = None,
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
        entity_name: str | None = None,
        fact_type: str | None = None,
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
                aggregate = self._noisy_or([self._noisy_or(values) * penalty for values in value_confidences.values()])
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

    def get_evidence_graph(self, project_id: str) -> dict[str, Any]:
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
