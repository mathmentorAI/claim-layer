from __future__ import annotations
import re
from typing import Optional

from core.claim_adapter import ClaimAdapter
from core.claim_extractor import ClaimExtractor
from core.claim_layer_adapter import ClaimLayerAdapter
from core.document_parser import DocumentParser, ParsedChunk
from core.hybrid_extraction import gate_extracted_claim
from core.interfaces import ExtractionConfig


class IngestionPipeline:
    """
    Orchestrates the full document → truth flow:

      Source document
        → DocumentParser    (remote parsing / OCR / chunk normalization)
        → ClaimExtractor    (text → ExtractedClaim list, per page or chunk)
        → stamp page_number + paragraph_id onto each ExtractedClaim
        → ClaimAdapter      (all claims → single IngestedDocument)
        → ClaimLayerAdapter (IngestedDocument → claim-layer store, once)

    One document = one ingestion call. No per-page ingestion.
    No logic lives here. Each stage is fully replaceable.
    """

    def __init__(
        self,
        parser: DocumentParser,
        extractor: ClaimExtractor,
        claim_adapter: ClaimAdapter,
        claim_layer_adapter: ClaimLayerAdapter,
    ) -> None:
        self.parser = parser
        self.extractor = extractor
        self.claim_adapter = claim_adapter
        self.claim_layer_adapter = claim_layer_adapter

    def _recover_quote(self, claim, text: str) -> str:
        candidate = (claim.quote or "").strip()
        if candidate:
            return candidate

        cleaned = text.strip()
        if not cleaned:
            return ""

        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[\.\!\?\:])\s+|\n+", cleaned)
            if sentence.strip()
        ]
        if not sentences:
            return cleaned[:400]

        entity_tokens = set(re.findall(r"[a-z0-9\+]+", str(claim.entity).lower()))
        predicate_tokens = set(re.findall(r"[a-z0-9\+]+", str(claim.predicate).lower()))
        value_tokens = set(re.findall(r"[a-z0-9\+]+", str(claim.value).lower()))

        def score(sentence: str) -> tuple[int, int, int, int]:
            lowered = sentence.lower()
            sentence_tokens = set(re.findall(r"[a-z0-9\+]+", lowered))
            entity_hits = len(sentence_tokens & entity_tokens)
            value_hits = len(sentence_tokens & value_tokens)
            predicate_hits = len(sentence_tokens & predicate_tokens)
            exact_hits = int(str(claim.value).lower() in lowered) + int(str(claim.entity).lower() in lowered)
            return (exact_hits, value_hits, entity_hits + predicate_hits, len(sentence))

        best = max(sentences, key=score)
        return best[:500]

    def ingest_pdf(self, file_path: str, document_id: str, extraction_config: Optional[ExtractionConfig] = None) -> None:
        parsed_doc = self.parser.parse_pdf(file_path)
        self.ingest_parsed_document(parsed_doc, document_id=document_id, extraction_config=extraction_config)

    def ingest_parsed_document(
        self,
        parsed_doc,
        document_id: str,
        extraction_config: Optional[ExtractionConfig] = None,
    ) -> None:
        all_extracted = []
        all_segments = []

        for page in parsed_doc.pages:
            units = page.chunks if getattr(page, "chunks", None) else [ParsedChunk(chunk_id=f"p{page.page_number}", text=page.text, page_number=page.page_number)]
            for chunk in units:
                if not chunk.text.strip():
                    continue
                
                # Persistence: keep the segment for hybrid retrieval
                all_segments.append({
                    "segment_id": chunk.chunk_id,
                    "text": chunk.text,
                    "page_number": chunk.page_number or page.page_number,
                    "start_offset": getattr(chunk, "start_offset", None),
                    "end_offset": getattr(chunk, "end_offset", None),
                    "section_title": getattr(chunk, "section_title", None),
                })

                # Extraction: text -> claims
                extracted = self.extractor.extract(chunk.text, extraction_config)
                for claim in extracted:
                    claim.quote = self._recover_quote(claim, chunk.text)
                    claim.page_number = chunk.page_number or page.page_number
                    claim.paragraph_id = claim.paragraph_id or chunk.chunk_id

                    # Hybrid gate: typed claims (polarity set) are validated
                    # against the chunk they came from — hallucinated quotes
                    # and malformed windows are dropped, polarity folds into
                    # the value, and inference_type is clamped by lexical
                    # cues. Legacy claims (polarity=None) pass through.
                    gated = gate_extracted_claim(claim, chunk.text)
                    if gated is not None:
                        all_extracted.append(gated)

        # If no claims were extracted, skip ingestion entirely.
        # This preserves the contract expected by pipeline tests.
        if not all_extracted:
            return

        payload = self.claim_adapter.to_ingested_document(
            all_extracted,
            document_id=document_id,
            project_id=self.claim_layer_adapter.project_id,
            extraction_config=extraction_config,
        )
        
        # Attach segments to the payload before ingestion
        if isinstance(payload, dict):
            payload["segments"] = all_segments
        else:
            payload.segments = all_segments

        self.claim_layer_adapter.ingest_document(payload)
