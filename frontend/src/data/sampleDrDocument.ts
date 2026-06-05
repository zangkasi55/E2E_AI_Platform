// =============================================================================
// data/sampleDrDocument.ts — Complete synthetic Document Intake (DR) package for
// UC1 (APP-1001 · Siam Lotus Foods Co., Ltd.). Mirrors
// data/credit_memo/sample_dr_document.md and reconciles with the applicants /
// financials / bureau / documents synthetic datasets. Used as the default file
// pre-attached to the DR node and shown in the in-page document preview.
// =============================================================================

export const SAMPLE_DR_FILE_NAME = "credit-file-APP-1001-siam-lotus-foods.txt";

export const SAMPLE_DR_DOCUMENT = `SME CREDIT FACILITY — APPLICATION & CREDIT FILE
Document type: Document Intake (DR) package
Bank reference: DR-APP-1001-2026-06
Date received: 1 June 2026
Relationship Manager: Anchalee P. (SME Banking, Central Region)
Classification: Confidential — Credit Use Only · SYNTHETIC TEST DATA

============================================================
1. APPLICANT IDENTIFICATION
------------------------------------------------------------
Applicant ID            : APP-1001
Legal name              : Siam Lotus Foods Co., Ltd.
Company registration no.: 0105560000011
Registered address      : 88/12 Moo 4, Tha Sai, Mueang Samut Sakhon, Samut Sakhon 74000
Year established         : 2014
Sector                  : Food & Beverage Manufacturing (processed & chilled foods)
Employees               : 85
Tax ID (VAT)            : 0-1055-60000-01-1
Ownership               : Privately held — founder 62%, family 28%, ESOP pool 10%
Authorised directors    : Mr. Prasit Wattanachai (MD), Ms. Lawan Wattanachai (Finance Director)

============================================================
2. FACILITY REQUESTED
------------------------------------------------------------
Requested amount   : THB 12,000,000
Purpose            : (a) Working-capital headroom for export order growth;
                     (b) Cold-storage expansion (1,200-pallet chilled warehouse)
Facility structure : THB 7,000,000 term loan (capex) + THB 5,000,000 revolving WC line
Tenor              : 60 months (term portion); revolving reviewed annually
Proposed pricing   : MLR + 1.50% (term) · MOR + 1.25% (revolving)
Repayment          : Monthly amortisation (term); cleanup of revolving every 120 days
Collateral offered : First charge over new cold-storage building & equipment
                     (appraised THB 9.4M); personal guarantee of MD
Drawdown           : Capex tranche milestone-based; WC line on demand

============================================================
3. PURPOSE & USE OF PROCEEDS
------------------------------------------------------------
The applicant has secured new export supply contracts in Vietnam and Malaysia
commencing Q3 2026. Cold-chain capacity is the binding constraint on fulfilling
these orders. Proceeds fund construction of a 1,200-pallet chilled warehouse and
additional working capital to bridge the extended cash-conversion cycle on export
receivables (avg. 65 days).

Use-of-proceeds breakdown:
  - Cold-storage building & refrigeration plant ...... THB 6.2M
  - Racking, handling equipment, controls ............ THB 0.8M
  - Incremental raw-material & packaging inventory ... THB 3.4M
  - Export receivable financing buffer ............... THB 1.6M

============================================================
4. FINANCIAL SUMMARY (3-YEAR, AUDITED) — THB
------------------------------------------------------------
Line item            FY2023         FY2024         FY2025
Revenue          210,000,000    238,000,000    271,000,000
COGS             162,000,000    181,000,000    205,000,000
EBITDA            24,500,000     28,900,000     33,600,000
Net income        11,800,000     14,200,000     16,900,000
Total assets     145,000,000    162,000,000    181,000,000
Current assets    78,000,000     86,000,000     95,000,000
Current liab.     52,000,000     55,000,000     58,000,000
Total debt        61,000,000     66,000,000     70,000,000
Interest expense   3,100,000      3,400,000      3,700,000
Cash              14,000,000     17,500,000     21,000,000
Equity            64,000,000     73,000,000     84,000,000

Derived metrics (FY2025):
  - Revenue CAGR (FY23->FY25) ....... ~13.6%
  - EBITDA margin ................... 12.4%
  - EBITDA / interest (coverage) .... ~9.1x
  - Net debt (total debt - cash) .... THB 49,000,000
  - Net debt / EBITDA ............... ~1.46x
  - Current ratio ................... 1.64x

Policy reference: SME term-facility minimum DSCR is 1.25x and net debt / EBITDA
ceiling is 4.0x at origination. The applicant is comfortably inside both limits.

============================================================
5. MANAGEMENT DISCUSSION (FY2025)
------------------------------------------------------------
Management attributes FY2025 revenue growth of 13.9% to new export contracts in
Vietnam and Malaysia. The cold-storage expansion is expected to lift gross margin
by ~150 bps once commissioned, by reducing spoilage and outsourced storage costs.
Order backlog at filing date covers ~7 months of incremental chilled volume.

============================================================
6. INDUSTRY CONTEXT
------------------------------------------------------------
Thailand processed-food exports are projected to grow 6-8% in 2026 on regional
demand. Cold-chain capacity remains a competitive bottleneck for mid-sized
processors in Samut Sakhon, supporting the rationale for the requested capex.

============================================================
7. CREDIT BUREAU REPORT (SUMMARY)
------------------------------------------------------------
Bureau              : NCB-SYNTHETIC
Pulled date         : 28 May 2026
Score               : 742  (Band A — Low Risk)
Total outstanding   : THB 61,000,000
Active accounts     : 4
Delinquencies (12m) : 0
Worst status (36m)  : Current
Inquiries (6m)      : 2
Notes               : Clean repayment history. One revolving facility at 38% util.

============================================================
8. COLLATERAL & SECURITY
------------------------------------------------------------
New cold-storage building (to be built) .... THB 6,400,000  (cost + appraisal)
Refrigeration & handling plant ............. THB 3,000,000  (supplier quotation)
Personal guarantee — MD .................... unlimited PG
Existing plant ............................. negative pledge (not charged)
Indicative LTV on charged assets ........... ~74% (term tranche)

============================================================
9. KYC / COMPLIANCE CHECKLIST
------------------------------------------------------------
[x] Company affidavit & DBD registration verified (0105560000011)
[x] Shareholder & UBO identification on file (>25% owners cleared)
[x] Directors' ID verification complete
[x] AML / sanctions screening — no adverse hits (synthetic)
[x] VAT registration and 3-year tax filings on file
[x] Site visit completed 22 May 2026 (RM Anchalee P.)
[x] Food-safety GMP/HACCP certificates current

============================================================
10. DOCUMENTS ENCLOSED
------------------------------------------------------------
 1. Loan application form (signed)
 2. Audited financial statements FY2023, FY2024, FY2025
 3. Management discussion & analysis FY2025
 4. 12-month bank statements (operating account)
 5. Company affidavit & shareholder register (DBD)
 6. Cold-storage construction quotation & equipment specs
 7. Export supply contracts (Vietnam, Malaysia) — redacted
 8. NCB-SYNTHETIC credit bureau report (28 May 2026)
 9. Collateral appraisal (preliminary) & insurance schedule
10. GMP/HACCP food-safety certificates

============================================================
11. RELATIONSHIP MANAGER NOTE
------------------------------------------------------------
Long-standing operating client with consistent double-digit growth, conservative
leverage, and a clean bureau record. The facility is strategically coherent and
well-secured. Recommend progressing to credit-memo drafting and committee review,
subject to standard covenants (DSCR >= 1.25x maintenance, net debt / EBITDA <= 3.0x,
insurance assignment on charged assets).
                                   — Anchalee P., Relationship Manager, 1 June 2026

All figures and identities in this document are synthetic and generated for the
Agentic AI Platform PoC (UC1). They do not represent any real person or company.
`;

// =============================================================================
// Highly Confidential variant — same applicant, but a board/legal document that
// Microsoft Purview classifies as "Highly Confidential \\ Board & Legal".
// The credit-memo data-loss-prevention policy blocks this from agent ingestion.
// File name matches the synthetic Purview catalog in lib/sensitivity.ts so the
// mock demo and the live FastAPI gate both reject it identically.
// =============================================================================

export const SAMPLE_HC_FILE_NAME = "Siam-Lotus-Board-Resolution-HIGHLY-CONFIDENTIAL.txt";

export const SAMPLE_HC_DOCUMENT = `BOARD OF DIRECTORS — SPECIAL RESOLUTION (EXTRACT)
Document type: Board & Legal — Special Resolution
Bank reference: BR-APP-1001-2026-06
Date: 30 May 2026
Classification: HIGHLY CONFIDENTIAL — Board & Legal · SYNTHETIC TEST DATA
Distribution: Board members and General Counsel only. Do NOT ingest into
automated systems. Microsoft Purview label: Highly Confidential \\ Board & Legal.

============================================================
1. COMPANY
------------------------------------------------------------
Legal name              : Siam Lotus Foods Co., Ltd.
Company registration no.: 0105560000011
Applicant ID            : APP-1001

============================================================
2. MEETING
------------------------------------------------------------
Meeting type   : Special Meeting of the Board of Directors
Date / time    : 30 May 2026, 14:00 ICT
Quorum         : 5 of 5 directors present (quorum satisfied)
Chair          : Mr. Prasit Wattanachai (Managing Director)
Secretary      : Ms. Lawan Wattanachai (Finance Director)

============================================================
3. CONFIDENTIAL MATTERS RESOLVED
------------------------------------------------------------
3.1  Approved a confidential acquisition of a competing cold-chain operator
     for up to THB 180,000,000, subject to due diligence and financing.
3.2  Approved a directors' related-party guarantee structure and revised
     shareholder buy-out terms (sealed annex A — privileged).
3.3  Noted ongoing legal advice from external counsel regarding a contractual
     dispute with a former distributor (matter ref. LIT-2026-014, privileged).
3.4  Approved revised executive remuneration and a confidential ESOP re-pricing.

============================================================
4. PRIVILEGED / RESTRICTED CONTENT
------------------------------------------------------------
This extract contains legally privileged deliberations, unannounced M&A intent,
and personal remuneration data. It is labeled Highly Confidential and is OUT OF
SCOPE for the credit-memo drafting agent. The agent must rely on the General /
Internal credit file (credit-file-APP-1001-siam-lotus-foods.txt) instead.

============================================================
5. CERTIFICATION
------------------------------------------------------------
Certified a true extract of the minutes, omitting sealed privileged annexes.
                                   — Ms. Lawan Wattanachai, Company Secretary

All names, figures, and matters in this document are synthetic and generated for
the Agentic AI Platform PoC (UC1) to demonstrate Microsoft Purview sensitivity-
label enforcement. They do not represent any real person, company, or event.
`;
