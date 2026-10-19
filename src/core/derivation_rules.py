"""Small, explicit proof boundary. Rules are trusted application code.

The built-in identity rule only restates one proposition without changing its
scope or attribution. Domain-specific implications require an explicit checker;
an LLM label or a list of premise IDs is not a proof.
"""
from typing import Callable, Dict, Sequence

from core.interfaces import Claim

RuleChecker = Callable[[Claim, Sequence[Claim]], bool]


def check_identity(conclusion: Claim, premises: Sequence[Claim]) -> bool:
    if len(premises) != 1:
        return False
    premise = premises[0]
    fields = (
        "entity", "predicate", "value", "canonical_entity", "canonical_predicate",
        "canonical_value", "valid_from", "valid_until", "speaker_role", "unit",
        "concept_fingerprint", "origin_tier",
    )
    # Type-sensitive comparison prevents True and 1 from proving each other.
    return all(
        type(getattr(conclusion, key)) is type(getattr(premise, key))
        and getattr(conclusion, key) == getattr(premise, key)
        for key in fields
    )


BUILTIN_RULES: Dict[str, RuleChecker] = {"identity": check_identity}
