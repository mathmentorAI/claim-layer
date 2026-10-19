from typing import List

from .inference_engine import resolve_claims
from .interfaces import Claim, Query, Reason, Result


class InMemoryClaimLayer:
    def __init__(self):
        self.claims: List[Claim] = []

    def ingest(self, claims: List[Claim]) -> None:
        self.claims.extend(claims)

    def get_by_entity(self, entity: str) -> List[Claim]:
        return [c for c in self.claims if c.entity == entity]

    def get_all(self) -> List[Claim]:
        return list(self.claims)

    def query(self, query: Query) -> List[Claim]:
        return [
            c for c in self.claims
            if c.entity == query.entity and c.predicate == query.predicate
        ]

    def resolve(self, claims: List[Claim]) -> Result:
        # Delegates to the unified inference engine: value-group election by
        # weighted noisy-OR support, source dedup, temporal validity, and a
        # contradiction penalty proportional to the losing groups' support.
        return resolve_claims(claims)
