from __future__ import annotations

import json
import mimetypes
import uuid
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from typing import Any, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from core.interfaces import ExtractionConfig


class DocumentParsingError(RuntimeError):
    """Raised when a document cannot be parsed by the configured parser service."""


def _normalize_endpoint(endpoint: str) -> str:
    base = endpoint.strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DocumentParsingError("Parser endpoint must be a valid http(s) URL.")
    return base


def _read_http_error_body(exc: HTTPError) -> str:
    return exc.read().decode("utf-8", errors="ignore") if hasattr(exc, "read") else ""


def _looks_like_openai_runtime(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("data"), list)
        and all(isinstance(item, dict) for item in payload.get("data", []))
    )


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def get_text(self) -> str:
        return "\n".join(self.parts)


def _encode_multipart_form_data(
    fields: list[tuple[str, str]],
    files: list[tuple[str, str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = f"----DeltoryxBoundary{uuid.uuid4().hex}"
    body = bytearray()

    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    for field_name, filename, content, content_type in files:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8")
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(content)
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), boundary


@dataclass
class ParsedPage:
    page_number: int   # 1-based
    text: str
    chunks: List["ParsedChunk"] = field(default_factory=list)


@dataclass
class ParsedChunk:
    chunk_id: str
    text: str
    page_number: Optional[int] = None
    start_offset: Optional[int] = None
    end_offset: Optional[int] = None
    section_title: Optional[str] = None
    bbox: Any = None


@dataclass
class ParsedDocument:
    document_id: str = ""
    filename: str = ""
    pages: List[ParsedPage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentParser:
    def parse_document(
        self,
        file_path: str,
        filename: str,
        document_id: str,
        extraction_config: ExtractionConfig,
    ) -> ParsedDocument:
        endpoint = str(extraction_config.endpoint or "").strip()
        if not endpoint:
            raise DocumentParsingError("Extraction config is missing a parser endpoint.")

        normalized_endpoint = _normalize_endpoint(endpoint)
        file_bytes = Path(file_path).read_bytes()
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        options = {
            "ocr": True,
            "chunking": True,
            "include_layout": True,
            "include_tables": True,
        }
        body, boundary = _encode_multipart_form_data(
            fields=[
                ("document_id", document_id),
                ("options", json.dumps(options, separators=(",", ":"))),
            ],
            files=[("file", filename, file_bytes, content_type)],
        )

        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        }
        if extraction_config.api_key:
            headers["Authorization"] = f"Bearer {extraction_config.api_key}"

        request = Request(
            f"{normalized_endpoint}/parse-document",
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(request, timeout=120) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = _read_http_error_body(exc)
            if self._should_use_local_adapter(
                normalized_endpoint,
                exc.code,
                detail,
                extraction_config.api_key,
            ):
                return self._parse_locally(
                    file_path,
                    filename=filename,
                    document_id=document_id,
                    parser_name="local-adapter:openai-runtime",
                )
            raise DocumentParsingError(
                f"Parser endpoint returned HTTP {exc.code}{f': {detail}' if detail else ''}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise DocumentParsingError(f"Parser endpoint request failed: {exc}") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DocumentParsingError(f"Parser returned invalid JSON: {exc}") from exc

        return self._validate_parsed_document(payload, document_id=document_id, filename=filename)

    def _validate_parsed_document(
        self,
        payload: Any,
        document_id: str,
        filename: str,
    ) -> ParsedDocument:
        if not isinstance(payload, dict):
            raise DocumentParsingError("Parser response must be a JSON object.")

        raw_pages = payload.get("pages")
        if not isinstance(raw_pages, list):
            raise DocumentParsingError("Parser response must include a 'pages' array.")

        pages: List[ParsedPage] = []
        for index, item in enumerate(raw_pages, start=1):
            if not isinstance(item, dict):
                raise DocumentParsingError("Each page in parser response must be an object.")

            page_number = item.get("page_number", index)
            try:
                page_number = int(page_number)
            except (TypeError, ValueError) as exc:
                raise DocumentParsingError("Each page must include a numeric page_number.") from exc

            page_text = str(item.get("text") or "").strip()

            raw_chunks = item.get("chunks")
            chunks: List[ParsedChunk] = []
            if raw_chunks is not None:
                if not isinstance(raw_chunks, list):
                    raise DocumentParsingError("Page field 'chunks' must be a list when provided.")
                for chunk_index, raw_chunk in enumerate(raw_chunks, start=1):
                    if not isinstance(raw_chunk, dict):
                        raise DocumentParsingError("Each chunk in parser response must be an object.")
                    chunk_text = str(raw_chunk.get("text") or "").strip()
                    if not chunk_text:
                        continue
                    chunk_id = str(raw_chunk.get("chunk_id") or f"p{page_number}-c{chunk_index}")
                    raw_chunk_page = raw_chunk.get("page_number")
                    chunk_page = page_number if raw_chunk_page is None else int(raw_chunk_page)
                    chunks.append(
                        ParsedChunk(
                            chunk_id=chunk_id,
                            text=chunk_text,
                            page_number=chunk_page,
                            start_offset=raw_chunk.get("start_offset"),
                            end_offset=raw_chunk.get("end_offset"),
                            section_title=raw_chunk.get("section_title"),
                            bbox=raw_chunk.get("bbox"),
                        )
                    )

            if page_text or chunks:
                pages.append(
                    ParsedPage(
                        page_number=page_number,
                        text=page_text,
                        chunks=chunks,
                    )
                )

        metadata = payload.get("metadata")
        if metadata is None:
            metadata = {}
        if not isinstance(metadata, dict):
            raise DocumentParsingError("Parser response field 'metadata' must be an object.")

        return ParsedDocument(
            document_id=str(payload.get("document_id") or document_id),
            filename=str(payload.get("filename") or filename),
            pages=pages,
            metadata=metadata,
        )

    def _should_use_local_adapter(
        self,
        endpoint: str,
        status_code: int,
        error_detail: str,
        api_key: str | None,
    ) -> bool:
        if status_code not in {404, 405, 415}:
            return False
        lowered = error_detail.lower()
        if "application/json" not in lowered and "unsupported media type" not in lowered and status_code == 415:
            return False
        return self._is_openai_compatible_runtime(endpoint, api_key)

    def _is_openai_compatible_runtime(self, endpoint: str, api_key: str | None) -> bool:
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        for path in ("/v1/models", "/api/v1/models"):
            request = Request(f"{endpoint}{path}", headers=headers, method="GET")
            try:
                with urlopen(request, timeout=4) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except Exception:
                continue
            if _looks_like_openai_runtime(payload):
                return True
        return False

    def _parse_locally(
        self,
        file_path: str,
        *,
        filename: str,
        document_id: str,
        parser_name: str,
    ) -> ParsedDocument:
        suffix = Path(filename).suffix.lower()
        if suffix == ".pdf":
            parsed = self.parse_pdf(file_path)
            parsed.document_id = document_id
            parsed.filename = filename
            parsed.metadata = {
                "page_count": len(parsed.pages),
                "ocr_used": False,
                "parser": parser_name,
            }
            return parsed

        if suffix == ".docx":
            text = self._parse_docx_text(file_path)
        elif suffix in {".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml"}:
            text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        elif suffix in {".html", ".htm"}:
            text = self._parse_html_text(file_path)
        else:
            raise DocumentParsingError(
                f"Configured endpoint is an OpenAI-compatible runtime, but '{suffix or 'unknown'}' is not supported by the built-in document adapter."
            )

        normalized = self._normalize_text(text)
        pages = [ParsedPage(page_number=1, text=normalized)] if normalized else []
        return ParsedDocument(
            document_id=document_id,
            filename=filename,
            pages=pages,
            metadata={
                "page_count": len(pages),
                "ocr_used": False,
                "parser": parser_name,
            },
        )

    def _parse_docx_text(self, file_path: str) -> str:
        try:
            with ZipFile(file_path) as archive:
                raw = archive.read("word/document.xml")
        except KeyError as exc:
            raise DocumentParsingError("DOCX document is missing word/document.xml.") from exc
        except Exception as exc:
            raise DocumentParsingError(f"Failed to parse DOCX document: {exc}") from exc

        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise DocumentParsingError(f"Failed to parse DOCX XML: {exc}") from exc

        paragraphs: list[str] = []
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        for paragraph in root.findall(".//w:p", ns):
            runs = [node.text or "" for node in paragraph.findall(".//w:t", ns)]
            text = "".join(runs).strip()
            if text:
                paragraphs.append(text)
        return "\n\n".join(paragraphs)

    def _parse_html_text(self, file_path: str) -> str:
        raw = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        parser = _HTMLTextExtractor()
        parser.feed(raw)
        return parser.get_text()

    def _normalize_text(self, text: str) -> str:
        lines = [line.strip() for line in text.splitlines()]
        blocks: list[str] = []
        current: list[str] = []
        for line in lines:
            if not line:
                if current:
                    blocks.append(" ".join(current))
                    current = []
                continue
            current.append(line)
        if current:
            blocks.append(" ".join(current))
        return "\n\n".join(blocks).strip()

    def parse_pdf(self, file_path: str) -> ParsedDocument:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        pages: List[ParsedPage] = []

        for i, page in enumerate(reader.pages):
            try:
                text = page.extract_text(extraction_mode="layout") or ""
            except TypeError:
                # pypdf < 4.0 does not support extraction_mode
                text = page.extract_text() or ""
            if text.strip():
                pages.append(ParsedPage(page_number=i + 1, text=text))

        return ParsedDocument(filename=Path(file_path).name, pages=pages)
