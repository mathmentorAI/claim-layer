from __future__ import annotations

from typing import Dict, Optional, Set

from core.interfaces import Claim, InferenceProfile, Result
from core.epistemic_judge import EpistemicJudge


def apply_grounding_protocol(
    result: Result,
    inference_profile: Optional[InferenceProfile] = None,
    verified_premise_ids: Optional[Set[str]] = None,
    premise_lookup: Optional[Dict[str, Claim]] = None,
) -> Result:
    """
    Apply post-resolution grounding protocol gates.

    Grounding Protocol (v2): Audits supporting claims against heuristic/speculative cue words
    and verifies formal premises via the decoupled EpistemicJudge, preventing adversarial
    self-labeling bypasses. Blocks emission when the winning support set is exclusively
    composed of blocked or downgraded inference types.

    If an InferenceProfile is provided (from a tenant's protocol), its blocked_types
    override the global BLOCKED_INFERENCE_TYPES defaults.
    """
    judge = EpistemicJudge()
    return judge.validate_resolution(
        result,
        inference_profile=inference_profile,
        verified_premise_ids=verified_premise_ids,
        premise_lookup=premise_lookup,
    )
