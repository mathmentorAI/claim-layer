from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.interfaces import Result


class KnowledgeLedgerRepository:
    """Minimal repository layer for the production knowledge ledger system."""

    def __init__(self, store) -> None:
        self._store = store

    def create_state_version(
        self,
        project_id: str,
        extraction_config_version: str,
        normalization_version: str,
    ) -> Dict[str, Any]:
        return self._store.create_knowledge_state_version(
            project_id=project_id,
            extraction_config_version=extraction_config_version,
            normalization_version=normalization_version,
        )

    def latest_state_version(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self._store.get_latest_knowledge_state_version(project_id)

    def list_state_versions(self, project_id: str) -> List[Dict[str, Any]]:
        return self._store.list_knowledge_state_versions(project_id)

    def state_version(self, version_id: str) -> Optional[Dict[str, Any]]:
        return self._store.get_knowledge_state_version(version_id)

    def state_diff(self, state_a: str, state_b: str) -> Dict[str, Any]:
        return self._store.diff_knowledge_state_versions(state_a, state_b)

    def verify_state(self, version_id: str) -> bool:
        return self._store.verify_knowledge_state_signature(version_id)

    def log_execution(
        self,
        project_id: str,
        state_version_id: str,
        protocol_id: Optional[str],
        query: str,
        result_value: Any,
        confidence: float,
        supporting_claims: List[str],
        contradictions: List[str],
        evidence_selection: List[str],
        weighting: List[float],
        query_mode: str = "explicit_only",
        used_knowledge_levels: Optional[List[str]] = None,
        grounding_status: Optional[str] = None,
        supporting_fact_ids: Optional[List[str]] = None,
        contradiction_fact_ids: Optional[List[str]] = None,
        answer_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._store.log_query_execution(
            project_id=project_id,
            state_version_id=state_version_id,
            protocol_id=protocol_id,
            query=query,
            result_value=result_value,
            confidence=confidence,
            supporting_claims=supporting_claims,
            contradictions=contradictions,
            evidence_selection=evidence_selection,
            weighting=weighting,
            query_mode=query_mode,
            used_knowledge_levels=used_knowledge_levels,
            grounding_status=grounding_status,
            supporting_fact_ids=supporting_fact_ids,
            contradiction_fact_ids=contradiction_fact_ids,
            answer_type=answer_type,
        )

    def query_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        return self._store.get_query_execution(execution_id)

    def list_query_executions(self, project_id: str) -> List[Dict[str, Any]]:
        return self._store.list_query_executions(project_id)

    def log_scenario_specific_evidence(
        self,
        *,
        project_id: str,
        query_execution_id: str,
        trace_id: Optional[str],
        scenario_specific_evidence: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return self._store.log_scenario_specific_evidence(
            project_id=project_id,
            query_execution_id=query_execution_id,
            trace_id=trace_id,
            scenario_specific_evidence=scenario_specific_evidence,
        )

    def list_scenario_specific_evidence(self, query_execution_id: str) -> List[Dict[str, Any]]:
        return self._store.list_scenario_specific_evidence(query_execution_id)

    def log_source_evidence_candidates(
        self,
        *,
        project_id: str,
        query_execution_id: str,
        trace_id: Optional[str],
        source_evidence_candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return self._store.log_source_evidence_candidates(
            project_id=project_id,
            query_execution_id=query_execution_id,
            trace_id=trace_id,
            source_evidence_candidates=source_evidence_candidates,
        )

    def log_preflight_contradictions(
        self,
        *,
        project_id: str,
        query_execution_id: str,
        trace_id: Optional[str],
        preflight_contradictions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return self._store.log_preflight_contradictions(
            project_id=project_id,
            query_execution_id=query_execution_id,
            trace_id=trace_id,
            preflight_contradictions=preflight_contradictions,
        )

    def replay_query_execution(self, execution_id: str, gateway) -> Dict[str, Any]:
        execution = self._store.get_query_execution(execution_id)
        if execution is None:
            raise ValueError(f"query_execution '{execution_id}' not found")

        state_version_id = execution["state_version_id"]
        if state_version_id != "system_init" and not self._store.verify_knowledge_state_signature(state_version_id):
            raise ValueError(
                f"knowledge_state_version '{state_version_id}' failed signature verification"
            )

        replay = {
            "answer": execution.get("result_value"),
            "grounding_status": execution.get("grounding_status"),
            "confidence": float(execution.get("confidence") or 0.0),
            "supporting_claims": [{"id": item} for item in list(execution.get("supporting_claims") or [])],
            "contradictions": [{"id": item} for item in list(execution.get("contradictions") or [])],
        }
        replay["scenario_specific_evidence"] = self._store.list_scenario_specific_evidence(execution_id)
        replay["source_evidence_candidates"] = self._store.list_source_evidence_candidates(execution_id)
        replay["preflight_contradictions"] = self._store.list_preflight_contradictions(execution_id)
        return replay
