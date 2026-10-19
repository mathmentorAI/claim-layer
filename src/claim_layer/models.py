from __future__ import annotations
from typing import Optional

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IngestedSource:
    page: Optional[int] = None
    paragraph_id: Optional[str] = None
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
    page: Optional[int] = None
    paragraph_id: Optional[str] = None
    embedding: list[float] | None = None


@dataclass
class IngestedFact:
    claim_ref: str
    entity_ref: str
    fact_type: str
    value: str
    verified: str = "pending"
    sources: list[IngestedSource] = field(default_factory=list)
    # Temporal validity window (ISO-8601 strings). None = always valid.
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    # Inference type proposed by a typed extractor and clamped by the hybrid
    # gate. None = not typed at extraction; consumers classify lexically.
    inference_type: Optional[str] = None


@dataclass
class IngestedSegment:
    segment_id: str
    text: str
    page_number: Optional[int] = None
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    section_title: Optional[str] = None
    embedding: list[float] | None = None


@dataclass
class IngestedDocument:
    project_id: str
    filename: str
    entities: list[IngestedEntity | dict[str, Any]] = field(default_factory=list)
    claims: list[IngestedClaim | dict[str, Any]] = field(default_factory=list)
    facts: list[IngestedFact | dict[str, Any]] = field(default_factory=list)
    segments: list[IngestedSegment | dict[str, Any]] = field(default_factory=list)
    file_hash: str = ""
    pipeline_version: str = "0.1.0"
    extraction_config: Optional[dict[str, Any]] = None
