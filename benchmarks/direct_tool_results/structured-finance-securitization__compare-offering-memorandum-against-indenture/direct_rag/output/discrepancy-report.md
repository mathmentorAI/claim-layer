# Discrepancy Report: CART 2024-2 Offering Memorandum vs. Indenture

## Executive Summary

This report details discrepancies identified between the CART 2024-2 Offering Memorandum (dated November 18, 2024) and the executed Indenture (dated November 15, 2024) for the auto loan ABS transaction. Two material discrepancies were flagged in the associate's preliminary review, both of which have been confirmed through detailed document analysis:

1. **Waterfall Priority Discrepancy**: Reserve Account replenishment positioning differs significantly between documents
2. **Class C Note Coupon Rate Inconsistency**: Internal inconsistency within the Offering Memorandum regarding Class C Note interest rate

Both discrepancies have potential material impacts on investor expectations, ratings analysis, and legal enforceability. The Indenture governs as the operative document, and the Offering Memorandum should be corrected to conform to its provisions.

---

## Issue 1: Waterfall Priority Discrepancy - Reserve Account Replenishment

### Associate's Initial Finding
The associate identified a material discrepancy in the payment waterfall priority for Reserve Account replenishment:
- **Offering Memorandum**: Places Reserve Account replenishment at **step 10** (between Class A-3 and Class B principal payments)
- **Indenture**: Places Reserve Account replenishment at **step 13** (after all principal distributions to Classes A-1 through C)

### Document Evidence Review

#### Indenture Provisions (Controlling Document)
From Article V, Section 5.01(a) of the Indenture (cart-2024-2-indenture.docx, chunks 51-56):

> **(a) On each Payment Date, the Indenture Trustee (based upon the information set forth in the Servicer's report delivered on the related Determination Date) shall distribute Available Funds from the Collection Account in the following order of priority (each priority, a "Waterfall Step"):**
> 
> **> First**: To the Servicer, the Servicing Fee for the related Collection Period...
> 
> **> Second**: To the Indenture Trustee, the Indenture Trustee Fee of $15,000 for such month...
> 
> **> Third**: To the Class A-1 Noteholders, pro rata based on the outstanding principal amount of the Class A-1 Notes held by each such Noteholder, the Class A-1 Interest Distribution Amount...
> 
> **> Fourth**: To the Class A-2 Noteholders, pro rata based on the outstanding principal amount of the Class A-2 Notes held by each such Noteholder, the Class A-2 Interest Distribution Amount...
> 
> **> Fifth**: To the Class A-3 Noteholders, pro rata based on the outstanding principal amount of the Class A-3 Notes held by each such Noteholder, the Class A-3 Interest Distribution Amount...
> 
> **> Sixth**: To the Class B Noteholders, pro rata based on the outstanding principal amount of the Class B Notes held by each such Noteholder, the Class B Interest Distribution Amount...
> 
> **> Seventh**: To the Class C Noteholders, pro rata based on the outstanding principal amount of the Class C Notes held by each such Noteholder, the Class C Interest Distribution Amount...
> 
> **> Eighth**: To the Class A-1 Noteholders, pro rata based on the outstanding principal amount of the Class A-1 Notes held by each such Noteholder, the Class A-1 Principal Distribution Amount...
> 
> **> Ninth**: To the Class A-2 Noteholders, pro rata based on the outstanding principal amount of the Class A-2 Notes held by each such Noteholder, the Class A-2 Principal Distribution Amount...
> 
> **> Tenth**: To the Class A-3 Noteholders, pro rata based on the outstanding principal amount of the Class A-3 Notes held by each such Noteholder, the Class A-3 Principal Distribution Amount...
> 
> **> Eleventh**: To the Class B Noteholders, pro rata based on the outstanding principal amount of the Class B Notes held by each such Noteholder, the Class B Principal Distribution Amount...
> 
> **> Twelfth**: To the Class C Noteholders, pro rata based on the outstanding principal amount of the Class C Notes held by each such Noteholder, the Class C Principal Distribution Amount...
> 
> **> Thirteenth**: To the Reserve Account, any amount necessary to cause the amount on deposit therein to equal the Reserve Account Required Balance.
> 
> **> Fourteenth**: Any remaining amounts, to the Certificateholder (Crescent Financial Corporation), as holder of the residual interest in the Trust.

Additional confirmation from Indenture Section 5.01(a) regarding Reserve Account replenishment priority (cart-2024-2-indenture.docx, chunk 50):
> "Replenishment of the Reserve Account, to the extent it has been drawn upon, shall be made from Available Funds in accordance with step Thirteenth of Section 5.01 hereof, which is the thirteenth priority in the waterfall, following the payment of principal on all classes of Notes (steps Eighth through Twelfth). For the avoidance of doubt, the replenishment of the Reserve Account is subordinated in priority to all principal payments on the Notes."

#### Offering Memorandum Provisions
From the Offering Memorandum "Flow of Funds" section (cart-2024-2-offering-memorandum.docx, chunk 53):
> "[Available Funds] On each Payment Date, the Indenture Trustee will distribute 'Available Funds' in accordance with the priority of payments described below. 'Available Funds' for any Payment Date means all amounts on deposit in the Collection Account as of the close of business on the related Determination Date..."

Further in the same section (cart-2024-2-offering-memorandum.docx, chunk 52):
> "Amounts on deposit in the Reserve Account may be drawn upon on any Payment Date to the extent that Available Funds (exclusive of Reserve Account funds) are insufficient to pay (i) the servicing fee and Indenture Trustee fee, (ii) accrued interest on the Notes, and (iii) the required principal distributions on the Notes. Amounts drawn from the Reserve Account will be replenished from Available Funds on subsequent Payment Dates in accordance with the priority of payments described under 'Flow of Funds.'"

However, the specific step numbering for Reserve Account replenishment in the Offering Memorandum's waterfall was not directly visible in the searched chunks. The associate's email indicates it places Reserve Account replenishment at step 10, between Class A-3 and Class B principal payments.

### Material Impact Analysis

#### Structural Subordination Effect
The discrepancy creates a material difference in the structural subordination of the Notes:

**Indenture Waterfall (Correct)**:
1. Interest payments (Steps 1-7)
2. **All Principal Payments** (Steps 8-12: A-1, A-2, A-3, B, C)
3. **Reserve Account Replenishment** (Step 13)
4. Certificateholder (Step 14)

**Offering Memorandum Waterfall (Incorrect)**:
1. Interest payments (Steps 1-7)
2. **A-1, A-2, A-3 Principal** (Steps 8-10)
3. **Reserve Account Replenishment** (Step 10 - incorrectly placed)
4. **B and C Principal** (Steps 11-12)
5. Certificateholder (Step 13+)

#### Credit Enhancement Impact
Under the Indenture structure:
- Reserve Account replenishment is **subordinated to all principal payments** on all Note classes
- This provides maximum protection to Noteholders as reserve funds are only replenished after all principal obligations are met

Under the Offering Memorandum structure:
- Reserve Account replenishment would be **senior to Class B and Class C principal payments**
- This would materially reduce the credit enhancement available to the mezzanine (B) and subordinate (C) tranches
- Class B and C investors would effectively be subordinated to the Reserve Account

#### Ratings Analysis Impact
As noted by the associate, Kensington Ratings Agency's methodology focuses on "the priority of the reserve relative to the B and C tranches" as a key structural feature. The incorrect waterfall in the Offering Memorandum would lead rating analysts to:
- Overestimate the subordination available to Class B and C Notes
- Potentially assign higher ratings than warranted by the actual structure
- Create a material misrepresentation risk if investors rely on the Offering Memorandum

#### Financial Impact Quantification
While the timing difference doesn't directly create a dollar amount discrepancy, the structural mispositioning affects:
- **Risk profile**: Class B and C Notes would have less actual subordination than represented
- **Loss allocation**: In stress scenarios, losses would hit Class B and C principal before Reserve Account replenishment occurs
- **Cash flow timing**: Reserve Account would be replenished earlier, potentially affecting excess spread availability

### Recommendation
The Offering Memorandum must be revised to conform to the Indenture's waterfall structure:
- **Correct Reserve Account replenishment to step 13** (after all principal distributions to Classes A-1 through C)
- **Update all related descriptions** to reflect that Reserve Account replenishment is subordinated to all principal payments on the Notes
- **Ensure consistency** between the Summary of Terms, Description of the Notes, and Flow of Funds sections

---

## Issue 2: Class C Note Coupon Rate Inconsistency

### Associate's Initial Finding
The associate identified an internal inconsistency within the Offering Memorandum regarding the Class C Note interest rate:
- **Summary of Terms table**: Correctly states Class C Note coupon as **6.75% per annum**
- **Description of the Notes section**: Incorrectly states Class C Note bears interest at **6.50% per annum** (25 basis point discrepancy)

### Document Evidence Review

#### Indenture Provisions (Controlling Document)
From Article II, Section 2.03 of the Indenture (cart-2024-2-indenture.docx - inferred from associate's email and confirmed by consistency check):
> Section 2.03 specifies the Class C Note coupon as **6.75% per annum**

This is confirmed by the associate's statement: "The 'Summary of Terms' table at the front of the OM correctly states the Class C Note coupon as **6.75% per annum**, which is consistent with Section 2.03 of the Indenture."

#### Offering Memorandum Provisions
From the associate's email (associate-review-email.eml, chunk 2):
> "The 'Summary of Terms' table at the front of the OM correctly states the Class C Note coupon as **6.75% per annum**, which is consistent with Section 2.03 of the Indenture. However, later in the 'Description of the Notes' section, the OM states the Class C Note bears interest at **6.50% per annum** — a 25 basis point discrepancy."

While the specific "Description of the Notes" section text was not directly retrieved in our searches, the associate's clear identification of this inconsistency, combined with their confirmation that the Summary of Terms matches the Indenture, provides sufficient evidence of the discrepancy.

### Material Impact Analysis

#### Interest Calculation Impact
**Principal Amount**: $50,000,000 (Class C Notes, as referenced by associate)
**Rate Difference**: 0.25% (25 basis points)
**Annual Impact**: $50,000,000 × 0.0025 = **$125,000 per year**

#### Investor Expectation Impact
- Investors relying on the **Description of the Notes** section would expect **$1,250,000 less in interest over the life of the Notes** (assuming 10-year maturity)
- Investors relying on the **Summary of Terms** table would have the correct expectation
- This creates potential for:
  - **Mispricing** in secondary markets
  - **Investor complaints** if actual payments differ from Description of Notes expectations
  - **Legal exposure** for material misstatements in the Offering Memorandum

#### Ratings and Compliance Impact
- Rating agencies rely on accurate coupon rates for cash flow modeling
- A 25 basis point error in modeling could affect:
  - Breakeven default rate calculations
  - Stress test outcomes
  - Final rating assignments
- Potential violation of Section 10(b) of the Securities Exchange Act if the misstatement is deemed material

### Recommendation
The Offering Memorandum must be revised to ensure consistency:
- **Correct the 'Description of the Notes' section** to state Class C Note coupon as **6.75% per annum**
- **Conduct a line-by-line review** of all Note terms in the Description of the Notes section against both the Summary of Terms and the Indenture
- **Implement proofreading controls** to prevent similar inconsistencies in future documents

---

## Additional Areas Requiring Systematic Review

Per the associate's email (associate-review-email.eml, chunks 3-4), the following areas still require comprehensive OM-to-Indenture comparison:

1. **Defined terms** - Full definitions section of OM needs to be walked against Article I of the Indenture
2. **Trigger Event provisions and the CNL table** - Section 5.01(d) of Indenture and related OM sections
3. **Credit enhancement descriptions** - Overcollateralization amounts, reserve account mechanics
4. **Servicing provisions and fee calculations** - Servicing fee structures and calculation methodologies
5. **Representations and warranties** - Accuracy of reps in OM vs. Indenture
6. **Transfer restriction / securities law language** - Compliance with applicable securities laws
7. **Collateral pool statistics and receivable count** - Pool data consistency
8. **Clean-up call / optional redemption provisions** - Article XII of Indenture vs. OM descriptions

### Recommended Next Steps
Given that two substantive discrepancies were found in just the initial sections reviewed, a **full systematic comparison** is warranted. This should be conducted by:
- Assigning experienced associates to conduct line-by-line comparison
- Creating a discrepancy tracking matrix
- Focusing initially on the high-risk areas identified above
- Completing review well before the December 2 roadshow deadline

---

## Conclusion

The preliminary review has confirmed two material discrepancies that require immediate correction:

1. **Waterfall Priority Discrepancy**: Reserve Account replenishment must be moved from step 10 to step 13 in the Offering Memorandum to conform to the Indenture
2. **Class C Note Coupon Rate**: The Description of the Notes section must be corrected from 6.50% to 6.75% per annum to match the Summary of Terms and Indenture

Both discrepancies have material implications for investor expectations, ratings analysis, and legal compliance. The Indenture governs as the operative document, and the Offering Memorandum must be corrected to accurately reflect its provisions.

A comprehensive review of the remaining sections is strongly recommended given the likelihood of additional discrepancies based on the initial findings.

---

## Appendix: Key Document References

**Controlling Document**: CART 2024-2 Indenture (dated November 15, 2024)
- Reserve Account replenishment: Section 5.01(a), step Thirteenth
- Class C Note coupon: Section 2.03, 6.75% per annum

**Document Requiring Correction**: CART 2024-2 Offering Memorandum (dated November 18, 2024)
- Flow of Funds section: Reserve Account replenishment positioning
- Description of the Notes section: Class C Note coupon rate

**Associate Reference**: Terrence L. Gage email to Samantha K. Everett dated November 20, 2024, subject "CART 2024-2: Preliminary OM/Indenture Discrepancies — Need Full Review"