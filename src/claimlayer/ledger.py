"""Concurrency-safe in-memory and optional SQLite Ledger for ClaimLayer v3."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from claimlayer.models import (
    Assertion,
    FactRecord,
    Policy,
    ResolutionRecord,
    Source,
    Verdict,
    normalize_key,
)
from claimlayer.verifiers.precedence import is_source_active

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subj_key TEXT NOT NULL,
    pred_key TEXT NOT NULL,
    source_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_lookup ON facts(subj_key, pred_key);
CREATE INDEX IF NOT EXISTS idx_facts_source ON facts(source_id);

CREATE TABLE IF NOT EXISTS resolutions (
    subj_key TEXT NOT NULL,
    pred_key TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (subj_key, pred_key)
);

CREATE TABLE IF NOT EXISTS verdicts (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    verdict_id TEXT NOT NULL,
    status TEXT NOT NULL,
    triage_state TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    payload_json TEXT NOT NULL,
    resolution_json TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_verdicts_id ON verdicts(verdict_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_triage ON verdicts(triage_state);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    """Authoritative store for sources, known facts, verdicts, and human resolutions."""

    def __init__(
        self,
        sources: Iterable[Source | dict[str, Any]] | None = None,
        facts: Iterable[FactRecord | dict[str, Any]] | None = None,
        *,
        db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._db_path = Path(db_path) if db_path is not None else None
        self._sources: dict[str, Source] = {}
        self._facts: list[FactRecord] = []
        self._resolutions: dict[tuple[str, str], ResolutionRecord] = {}
        self._verdict_log: list[dict[str, Any]] = []

        if self._db_path is not None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_sqlite()
            self._load_sqlite()

        if sources:
            for src in sources:
                self.add_source(src)
        if facts:
            for fact in facts:
                self.add_fact(fact)

    def _connect(self) -> sqlite3.Connection:
        assert self._db_path is not None
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SQLITE_SCHEMA)

    def _load_sqlite(self) -> None:
        with self._connect() as conn:
            for row in conn.execute("SELECT payload_json FROM sources ORDER BY rowid ASC"):
                data = json.loads(row["payload_json"])
                data.pop("sha256", None)
                src = Source(**data)
                self._sources[src.id] = src

            for row in conn.execute("SELECT payload_json FROM facts ORDER BY id ASC"):
                data = json.loads(row["payload_json"])
                self._facts.append(FactRecord(**data))

            for row in conn.execute("SELECT subj_key, pred_key, payload_json FROM resolutions"):
                data = json.loads(row["payload_json"])
                self._resolutions[(row["subj_key"], row["pred_key"])] = ResolutionRecord(**data)

            for row in conn.execute("SELECT * FROM verdicts ORDER BY seq ASC"):
                self._verdict_log.append(
                    {
                        "seq": row["seq"],
                        "verdict_id": row["verdict_id"],
                        "status": row["status"],
                        "triage_state": row["triage_state"],
                        "agent_id": row["agent_id"],
                        "policy_id": row["policy_id"],
                        "confidence": row["confidence"],
                        "verdict": json.loads(row["payload_json"]),
                        "resolution": (
                            json.loads(row["resolution_json"]) if row["resolution_json"] else None
                        ),
                        "created_at": row["created_at"],
                        "resolved_at": row["resolved_at"],
                    }
                )

    def add_source(self, source: Source | dict[str, Any]) -> Source:
        src = source if isinstance(source, Source) else Source(**source)
        with self._lock:
            self._sources[src.id] = src
            if self._db_path is not None:
                payload = src.to_dict()
                payload.pop("sha256", None)
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO sources(id, payload_json, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            payload_json = excluded.payload_json,
                            updated_at = excluded.updated_at
                        """,
                        (src.id, json.dumps(payload, ensure_ascii=False), _utc_now_iso()),
                    )
        return src

    def get_source(self, source_id: str) -> Source | None:
        with self._lock:
            return self._sources.get(source_id)

    def list_sources(self) -> list[Source]:
        with self._lock:
            return [self._sources[k] for k in sorted(self._sources.keys())]

    def add_fact(self, fact: FactRecord | dict[str, Any]) -> FactRecord:
        rec = fact if isinstance(fact, FactRecord) else FactRecord(**fact)
        with self._lock:
            if rec not in self._facts:
                self._facts.append(rec)
                if self._db_path is not None:
                    with self._connect() as conn:
                        conn.execute(
                            "INSERT INTO facts(subj_key, pred_key, source_id, payload_json) VALUES (?, ?, ?, ?)",
                            (
                                normalize_key(rec.subject),
                                normalize_key(rec.predicate),
                                rec.source_id,
                                json.dumps(rec.to_dict(), ensure_ascii=False),
                            ),
                        )
        return rec

    def get_facts(self, subject: str, predicate: str) -> list[FactRecord]:
        sk = normalize_key(subject)
        pk = normalize_key(predicate)
        with self._lock:
            return [
                f
                for f in self._facts
                if normalize_key(f.subject) == sk and normalize_key(f.predicate) == pk
            ]

    def get_facts_by_source(self, source_id: str) -> list[FactRecord]:
        with self._lock:
            return [f for f in self._facts if f.source_id == source_id]

    def list_facts(self) -> list[FactRecord]:
        with self._lock:
            return list(self._facts)

    def superseded_source_ids(
        self,
        *,
        as_of: str | None = None,
        subject: str | None = None,
        predicate: str | None = None,
    ) -> set[str]:
        """Return IDs of sources superseded globally or for a specific (subject, predicate)."""
        superseded: set[str] = set()
        sk = normalize_key(subject) if subject else None
        pk = normalize_key(predicate) if predicate else None
        with self._lock:
            for src in self._sources.values():
                active, _ = is_source_active(src, as_of)
                if not active or not src.supersedes:
                    continue
                src_facts = [f for f in self._facts if f.source_id == src.id]
                if not src_facts or sk is None or pk is None:
                    superseded.update(src.supersedes)
                else:
                    touches_pair = any(
                        normalize_key(f.subject) == sk and normalize_key(f.predicate) == pk
                        for f in src_facts
                    )
                    if touches_pair:
                        superseded.update(src.supersedes)
        return superseded

    def get_resolution(self, subject: str, predicate: str) -> ResolutionRecord | None:
        key = (normalize_key(subject), normalize_key(predicate))
        with self._lock:
            return self._resolutions.get(key)

    def list_resolutions(self) -> list[ResolutionRecord]:
        with self._lock:
            return list(self._resolutions.values())

    def record_verdict(self, verdict: Verdict) -> dict[str, Any]:
        """Persist a verification verdict into the audit and triage log."""
        now = _utc_now_iso()
        triage_state = "OPEN" if verdict.status == "ESCALATE" else "AUTO_CLOSED"
        payload = verdict.to_dict()
        with self._lock:
            seq = len(self._verdict_log) + 1
            if self._db_path is not None:
                with self._connect() as conn:
                    cur = conn.execute(
                        """
                        INSERT INTO verdicts(
                            verdict_id, status, triage_state, agent_id, policy_id,
                            confidence, payload_json, resolution_json, created_at, resolved_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)
                        """,
                        (
                            verdict.verdict_id,
                            verdict.status,
                            triage_state,
                            verdict.agent_id,
                            verdict.policy_id,
                            verdict.confidence,
                            json.dumps(payload, ensure_ascii=False),
                            now,
                        ),
                    )
                    seq = int(cur.lastrowid or seq)

            entry = {
                "seq": seq,
                "verdict_id": verdict.verdict_id,
                "status": verdict.status,
                "triage_state": triage_state,
                "agent_id": verdict.agent_id,
                "policy_id": verdict.policy_id,
                "confidence": verdict.confidence,
                "verdict": payload,
                "resolution": None,
                "created_at": now,
                "resolved_at": None,
            }
            self._verdict_log.append(entry)
            return dict(entry)

    def resolve_escalation(
        self,
        *,
        verdict_id: str | None = None,
        subject: str,
        predicate: str,
        selected_value: str,
        resolver: str = "human_supervisor",
        action: str = "APPROVE_VALUE",
        note: str = "",
    ) -> dict[str, Any]:
        """Record a 1-click human triage resolution and close matching escalated verdicts."""
        now = _utc_now_iso()
        rec = ResolutionRecord(
            subject=subject,
            predicate=predicate,
            selected_value=selected_value,
            resolver=resolver,
            note=note,
            verdict_id=verdict_id,
            resolved_at=now,
        )
        key = (normalize_key(subject), normalize_key(predicate))
        res_payload = {**rec.to_dict(), "action": action}

        with self._lock:
            if action != "REJECT_TO_AGENT":
                self._resolutions[key] = rec
                if self._db_path is not None:
                    with self._connect() as conn:
                        conn.execute(
                            """
                            INSERT INTO resolutions(subj_key, pred_key, payload_json)
                            VALUES (?, ?, ?)
                            ON CONFLICT(subj_key, pred_key) DO UPDATE SET
                                payload_json = excluded.payload_json
                            """,
                            (key[0], key[1], json.dumps(rec.to_dict(), ensure_ascii=False)),
                        )

            updated_entries: list[dict[str, Any]] = []
            for entry in self._verdict_log:
                if entry["triage_state"] != "OPEN":
                    continue
                matches_id = verdict_id is not None and entry["verdict_id"] == verdict_id
                matches_pair = any(
                    normalize_key(iss.get("subject") or "") == key[0]
                    and normalize_key(iss.get("predicate") or "") == key[1]
                    for iss in entry["verdict"].get("issues", [])
                )
                if matches_id or (verdict_id is None and matches_pair):
                    entry["triage_state"] = (
                        "REJECTED" if action == "REJECT_TO_AGENT" else "RESOLVED"
                    )
                    entry["resolution"] = res_payload
                    entry["resolved_at"] = now
                    updated_entries.append(dict(entry))

                    if self._db_path is not None:
                        with self._connect() as conn:
                            conn.execute(
                                """
                                UPDATE verdicts
                                SET triage_state = ?, resolution_json = ?, resolved_at = ?
                                WHERE seq = ?
                                """,
                                (
                                    entry["triage_state"],
                                    json.dumps(res_payload, ensure_ascii=False),
                                    now,
                                    entry["seq"],
                                ),
                            )

        return {
            "resolution": res_payload,
            "updated_verdicts": len(updated_entries),
        }

    def list_verdicts(self, *, triage_state: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            items = list(reversed(self._verdict_log))
            if triage_state:
                items = [e for e in items if e["triage_state"] == triage_state]
            return [dict(e) for e in items[:limit]]

    def get_verdict_entry(self, verdict_id: str) -> dict[str, Any] | None:
        with self._lock:
            for entry in reversed(self._verdict_log):
                if entry["verdict_id"] == verdict_id:
                    return dict(entry)
            return None

    def get_metrics(self) -> dict[str, Any]:
        """Compute live metrics demonstrating agent supervision bottleneck reduction."""
        with self._lock:
            total = len(self._verdict_log)
            pass_count = sum(1 for e in self._verdict_log if e["status"] == "PASS")
            retry_count = sum(1 for e in self._verdict_log if e["status"] == "RETRY")
            escalate_count = sum(1 for e in self._verdict_log if e["status"] == "ESCALATE")
            open_escalations = sum(1 for e in self._verdict_log if e["triage_state"] == "OPEN")
            resolved_escalations = sum(
                1 for e in self._verdict_log if e["triage_state"] in {"RESOLVED", "REJECTED"}
            )
            autonomous_handled = pass_count + retry_count
            saved_pct = round((autonomous_handled / total) * 100.0, 1) if total > 0 else 0.0

            return {
                "total_verifications": total,
                "auto_approved_pass": pass_count,
                "agent_self_retry": retry_count,
                "escalated_to_human": escalate_count,
                "open_escalations": open_escalations,
                "resolved_escalations": resolved_escalations,
                "human_supervision_saved_pct": saved_pct,
                "sources_count": len(self._sources),
                "facts_count": len(self._facts),
                "resolutions_count": len(self._resolutions),
            }

    def reset(self) -> None:
        """Clear all state (useful for demos and tests)."""
        with self._lock:
            self._sources.clear()
            self._facts.clear()
            self._resolutions.clear()
            self._verdict_log.clear()
            if self._db_path is not None:
                with self._connect() as conn:
                    conn.executescript(
                        "DELETE FROM sources; DELETE FROM facts; DELETE FROM resolutions; DELETE FROM verdicts;"
                    )

    def verify(
        self,
        assertions: Iterable[Assertion | dict[str, Any]],
        policy: Policy | dict[str, Any] | None = None,
        *,
        as_of: str | None = None,
        agent_id: str = "agent",
        record: bool = False,
    ) -> Verdict:
        from claimlayer.verify import verify

        verdict = verify(
            assertions=assertions,
            ledger=self,
            policy=policy,
            as_of=as_of,
            agent_id=agent_id,
        )
        if record:
            self.record_verdict(verdict)
        return verdict
