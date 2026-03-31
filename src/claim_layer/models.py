from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IngestedSource:
    page: int | None = None
    paragraph_id: str | None = None
    text: str = ""


@dataclass
class IngestedEntity:
    entity_id: str
    name: str
    entity_type: str = "custom"


@dataclass
class IngestedClaim:
    claim_id: str
    text: str
    confidence: float = 0.0
    page: int | None = None
    paragraph_id: str | None = None
    embedding: list[float] | None = None


@dataclass
class IngestedFact:
    claim_ref: str
    entity_ref: str
    fact_type: str
    value: str
    verified: str = "pending"
    sources: list[IngestedSource] = field(default_factory=list)


@dataclass
class IngestedDocument:
    project_id: str
    filename: str
    entities: list[IngestedEntity | dict[str, Any]] = field(default_factory=list)
    claims: list[IngestedClaim | dict[str, Any]] = field(default_factory=list)
    facts: list[IngestedFact | dict[str, Any]] = field(default_factory=list)
    file_hash: str = ""
    pipeline_version: str = "0.1.0"
