"""ClaimLayer v3: Deterministic computable verification for AI agent outputs."""

from claimlayer.ledger import Ledger
from claimlayer.mcp_server import MCPVerificationServer
from claimlayer.models import (
    Assertion,
    ConflictDiff,
    FactRecord,
    Issue,
    Policy,
    ResolutionRecord,
    Source,
    Verdict,
    VerificationReceipt,
)
from claimlayer.receipt import RECEIPT_SCHEME, verify_receipt
from claimlayer.verifiers.diff import (
    SectionDivergence,
    build_comparison_policy,
    extract_divergent_sections,
)
from claimlayer.verify import verify

__version__ = "3.0.0"

__all__ = [
    "Assertion",
    "ConflictDiff",
    "FactRecord",
    "Issue",
    "Ledger",
    "MCPVerificationServer",
    "Policy",
    "RECEIPT_SCHEME",
    "ResolutionRecord",
    "SectionDivergence",
    "Source",
    "Verdict",
    "VerificationReceipt",
    "__version__",
    "build_comparison_policy",
    "extract_divergent_sections",
    "verify",
    "verify_receipt",
]
