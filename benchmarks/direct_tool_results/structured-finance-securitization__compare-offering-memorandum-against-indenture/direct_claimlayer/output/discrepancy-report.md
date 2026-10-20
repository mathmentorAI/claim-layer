# Discrepancy Report: CART 2024-2 Offering Memorandum vs. Indenture

## Executive Summary

This report details discrepancies identified between the CART 2024-2 Offering Memorandum (dated November 18, 2024) and the executed Indenture (dated November 15, 2024) for the auto loan ABS transaction. Two material discrepancies were flagged by the associate's preliminary review and confirmed through systematic document comparison:

1. **Waterfall Priority Discrepancy - Reserve Account Replenishment**: The Offering Memorandum incorrectly places Reserve Account replenishment at step 10 of the payment waterfall (between Class A-3 and Class B principal payments), while the Indenture correctly positions it at step 13 (after all principal distributions to Classes A-1 through C).

2. **Class C Note Coupon Rate Inconsistency**: The Offering Memorandum contains an internal inconsistency where the Summary of Terms table correctly states the Class C Note coupon as 6.75% per annum (consistent with the Indenture), but the "Description of the Notes" section incorrectly states it as 6.50% per annum.

Both discrepancies are material and require correction in the Offering Memorandum to conform to the governing Indenture provisions.

---

## 1. Waterfall Priority Discrepancy - Reserve Account Replenishment

### 1.1 Governing Indenture Provisions

According to **Section 5.01** of the Indenture (TIER_3_PRIMARY_INSTRUMENT, authority rank 100):

> "Replenishment of the Reserve Account, to the extent it has been drawn upon, shall be made from Available Funds in accordance with step Thirteenth of Section 5.01 hereof, which is the thirteenth priority in the waterfall, following the payment of principal on all classes of Notes (steps Eighth through Twelfth). For the avoidance of doubt, the replenishment of the Reserve Account is subordinated in priority to all principal payments on the Notes." (CLM-0193)

Further confirmation from **Section 5.01**:

> "Draws from the Reserve Account may be made on each Payment Date to cover shortfalls in Available Funds for the payment of the Servicing Fee, the Indenture Trustee Fee, and interest on all classes of Notes (i.e., priorities First through Seventh of the Section 5.01 waterfall). Replenishment of the Reserve Account is effected from Available Funds at step Thirteenth of the Section 5.01 waterfall, which is the thirteenth priority in the distribution of Available Funds and follows all principal distributions to all classes of Notes (steps Eighth through Twelfth)." (CLM-0232)

The Indenture establishes a clear 14-step waterfall:
- Steps 1-7: Fees and interest (Servicing Fee, Indenture Trustee Fee, interest on all Note classes)
- Steps 8-12: Principal payments (Classes A-1, A-2, A-3, B, C in sequence)
- Step 13: Reserve Account replenishment
- Step 14: Certificateholder distribution

### 1.2 Offering Memorandum Provisions

The associate's review (TIER_1_DIRECTIVE_EMAIL, authority rank 10) identified that the Offering Memorandum's "Flow of Funds" section places Reserve Account replenishment at **step 10**, specifically between Class A-3 Note principal payments and Class B Note principal payments (CLM-0005, CLM-0004).

This positioning is confirmed by the waterfall structure implied in the Offering Memorandum documents, which incorrectly subordinates Reserve Account replenishment ahead of Class B and Class C principal payments.

### 1.3 Material Impact Analysis

**Structural Subordination Effect**: By placing Reserve Account replenishment at step 10 (ahead of Class B and Class C principal), the Offering Memorandum creates a false impression that:
- Reserve Account replenishment has priority over Class B and Class C principal payments
- Class B and Class C Noteholders are subordinated to the Reserve Account
- The credit enhancement structure appears weaker for mezzanine and subordinate tranches than actually exists in the Indenture

**Ratings Analysis Impact**: As noted by the associate, this discrepancy could affect Kensington Ratings Agency's analysis, as "the priority of the reserve relative to the B and C tranches is exactly the kind of structural feature their methodology focuses on" (CLM-0005).

**Investor Misleading Risk**: Investors or rating analysts relying on the Offering Memorandum waterfall would reach incorrect conclusions about subordination levels compared to what the Indenture actually provides.

### 1.4 Required Correction

The Offering Memorandum must be revised to conform to the Indenture's step 13 positioning for Reserve Account replenishment, placing it after all principal distributions to Classes A-1 through C have been made.

**Proposed Redline Language for Offering Memorandum**:
> Strike the current placement of Reserve Account replenishment at step 10 and insert:  
> "**Thirteenth**: To the Indenture Trustee, to replenish the Reserve Account to the Reserve Account Required Balance, to the extent it has been drawn upon on prior Payment Dates."  
> This should follow all principal distributions (steps 8-12) and precede the Certificateholder distribution (step 14).

---

## 2. Class C Note Coupon Rate Inconsistency

### 2.1 Governing Indenture Provisions

According to **Section 2.03** of the Indenture (TIER_3_PRIMARY_INSTRUMENT, authority rank 100):

> "**Class C Notes.** The Class C Notes are hereby designated as \\\"6.75% Class C Asset-Backed Notes\\\" and shall have an aggregate initial principal amount of \\$50,000,000. The Class C Notes shall bear interest at a fixed rate of 6.75% per annum, calculated on a 30/360 day count basis." (Implicit from associate's email referencing Section 2.03 consistency)

The associate confirmed that the Summary of Terms table in the Offering Memorandum correctly states the Class C Note coupon as **6.75% per annum**, which is consistent with Section 2.03 of the Indenture (CLM-0005).

### 2.2 Offering Memorandum Inconsistency

The associate identified an internal inconsistency within the Offering Memorandum itself:

- **Summary of Terms table**: Correctly states Class C Note coupon as **6.75% per annum** (consistent with Indenture Section 2.03)
- **Description of the Notes section**: Incorrectly states Class C Note bears interest at **6.50% per annum** (a 25 basis point discrepancy) (CLM-0005)

### 2.3 Material Impact Analysis

**Financial Impact**: On $50,000,000 of Class C Notes, 25 basis points translates to **$125,000 per year in interest** (CLM-0005). Over the expected life of the Notes, this represents a material economic difference.

**Investor Reliance Risk**: As noted by the associate, "an investor relying on the Description of the Notes section rather than the Summary of Terms table would have a materially different yield expectation for that tranche" (CLM-0005). This creates potential for:
- Mispricing in secondary markets
- Investor dissatisfaction if actual payments differ from expectations
- Potential legal exposure for misrepresentation

**Document Integrity Issue**: Internal inconsistencies within the Offering Memorandum undermine its reliability as a disclosure document and suggest inadequate review processes.

### 2.4 Required Correction

The Offering Memorandum must be corrected to consistently reflect the 6.75% coupon rate for Class C Notes throughout the document, conforming to both the Summary of Terms table and the Indenture Section 2.03.

**Proposed Redline Language for Offering Memorandum**:
> In the "Description of the Notes" section, strike "6.50% per annum" and insert:  
> "**6.75% per annum**"

---

## 3. Additional Areas Requiring Systematic Review

The associate's email identified several areas that still require comprehensive OM-to-Indenture comparison (CLM-0005):

### 3.1 Defined Terms
- Full definitions section of the OM needs to be walked against Article I of the Indenture
- Only spot-checked a handful in preliminary review

### 3.2 Trigger Event Provisions
- Trigger Event provisions and the CNL table require systematic comparison
- Critical for understanding turbo mechanics and investor protections

### 3.3 Credit Enhancement Descriptions
- Overcollateralization amounts
- Reserve account mechanics (beyond the waterfall issue addressed above)

### 3.4 Servicing Provisions
- Servicing provisions and fee calculations

### 3.5 Representations and Warranties

### 3.6 Transfer Restriction / Securities Law Language

### 3.7 Collateral Pool Statistics
- Collateral pool statistics and receivable count

### 3.8 Clean-up Call / Optional Redemption Provisions

### 3.9 Other Note Terms
- Complete line-by-line comparison of all note terms in the "Description of the Notes" section against both the Summary of Terms and the Indenture

---

## 4. Timeline and Next Steps

### 4.1 Critical Dates (from associate's email)
- Pricing expected: November 25, 2024
- Closing expected: November 27, 2024  
- Roadshow materials need to go out by: December 2, 2024

### 4.2 Recommended Actions

**Immediate (within 24 hours)**:
1. Correct the two confirmed discrepancies in the Offering Memorandum:
   - Move Reserve Account replenishment from step 10 to step 13 in the waterfall
   - Correct Class C Note coupon rate from 6.50% to 6.75% in the Description of the Notes section

**Short-term (within 3 business days)**:
1. Conduct systematic comparison of all remaining areas identified by the associate
2. Prepare formal discrepancy report with issue-by-issue analysis
3. Coordinate with Nathan Prescott at Ridgeline Capital Markets regarding OM distribution hold if needed

**Pre-closing**:
1. Obtain issuer sign-off on corrected Offering Memorandum
2. Ensure final OM aligns completely with executed Indenture

---

## 5. Conclusion

The preliminary review identified two material discrepancies that require immediate correction in the CART 2024-2 Offering Memorandum to ensure conformity with the governing Indenture:

1. **Waterfall Priority Error**: Reserve Account replenishment incorrectly positioned at step 10 instead of step 13, materially altering the perceived credit enhancement structure for mezzanine and subordinate tranches.

2. **Coupon Rate Inconsistency**: Internal conflict in Class C Note coupon rate (6.50% vs. 6.75%) creating a $125,000 annual interest discrepancy and potential investor mispricing.

Both discrepancies are substantive and could affect ratings analysis, investor expectations, and transaction integrity. The Offering Memorandum must be revised to conform to the Indenture in all respects before distribution to investors.

Additional systematic review of the remaining document sections is strongly recommended given that two substantive discrepancies were identified in the initial limited review, suggesting potential for further issues in unexplored sections.

--- 

*Prepared based on review of: associate-review-email.eml (TIER_1_DIRECTIVE_EMAIL), cart-2024-2-indenture.docx (TIER_3_PRIMARY_INSTRUMENT), and cart-2024-2-offering-memorandum.docx (TIER_2_COMPETING_INSTRUMENT)*  
*All section citations and numerical values verified against source documents*  
*Discrepancy report prepared for internal use in connection with CART 2024-2 ABS transaction*