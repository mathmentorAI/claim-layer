# Compliance Check: ClaimLayer LICENSE (BSL 1.1)

**Date:** 2026-03-31
**Reviewed by:** Automated compliance check (not legal advice)
**Scope:** LICENSE file, README.md, pyproject.toml, setup.py

---

## Summary

**Assessment: Proceed with conditions**

The LICENSE file implements a Business Source License 1.1 (BSL 1.1) framework with custom language. While the overall structure is sound, there are several inconsistencies and potential compliance gaps that should be addressed before broader distribution or enforcement.

---

## Applicable Regulations and Standards

| Standard / Framework | Relevance | Key Requirements |
|---|---|---|
| BSL 1.1 (MariaDB canonical template) | The LICENSE declares itself as BSL 1.1 and references mariadb.com/bsl11 | Change Date ≤ 4 years from release; Change License must be GPL v2-compatible; canonical header fields required |
| SPDX License Identifier (BUSL-1.1) | pyproject.toml declares `license = {text = "BSL-1.1"}` | License text should match the canonical BSL 1.1 template if claiming that identifier |
| Apache License 2.0 | Declared as the Change License | Must satisfy BSL 1.1's requirement that the Change License be GPL-compatible |
| Spanish Civil Code / IP Law | Governing law is Spain, jurisdiction is Madrid | Enforceability of license terms depends on Spanish contract and IP law |

---

## Requirements

| # | Requirement | Status | Action Needed |
|---|---|---|---|
| 1 | LICENSE text matches canonical BSL 1.1 template | **Not Met** | The LICENSE uses substantially custom language (custom sections, restructured terms). If claiming SPDX identifier BUSL-1.1, consider aligning with the canonical template or clarifying the license is "based on" BSL 1.1 |
| 2 | Change Date ≤ 4 years from release | **Unknown** | Change Date is 2030-03-31. If v0.3.0 was released in 2026, this is ~4 years — at the boundary. If released earlier, it may exceed the 4-year guideline. Each version should have its own Change Date calculated from its release |
| 3 | Change License is GPL v2-compatible | **Requires Review** | Apache 2.0 is compatible with GPLv3 but the FSF considers it incompatible with GPLv2. The BSL 1.1 canonical text requires compatibility "with GPL Version 2.0 or a later version." The "or a later version" clause is debated — see Risk Areas |
| 4 | README license description matches LICENSE | **Not Met** | README states "Free for internal use within your organization" — LICENSE explicitly requires a commercial license for internal production use. This is a material inconsistency |
| 5 | setup.py declares license consistently | **Not Met** | setup.py (v0.1.0) has no license field; pyproject.toml (v0.3.0) declares BSL-1.1. Version and license metadata are inconsistent |
| 6 | Required BSL 1.1 header fields present | **Met** | Licensor, Licensed Work, Additional Use Grant, Change Date, and Change License are all specified |
| 7 | Distribution requirement (include license unmodified) | **Met** | Section 3 requires the License to be included unmodified in distributions |
| 8 | Warranty disclaimer present | **Met** | "AS IS" disclaimer and limitation of liability are included |

---

## Risk Areas

| Risk | Severity | Detail |
|---|---|---|
| README contradicts LICENSE on internal use | **High** | README says "Free for internal use within your organization." LICENSE says "Any use in a Production Environment (including internal use for real business operations) requires an explicit commercial license." A user relying on the README could unknowingly violate the license. This could weaken enforceability if challenged |
| Apache 2.0 / GPLv2 compatibility debate | **Medium** | The FSF considers Apache 2.0 incompatible with GPLv2 due to patent termination provisions. It is compatible with GPLv3. Whether this satisfies the BSL 1.1 "GPL Version 2.0 or a later version" requirement depends on how "or a later version" is interpreted. Other BSL adopters (e.g., HashiCorp) have used similar Change License choices, but this has not been judicially tested |
| Custom license text claiming BUSL-1.1 identifier | **Medium** | The pyproject.toml uses the SPDX identifier "BSL-1.1," but the LICENSE text is substantially customized (added sections on competition, contributions, trademarks, governing law). Users and automated tools expecting canonical BSL 1.1 terms may be misled. This could create confusion in dependency audits |
| Anti-competition clause breadth | **Medium** | The prohibition on building products in "Evidence Intelligence, AI verification, RAG auditing, or any offerings substantially similar in purpose" is broad. "RAG auditing" and "AI verification" could encompass many AI/ML tools. Vague scope may be difficult to enforce or may deter legitimate non-competing use |
| Licensor vs. Author identity | **Low** | Licensor is "Francisco Jesús Hernández de Blas" (individual). pyproject.toml author is "Deltoryx" (entity?). Trademark section protects "Deltoryx" and "The Claim Layer." The legal relationship between the individual and the entity should be clear for enforceability |
| Change Date boundary compliance | **Low** | If v0.3.0 was released in early 2026, the 2030-03-31 Change Date is at the 4-year limit. Future versions should track their own Change Dates relative to their release dates |

---

## Recommended Actions

1. **Fix the README immediately.** Remove or correct the claim "Free for internal use within your organization." Replace with language consistent with the LICENSE, e.g., "Free for non-production, testing, and evaluation use. Production use (including internal) requires a commercial license."

2. **Clarify the SPDX identifier.** Either align the LICENSE text more closely with the canonical BSL 1.1 template (adding custom terms in the Additional Use Grant field), or change the SPDX identifier to something like `LicenseRef-ClaimLayer-BSL` to signal customization.

3. **Evaluate the Change License choice.** Consult counsel on whether Apache 2.0 satisfies the BSL 1.1 "GPL Version 2.0 or a later version" requirement. Consider using GPLv3 or MPL 2.0 as alternatives if strict compliance is desired.

4. **Align setup.py with pyproject.toml.** Either remove setup.py if pyproject.toml is the primary build config, or synchronize version and license fields.

5. **Narrow the anti-competition clause.** Consider defining the restricted competitive scope more precisely (e.g., referencing ClaimLayer's specific functionality rather than broad categories like "RAG auditing").

6. **Document the Licensor-entity relationship.** Clarify whether "Deltoryx" is a trade name, company, or brand of the Licensor. This strengthens enforceability of both the license and the trademark clause.

---

## Approvals Needed

| Approver | Why | Status |
|---|---|---|
| Licensor / Legal counsel | Validate Change License GPL-compatibility interpretation | Pending |
| Licensor | Approve README corrections to resolve inconsistency | Pending |
| IP counsel (Spain) | Confirm enforceability of anti-competition clause under Spanish law | Pending |

---

## Further Review Recommended

- **Outside counsel review** of the anti-competition clause enforceability under Spanish and EU competition law. Broad non-compete provisions in software licenses can raise antitrust concerns in certain EU jurisdictions.
- **SPDX / license compliance specialist** review to confirm whether the customized text can legitimately use the BUSL-1.1 identifier or if a custom identifier is needed.
- **Per-version Change Date tracking**: As new versions are released, each should document its own Change Date to comply with the 4-year requirement.

---

*This assessment is automated and does not constitute legal advice. All findings should be reviewed by a qualified legal professional before action.*
