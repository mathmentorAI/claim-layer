from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from core.derivation_rules import BUILTIN_RULES, RuleChecker

from core.interfaces import (
    BLOCKED_INFERENCE_TYPES,
    Claim,
    InferenceProfile,
    Reason,
    Result,
)
from core.inference_assignment import (
    _ABDUCTIVE_TERMS,
    _contains_any,
    _HEURISTIC_TERMS,
    _NARRATIVE_TERMS,
    _PROBABILISTIC_TERMS,
)


_EXTRA_HEURISTIC_TERMS = (
    "se estima", "estimado", "estimada", "estimación", "estimacion", "estimate", "estimated",
    "podría", "podria", "might", "could", "presuntamente", "presumed", "presuntivo",
)
_EXTRA_ABDUCTIVE_TERMS = (
    "conjetura", "conjecture", "se conjetura", "hipótesis", "hipotesis", "hypothesis",
    "se infiere provisionalmente", "posiblemente", "possibly", "plausible",
)

_ALLEGATION_TERMS = (
    # Legal ES
    "la defensa sostiene", "sostiene que", "afirma que", "alega que", "alegan que",
    "alegación", "alegacion", "alegaciones", "pretensión", "pretension",
    "manifiesta que", "manifestó que", "manifesto que", "según la defensa", "segun la defensa",
    "a juicio de parte", "declaró que", "declaro que", "testificó que", "testifico que",
    "declaración de parte", "declaracion de parte", "declaración testifical", "declaracion testifical",
    "versión de", "version de", "postura de la defensa", "afirmación unilateral",
    # Legal EN
    "defense claims", "claims that", "alleges that", "allegation", "contends that",
    "argues that", "testified that", "assertion", "party statement", "unilateral claim",
    # Clinical / Medical (unverified subjective patient self-report / anamnesis without clinical confirmation)
    "el paciente refiere creer", "paciente refiere sin comprobación", "anamnesis subjetiva no verificada",
    "patient self-reports", "unverified patient report", "subjective complaint without clinical confirmation",
    # Financial / Audit / Corporate (unaudited management projections / forward-looking estimates)
    "la dirección proyecta", "estimación no auditada", "proyección de la gerencia", "previsión no auditada",
    "unaudited management projection", "unaudited estimate", "forward-looking guidance",
    # Engineering / Cybersecurity (unverified user ticket / preliminary speculation)
    "el usuario reporta sin logs", "hipótesis preliminar no verificada", "unverified user report",
)

_PROVEN_JUDICIAL_CUES = (
    # Legal
    "hecho probado", "hechos probados", "declaramos probado", "se declara probado",
    "ha quedado acreditado", "queda acreditado", "consta probado", "fallamos", "sentencia",
    "proven fact", "proven facts", "established fact", "court finds", "hecho incontrovertido",
    # Clinical / Lab
    "confirmado por laboratorio", "analítica confirma", "analitica confirma", "biopsia confirma",
    "hallazgo clínico objetivo", "hallazgo clinico objetivo", "lab confirmed", "biopsy confirmed",
    "clinical finding",
    # Financial / Audit
    "auditado sin salvedades", "certificado por el auditor", "informe de auditoría certifica",
    "audited financial statement", "certified by auditor",
    # Engineering / Telemetry
    "confirmado por telemetría", "verificado en logs", "verified by telemetry",
)

UNVERIFIED_SPEAKER_ROLES = {
    # Legal
    "PARTY_ALLEGATION",
    "UNVERIFIED_ALLEGATION",
    "DEFENSE_CLAIM",
    "PLAINTIFF_ALLEGATION",
    "WITNESS_CLAIM",
    # Clinical / Medical
    "PATIENT_SELF_REPORT",
    "UNVERIFIED_ANAMNESIS",
    "SUBJECTIVE_SYMPTOM",
    # Financial / Corporate
    "MANAGEMENT_PROJECTION",
    "UNAUDITED_ESTIMATE",
    "FORWARD_LOOKING_GUIDANCE",
    # Engineering / Cybersecurity
    "USER_TICKET_REPORT",
    "UNVERIFIED_HYPOTHESIS",
    "ROOT_CAUSE_SPECULATION",
}

_EPISTEMIC_RANKS: Dict[str, int] = {
    "deductive": 100,
    "arithmetic": 95,
    "syntactic": 90,
    "semantic": 85,
    "inductive": 70,
    "abductive": 50,
    "probabilistic": 40,
    "heuristic": 30,
    "narrative": 10,
}


def _rank_to_type(rank: int) -> str:
    if rank <= 10:
        return "narrative"
    if rank <= 30:
        return "heuristic"
    if rank <= 40:
        return "probabilistic"
    if rank <= 50:
        return "abductive"
    if rank <= 70:
        return "inductive"
    return "deductive"


ALL_HEURISTIC_TERMS = _HEURISTIC_TERMS + _EXTRA_HEURISTIC_TERMS
ALL_ABDUCTIVE_TERMS = _ABDUCTIVE_TERMS + _EXTRA_ABDUCTIVE_TERMS


@dataclass
class EpistemicAuditResult:
    claim_id: str
    original_type: str
    audited_type: str
    is_overridden: bool
    override_reason: Optional[str] = None
    missing_premises: List[str] = field(default_factory=list)
    derivation_status: str = "source_supported"


class EpistemicJudge:
    """
    Decoupled Epistemic Judge for formal validation of claim classifications.
    Eliminates reliance on generative LLM self-labeling and enforces formal
    premise verification, allegation attribution detection, and epistemic closure.
    """

    def __init__(self, rule_checkers: Optional[Mapping[str, RuleChecker]] = None) -> None:
        self._rule_checkers = dict(BUILTIN_RULES)
        if rule_checkers:
            self._rule_checkers.update(rule_checkers)

    def _has_premise_cycle(
        self,
        start_id: str,
        premise_ids: List[str],
        premise_lookup: Optional[Dict[str, Claim]],
    ) -> bool:
        """Return True if any path from `premise_ids` loops back to `start_id` or forms a cycle."""
        if not start_id or not premise_ids:
            return False
        if start_id in premise_ids:
            return True
        if not premise_lookup:
            return False

        def _dfs(curr_ids: List[str], path_stack: Set[str]) -> bool:
            for pid in curr_ids:
                if pid in path_stack:
                    return True
                p_claim = premise_lookup.get(pid)
                if not p_claim:
                    continue
                next_p = getattr(p_claim, "premises", []) or []
                if next_p and _dfs(next_p, path_stack | {pid}):
                    return True
            return False

        return _dfs(premise_ids, {start_id})

    def audit_claim(
        self,
        claim: Claim,
        verified_premise_ids: Optional[Set[str]] = None,
        require_declared_premises: bool = False,
        premise_lookup: Optional[Dict[str, Claim]] = None,
    ) -> EpistemicAuditResult:
        """
        Audit a claim's claimed inference_type against its text, attribution, and formal premises.
        """
        orig_type = claim.inference_type.strip().lower()
        claim_quote = getattr(claim, "quote", "") or ""
        claim_val = str(claim.value or "")
        merged_text = f"{claim.predicate} {claim_quote} {claim_val}".lower()

        missing_premises: List[str] = []

        # 1. Adversarial & Attribution Inspection:
        # If claimed as deductive / arithmetic, verify that it contains NO low-reliability,
        # speculative or unratified party allegation language.
        if orig_type in {"deductive", "arithmetic", "syntactic"}:
            if _contains_any(merged_text, ALL_HEURISTIC_TERMS):
                return EpistemicAuditResult(
                    claim_id=claim.id,
                    original_type=orig_type,
                    audited_type="heuristic",
                    is_overridden=True,
                    override_reason="Detected heuristic marker in claim text/value",
                    derivation_status="unverified",
                )
            if _contains_any(merged_text, ALL_ABDUCTIVE_TERMS):
                return EpistemicAuditResult(
                    claim_id=claim.id,
                    original_type=orig_type,
                    audited_type="abductive",
                    is_overridden=True,
                    override_reason="Detected abductive/speculative marker in claim text/value",
                    derivation_status="hypothesis",
                )
            if _contains_any(merged_text, _PROBABILISTIC_TERMS):
                return EpistemicAuditResult(
                    claim_id=claim.id,
                    original_type=orig_type,
                    audited_type="probabilistic",
                    is_overridden=True,
                    override_reason="Detected probabilistic marker in claim text/value",
                    derivation_status="hypothesis",
                )
            if _contains_any(merged_text, _NARRATIVE_TERMS):
                return EpistemicAuditResult(
                    claim_id=claim.id,
                    original_type=orig_type,
                    audited_type="narrative",
                    is_overridden=True,
                    override_reason="Detected narrative marker in claim text/value",
                    derivation_status="unverified",
                )
            # Allegation attribution check: party claim without proven judicial finding
            if _contains_any(merged_text, _ALLEGATION_TERMS) and not _contains_any(merged_text, _PROVEN_JUDICIAL_CUES):
                return EpistemicAuditResult(
                    claim_id=claim.id,
                    original_type=orig_type,
                    audited_type="abductive",
                    is_overridden=True,
                    override_reason="Detected party allegation attribution without judicial confirmation",
                    derivation_status="unverified",
                )
            # Discursive section attribution check via LLM-extracted speaker_role
            speaker_role = (getattr(claim, "speaker_role", None) or "").strip().upper()
            if (
                speaker_role in UNVERIFIED_SPEAKER_ROLES
                and not _contains_any(merged_text, _PROVEN_JUDICIAL_CUES)
            ):
                return EpistemicAuditResult(
                    claim_id=claim.id,
                    original_type=orig_type,
                    audited_type="abductive",
                    is_overridden=True,
                    override_reason=f"Detected unratified party/witness/unverified attribution via speaker_role={speaker_role}",
                    derivation_status="unverified",
                )

        # 2. Formal Premise Verification, Acyclicity & Epistemic Closure:
        declared_premises = getattr(claim, "premises", []) or []
        if declared_premises and self._has_premise_cycle(claim.id, declared_premises, premise_lookup):
            return EpistemicAuditResult(
                claim_id=claim.id,
                original_type=orig_type,
                audited_type="abductive",
                is_overridden=True,
                override_reason="Cyclic justification detected in premise DAG",
                derivation_status="unverified",
            )

        if require_declared_premises and not declared_premises and orig_type == "deductive":
            return EpistemicAuditResult(
                claim_id=claim.id,
                original_type=orig_type,
                audited_type="abductive",
                is_overridden=True,
                override_reason="Deductive inference requires explicit verified premises",
                derivation_status="unverified",
            )

        if declared_premises:
            missing_premises = [
                p for p in declared_premises
                if p not in (verified_premise_ids or set())
                or p not in (premise_lookup or {})
                or premise_lookup[p].id != p
            ]
            if missing_premises:
                return EpistemicAuditResult(
                    claim_id=claim.id,
                    original_type=orig_type,
                    audited_type="abductive",
                    is_overridden=True,
                    override_reason=f"Missing verified premises: {missing_premises}",
                    missing_premises=missing_premises,
                    derivation_status="unverified",
                )

        # 3. Transitive Fixed-Point Epistemic Closure over Premise DAGs:
        #    EpistemicRank(conclusion) <= min_{p in ancestors(conclusion)}(EpistemicRank(p))
        if declared_premises and premise_lookup:
            orig_rank = _EPISTEMIC_RANKS.get(orig_type, 100)
            min_premise_rank, weakest_premise_id, weakest_premise_reason = (
                self._compute_transitive_premise_rank(
                    declared_premises,
                    premise_lookup,
                    visited={claim.id} if getattr(claim, "id", None) else set(),
                    initial_cap=orig_rank,
                )
            )

            if orig_rank > min_premise_rank:
                downgraded_type = _rank_to_type(min_premise_rank)
                reason_detail = (
                    weakest_premise_reason
                    or f"Epistemic closure: conclusion rank ({orig_rank}) exceeds antecedent '{weakest_premise_id}' rank ({min_premise_rank})"
                )
                return EpistemicAuditResult(
                    claim_id=claim.id,
                    original_type=orig_type,
                    audited_type=downgraded_type,
                    is_overridden=True,
                    override_reason=reason_detail,
                    derivation_status="unverified" if downgraded_type in BLOCKED_INFERENCE_TYPES else "hypothesis",
                )

        # A verified ID establishes provenance, not implication. Recheck every
        # ancestor, then validate the conclusion using trusted rule code.
        rule_error = None
        if declared_premises:
            for pid in declared_premises:
                premise_audit = self.audit_claim(
                    premise_lookup[pid],
                    verified_premise_ids=verified_premise_ids,
                    premise_lookup=premise_lookup,
                )
                if premise_audit.derivation_status not in {"source_supported", "rule_derived"}:
                    rule_error = f"Premise '{pid}' has no verified derivation"
                    break
            checker = (
                self._rule_checkers.get(claim.derivation_rule)
                if isinstance(claim.derivation_rule, str) else None
            )
            if not rule_error and checker is None:
                rule_error = "Missing or unknown derivation rule"
            if not rule_error:
                try:
                    valid = checker(claim, tuple(premise_lookup[p] for p in declared_premises))
                except Exception:
                    valid = False
                if valid is not True:
                    rule_error = "Derivation rule does not justify the conclusion"
        elif claim.derivation_rule:
            rule_error = "Derivation rule requires explicit verified premises"

        if rule_error:
            return EpistemicAuditResult(
                claim_id=claim.id, original_type=orig_type, audited_type="abductive",
                is_overridden=True, override_reason=rule_error,
                derivation_status="unverified",
            )

        if orig_type in BLOCKED_INFERENCE_TYPES:
            status = "unverified"
        elif orig_type in {"inductive", "probabilistic", "common_sense", "causal", "multi_hop"}:
            status = "hypothesis"
        elif declared_premises:
            status = "rule_derived"
        else:
            status = "source_supported"

        return EpistemicAuditResult(
            claim_id=claim.id,
            original_type=orig_type,
            audited_type=orig_type,
            is_overridden=False,
            derivation_status=status,
        )

    def _compute_transitive_premise_rank(
        self,
        premise_ids: List[str],
        premise_lookup: Dict[str, Claim],
        visited: Set[str],
        initial_cap: int = 100,
    ) -> Tuple[int, Optional[str], Optional[str]]:
        """
        Recursively traverse the premise DAG to compute the minimum epistemic rank
        across all direct and transitive ancestors, preventing cycle-induced loops
        and ensuring order-independent fixed-point propagation.
        """
        min_rank = initial_cap
        weakest_id: Optional[str] = None
        weakest_reason: Optional[str] = None

        for p_id in premise_ids:
            if p_id in visited:
                continue
            p_claim = premise_lookup.get(p_id)
            if not p_claim:
                continue
            p_type = getattr(p_claim, "inference_type", "deductive").strip().lower()
            p_rank = _EPISTEMIC_RANKS.get(p_type, 50)
            p_text = (
                f"{getattr(p_claim, 'predicate', '')} "
                f"{getattr(p_claim, 'quote', '')} "
                f"{getattr(p_claim, 'value', '')}"
            ).lower()
            p_role = (getattr(p_claim, "speaker_role", None) or "").strip().upper()
            local_reason: Optional[str] = None

            # Inspect premise text for heuristic/abductive/probabilistic/narrative/allegation cues
            if _contains_any(p_text, _NARRATIVE_TERMS) and p_rank > _EPISTEMIC_RANKS["narrative"]:
                p_rank = _EPISTEMIC_RANKS["narrative"]
                local_reason = f"Premise '{p_id}' carries narrative marker"
            elif _contains_any(p_text, ALL_HEURISTIC_TERMS) and p_rank > _EPISTEMIC_RANKS["heuristic"]:
                p_rank = _EPISTEMIC_RANKS["heuristic"]
                local_reason = f"Premise '{p_id}' carries heuristic marker"
            elif _contains_any(p_text, _PROBABILISTIC_TERMS) and p_rank > _EPISTEMIC_RANKS["probabilistic"]:
                p_rank = _EPISTEMIC_RANKS["probabilistic"]
                local_reason = f"Premise '{p_id}' carries probabilistic marker"
            elif (
                _contains_any(p_text, ALL_ABDUCTIVE_TERMS)
                or _contains_any(p_text, _ALLEGATION_TERMS)
                or p_role in UNVERIFIED_SPEAKER_ROLES
            ) and not _contains_any(p_text, _PROVEN_JUDICIAL_CUES):
                if p_rank > _EPISTEMIC_RANKS["abductive"]:
                    p_rank = _EPISTEMIC_RANKS["abductive"]
                    local_reason = f"Premise '{p_id}' carries party allegation attribution"

            if p_rank < min_rank:
                min_rank = p_rank
                weakest_id = p_id
                weakest_reason = local_reason

            # Recurse into ancestors of p_claim
            anc_premises = getattr(p_claim, "premises", []) or []
            if anc_premises:
                anc_rank, anc_id, anc_reason = self._compute_transitive_premise_rank(
                    anc_premises,
                    premise_lookup,
                    visited=visited | {p_id},
                    initial_cap=min_rank,
                )
                if anc_rank < min_rank:
                    min_rank = anc_rank
                    weakest_id = anc_id or p_id
                    weakest_reason = anc_reason

        return min_rank, weakest_id, weakest_reason

    def audit_and_sanitize_claims(
        self,
        claims: List[Claim],
        verified_premise_ids: Optional[Set[str]] = None,
        require_declared_premises: bool = False,
        premise_lookup: Optional[Dict[str, Claim]] = None,
    ) -> Tuple[List[Claim], List[Dict[str, Any]]]:
        """
        Audit all claims in place and return (sanitized_claims, audit_trace).
        """
        trace: List[Dict[str, Any]] = []
        sanitized: List[Claim] = []

        # Merge local claims into premise lookup if not explicitly supplied
        effective_lookup: Dict[str, Claim] = {}
        if premise_lookup:
            effective_lookup.update(premise_lookup)
        for c in claims:
            if c.id and c.id not in effective_lookup:
                effective_lookup[c.id] = c

        # Evaluate the same snapshot for every claim before applying overrides.
        audits = [
            self.audit_claim(
                c,
                verified_premise_ids=verified_premise_ids,
                require_declared_premises=require_declared_premises,
                premise_lookup=effective_lookup,
            ) for c in claims
        ]
        for c, audit in zip(claims, audits):
            if audit.is_overridden:
                c.inference_type = audit.audited_type
                trace.append({
                    "claim_id": audit.claim_id,
                    "action": "override_inference_type",
                    "original": audit.original_type,
                    "audited": audit.audited_type,
                    "reason": audit.override_reason,
                    "derivation_status": audit.derivation_status,
                })
            sanitized.append(c)

        return sanitized, trace

    def validate_resolution(
        self,
        result: Result,
        inference_profile: Optional[InferenceProfile] = None,
        verified_premise_ids: Optional[Set[str]] = None,
        premise_lookup: Optional[Dict[str, Claim]] = None,
    ) -> Result:
        """
        Post-resolution epistemic gate. Audits supporting claims and blocks
        decision emission if supporting evidence is exclusively composed of
        blocked or downgraded inference types.
        """
        supporting = result.supporting_claims or []
        if not supporting:
            return result

        # Re-audit supporting claims with effective premise lookup
        effective_lookup: Dict[str, Claim] = {}
        if premise_lookup:
            effective_lookup.update(premise_lookup)
        for c in (result.supporting_claims or []) + (result.contradictions or []):
            if c.id and c.id not in effective_lookup:
                effective_lookup[c.id] = c

        self.audit_and_sanitize_claims(
            supporting,
            verified_premise_ids=verified_premise_ids,
            premise_lookup=effective_lookup,
        )

        def _is_blocked(inference_type: str) -> bool:
            if inference_profile is not None:
                return inference_profile.is_blocked(inference_type)
            return inference_type in BLOCKED_INFERENCE_TYPES

        if all(_is_blocked(c.inference_type) for c in supporting):
            return Result(
                value=None,
                confidence=0.0,
                contradictions=result.contradictions,
                supporting_claims=supporting,
                reason=Reason.BLOCKED_INFERENCE,
            )

        return result
