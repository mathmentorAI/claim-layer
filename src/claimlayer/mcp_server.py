"""Zero-dependency Model Context Protocol (MCP) server for ClaimLayer agent verification."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claimlayer.ledger import Ledger
from claimlayer.models import FactRecord, Source

JSONRPC_VERSION = "2.0"
LATEST_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = (
    LATEST_PROTOCOL_VERSION,
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)

JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "register_source",
        "title": "Register Verification Source",
        "description": (
            "Register a source document in the ClaimLayer verification ledger with its "
            "authority tier ('authoritative', 'standard', 'draft'), optional validity dates, "
            "supersedes list, and optional structured facts."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["id", "text"],
            "properties": {
                "id": {"type": "string", "description": "Unique source identifier"},
                "text": {"type": "string", "description": "Full verbatim source text"},
                "tier": {
                    "type": "string",
                    "enum": ["authoritative", "standard", "draft"],
                    "default": "standard",
                },
                "title": {"type": "string"},
                "valid_from": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "valid_until": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "supersedes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "IDs of earlier documents superseded by this source",
                },
                "facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["subject", "predicate", "value"],
                        "properties": {
                            "subject": {"type": "string"},
                            "predicate": {"type": "string"},
                            "value": {"type": "string"},
                            "quote": {"type": "string"},
                            "unit": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "verify_proposal",
        "title": "Verify Agent Proposal",
        "description": (
            "Deterministically verify structured agent assertions before execution or delivery. "
            "Returns status='PASS' (auto-approved with Merkle receipt; proceed immediately), "
            "'RETRY' (fixable grounding/precedence error; self-correct without waking a human), "
            "or 'ESCALATE' (genuine conflict or threshold gate queued for 15s human triage)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["assertions"],
            "properties": {
                "agent_id": {"type": "string", "default": "mcp_agent"},
                "as_of": {"type": "string", "description": "ISO evaluation date YYYY-MM-DD"},
                "assertions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["subject", "predicate", "value", "source_id", "quote"],
                        "properties": {
                            "id": {"type": "string"},
                            "subject": {"type": "string"},
                            "predicate": {"type": "string"},
                            "value": {"type": "string"},
                            "unit": {"type": "string"},
                            "source_id": {"type": "string"},
                            "quote": {"type": "string"},
                            "confidence": {"type": "number", "default": 1.0},
                        },
                    },
                },
                "policy": {
                    "type": "object",
                    "properties": {
                        "policy_id": {"type": "string"},
                        "min_tier_rank": {"type": "integer"},
                        "min_support": {"type": "number"},
                        "block_superseded": {"type": "boolean"},
                        "block_expired": {"type": "boolean"},
                        "required_predicates": {"type": "array", "items": {"type": "string"}},
                        "required_source_ids": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    },
    {
        "name": "check_escalation",
        "title": "Check Human Escalation Status",
        "description": "Poll whether a human reviewer has resolved an escalated verdict.",
        "inputSchema": {
            "type": "object",
            "required": ["verdict_id"],
            "properties": {
                "verdict_id": {"type": "string"},
            },
        },
    },
]


class MCPError(Exception):
    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass
class MCPSession:
    session_id: str | None = None
    protocol_version: str = LATEST_PROTOCOL_VERSION
    initialize_sent: bool = False
    initialized: bool = False
    client_info: dict[str, Any] = field(default_factory=dict)


class MCPVerificationServer:
    """MCP JSON-RPC 2.0 handler backed directly by a ClaimLayer Ledger."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "register_source":
            raw_facts = arguments.get("facts") or []
            src = Source(
                id=str(arguments["id"]),
                text=str(arguments["text"]),
                tier=str(arguments.get("tier") or "standard"),
                title=arguments.get("title"),
                valid_from=arguments.get("valid_from"),
                valid_until=arguments.get("valid_until"),
                supersedes=list(arguments.get("supersedes") or []),
            )
            self.ledger.add_source(src)
            for rf in raw_facts:
                self.ledger.add_fact(
                    FactRecord(
                        subject=str(rf["subject"]),
                        predicate=str(rf["predicate"]),
                        value=str(rf["value"]),
                        source_id=src.id,
                        quote=str(rf.get("quote") or ""),
                        unit=rf.get("unit"),
                        confidence=float(rf.get("confidence", 1.0)),
                    )
                )
            return {
                "registered": True,
                "source_id": src.id,
                "sha256": src.sha256,
                "authority_rank": src.rank,
                "facts_registered": len(raw_facts),
            }

        if name == "verify_proposal":
            verdict = self.ledger.verify(
                assertions=arguments.get("assertions") or [],
                policy=arguments.get("policy"),
                as_of=arguments.get("as_of"),
                agent_id=str(arguments.get("agent_id") or "mcp_agent"),
                record=True,
            )
            return verdict.to_dict()

        if name == "check_escalation":
            vid = str(arguments.get("verdict_id") or "")
            entry = self.ledger.get_verdict_entry(vid)
            if entry is None:
                return {"found": False, "verdict_id": vid}
            return {
                "found": True,
                "verdict_id": vid,
                "status": entry["status"],
                "triage_state": entry["triage_state"],
                "resolution": entry["resolution"],
                "resolved_at": entry["resolved_at"],
            }

        raise MCPError(JSONRPC_INVALID_PARAMS, f"Unknown tool: {name}")

    def handle_message(
        self, message: Any, session: MCPSession, *, stateless_http: bool = False
    ) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != JSONRPC_VERSION:
            raise MCPError(JSONRPC_INVALID_REQUEST, "Invalid JSON-RPC 2.0 message")

        if "method" not in message and ("result" in message or "error" in message):
            return None

        method = message.get("method")
        if not isinstance(method, str) or not method:
            raise MCPError(JSONRPC_INVALID_REQUEST, "Method is required")

        # Notification
        if "id" not in message:
            if method == "notifications/initialized":
                session.initialized = True
            return None

        req_id = message["id"]
        params = message.get("params") or {}

        if method == "initialize":
            req_ver = str(params.get("protocolVersion") or LATEST_PROTOCOL_VERSION)
            negotiated = (
                req_ver if req_ver in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
            )
            session.protocol_version = negotiated
            session.initialize_sent = True
            session.initialized = stateless_http
            return {
                "jsonrpc": JSONRPC_VERSION,
                "id": req_id,
                "result": {
                    "protocolVersion": negotiated,
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "claimlayer-mcp",
                        "version": "3.0.0",
                        "title": "ClaimLayer Computable Verification Server",
                    },
                    "instructions": (
                        "Call verify_proposal before completing tasks or executing actions. "
                        "On PASS, proceed immediately without human wait. On RETRY, fix the "
                        "reported issues and re-verify. On ESCALATE, pause only on the contested item."
                    ),
                },
            }

        if method == "ping":
            return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": {}}

        if not stateless_http and not session.initialize_sent:
            raise MCPError(JSONRPC_INVALID_REQUEST, "Server session is not initialized")

        if method == "tools/list":
            return {"jsonrpc": JSONRPC_VERSION, "id": req_id, "result": {"tools": MCP_TOOLS}}

        if method == "tools/call":
            if not isinstance(params, dict):
                raise MCPError(JSONRPC_INVALID_PARAMS, "tools/call params must be an object")
            tool_name = str(params.get("name") or "")
            tool_args = params.get("arguments") or {}
            if not tool_name:
                raise MCPError(JSONRPC_INVALID_PARAMS, "Tool name is required")
            try:
                output = self.execute_tool(tool_name, tool_args)
                return {
                    "jsonrpc": JSONRPC_VERSION,
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": json.dumps(output, sort_keys=True)}
                        ],
                        "structuredContent": output,
                        "isError": False,
                    },
                }
            except MCPError:
                raise
            except Exception as exc:
                return {
                    "jsonrpc": JSONRPC_VERSION,
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Tool execution error: {exc}"}],
                        "isError": True,
                    },
                }

        raise MCPError(JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}")

    def handle_envelope(
        self, payload: Any, session: MCPSession, *, stateless_http: bool = False
    ) -> list[dict[str, Any]]:
        requests = payload if isinstance(payload, list) else [payload]
        if not requests:
            raise MCPError(JSONRPC_INVALID_REQUEST, "Empty JSON-RPC batch")

        responses: list[dict[str, Any]] = []
        for req in requests:
            try:
                resp = self.handle_message(req, session, stateless_http=stateless_http)
            except MCPError as exc:
                req_id = req.get("id") if isinstance(req, dict) else None
                resp = {
                    "jsonrpc": JSONRPC_VERSION,
                    "id": req_id,
                    "error": {"code": exc.code, "message": exc.message},
                }
            except Exception as exc:
                req_id = req.get("id") if isinstance(req, dict) else None
                resp = {
                    "jsonrpc": JSONRPC_VERSION,
                    "id": req_id,
                    "error": {"code": JSONRPC_INTERNAL_ERROR, "message": str(exc)},
                }
            if resp is not None:
                responses.append(resp)
        return responses


def run_stdio_server(db_path: str | Path | None = None) -> int:
    """Run the ClaimLayer MCP server over standard input/output."""
    ledger = Ledger(db_path=db_path)
    server = MCPVerificationServer(ledger)
    session = MCPSession()

    for raw_line in sys.stdin.buffer:
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line.decode("utf-8"))
            responses = server.handle_envelope(payload, session)
            if not responses:
                continue
            out = responses if isinstance(payload, list) else responses[0]
            encoded = json.dumps(out, separators=(",", ":")).encode("utf-8")
        except Exception as exc:
            encoded = json.dumps(
                {
                    "jsonrpc": JSONRPC_VERSION,
                    "id": None,
                    "error": {"code": JSONRPC_PARSE_ERROR, "message": str(exc)},
                },
                separators=(",", ":"),
            ).encode("utf-8")
        sys.stdout.buffer.write(encoded + b"\n")
        sys.stdout.buffer.flush()
    return 0
