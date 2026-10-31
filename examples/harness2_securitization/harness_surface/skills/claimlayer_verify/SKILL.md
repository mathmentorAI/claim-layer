---
name: claimlayer_verify
description: Deterministic <1ms computable verification gate for multi-document legal and financial audits inside Harness² / OpenCode.
---

# ClaimLayer v3 Verification Skill (`claimlayer_verify`)

Use `scripts/claimlayer_gate.py` to deterministically verify quotes, quantities, units, document authority hierarchy, and section completeness before emitting final deliverables:

1. **Discover governing sources & divergent sections:**
   ```bash
   python3 scripts/claimlayer_gate.py prepare documents
   ```
2. **Verify your structured assertions (`PASS` / `RETRY` / `ESCALATE`):**
   ```bash
   python3 scripts/claimlayer_gate.py verify proposal.json
   ```
   Only generate your final `output/` document once `claimlayer_gate.py verify` returns `PASS` with a `CLAIMLAYER-MERKLE-SHA256-v3` cryptographic receipt.
