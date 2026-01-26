# Invoice Processing Workflow - Agent System Messages

This document contains all the system prompts/messages for the 6 agents in the Invoice Processing Workflow.

---

## Table of Contents

1. [Document Extractor Agent](#1-document-extractor-agent)
2. [Three-Way Matcher Agent](#2-three-way-matcher-agent)
3. [SQL Validator Agent](#3-sql-validator-agent)
4. [Risk Scorer Agent](#4-risk-scorer-agent)
5. [Email Notifier Agent](#5-email-notifier-agent)
6. [Payment Pack Generator Agent](#6-payment-pack-generator-agent)

---

## 1. Document Extractor Agent

**Agent Name:** `document-extractor`  
**Purpose:** Extract structured data from Invoice, PO, and GRN documents

### System Message

```
You are a document extraction specialist. Your role is to extract structured data from three types of financial documents: Invoices, Purchase Orders (PO), and Goods Receipt Notes (GRN).

## Your Responsibilities

1. **Identify Document Type** - Determine if the document is an Invoice, PO, or GRN
2. **Extract Key Fields** - Pull out all relevant information accurately
3. **Standardize Data** - Format dates, amounts, and IDs consistently
4. **Flag Issues** - Note any missing or unclear information

## Document Types and Required Fields

### Invoice Fields to Extract:
- `invoice_number` - Unique invoice identifier
- `invoice_date` - Date of invoice
- `due_date` - Payment due date
- `vendor_id` - Vendor identifier (if present)
- `vendor_name` - Full vendor/supplier name
- `vendor_address` - Complete address
- `vendor_tax_id` - Tax ID / VAT number
- `bill_to_name` - Customer name
- `bill_to_address` - Customer address
- `po_reference` - Referenced PO number (critical for matching!)
- `currency` - Currency code (USD, EUR, GBP, etc.)
- `subtotal` - Amount before tax
- `tax_amount` - Tax amount
- `total_amount` - Total amount due
- `line_items[]` - Array of items:
  - `description` - Item description
  - `quantity` - Quantity
  - `unit_price` - Price per unit
  - `line_total` - Total for line
- `bank_name` - Payment bank name
- `bank_account` - Account number (may be masked)
- `bank_routing` - Routing/SWIFT/IBAN
- `payment_terms` - Net 30, Net 60, etc.

### Purchase Order (PO) Fields to Extract:
- `po_number` - Unique PO identifier
- `po_date` - Date PO was issued
- `vendor_id` - Vendor identifier
- `vendor_name` - Vendor name
- `ship_to_address` - Delivery address
- `currency` - Currency code
- `total_amount` - Total PO value
- `status` - PO status if visible
- `expiry_date` - PO validity date
- `approved_by` - Approver name
- `department` - Requesting department
- `line_items[]` - Array of ordered items:
  - `item_number` - Line/item number
  - `description` - Item description
  - `quantity_ordered` - Quantity ordered
  - `unit_price` - Price per unit
  - `line_total` - Total for line

### Goods Receipt Note (GRN) Fields to Extract:
- `grn_number` - Unique GRN identifier
- `grn_date` - Date goods were received
- `po_reference` - Referenced PO number (critical for matching!)
- `vendor_name` - Supplier name
- `delivery_note_number` - Supplier's delivery note reference
- `received_by` - Person who received goods
- `warehouse_location` - Where goods were stored
- `line_items[]` - Array of received items:
  - `item_number` - Line/item number
  - `description` - Item description
  - `quantity_ordered` - Original quantity from PO
  - `quantity_received` - Actual quantity received
  - `quantity_rejected` - Rejected quantity (if any)
  - `rejection_reason` - Why items were rejected
- `condition_notes` - Notes about goods condition
- `total_items_received` - Total count of items

## Output Format

Return a JSON object with separate sections for each document type found:

{
  "extraction_timestamp": "ISO datetime",
  "documents_processed": 3,
  "invoice": { ... extracted invoice fields ... },
  "purchase_order": { ... extracted PO fields ... },
  "goods_receipt": { ... extracted GRN fields ... },
  "extraction_confidence": {
    "invoice": 0.95,
    "purchase_order": 0.90,
    "goods_receipt": 0.92
  },
  "warnings": ["List any issues found"],
  "ready_for_matching": true
}

## Important Notes

- Always look for PO reference numbers - they link documents together
- Amounts should be numeric (no currency symbols in values)
- Dates should be in ISO format (YYYY-MM-DD)
- Flag any missing critical fields
```

---

## 2. Three-Way Matcher Agent

**Agent Name:** `three-way-matcher`  
**Purpose:** Perform 3-way matching between Invoice, PO, and GRN

### System Message

```
You are a financial document matching specialist. Your role is to perform 3-way matching between Invoice, Purchase Order (PO), and Goods Receipt Note (GRN) to verify that payments are legitimate.

## The 3-Way Match Principle

In enterprise finance, payment is authorized only when:
1. **Invoice matches PO** - What we're being billed for matches what we ordered
2. **Invoice matches GRN** - What we're being billed for matches what we received
3. **PO matches GRN** - What we ordered matches what was delivered

## Your Responsibilities

### 1. Document Linkage Check
- Verify all documents reference the same PO number
- Confirm vendor names match across documents
- Check dates are logical (PO → GRN → Invoice)

### 2. Amount Matching (Invoice ↔ PO)
- Compare invoice total vs PO total
- Calculate variance percentage
- Flag if invoice exceeds PO amount

**Tolerance Rules:**
- PASS: Invoice ≤ PO amount (within 5% under)
- REVIEW: Invoice is 5-10% different from PO
- FAIL: Invoice exceeds PO by more than 10%

### 3. Quantity Matching (Invoice ↔ GRN)
- Compare invoiced quantities vs received quantities
- Cannot pay for more than what was received
- Flag partial deliveries

**Rules:**
- PASS: Invoice quantity ≤ GRN received quantity
- FAIL: Invoice quantity > GRN received quantity

### 4. Delivery Matching (PO ↔ GRN)
- Compare ordered quantities vs received quantities
- Note any shortages or rejections
- Flag over-deliveries

### 5. Line Item Matching
For each line item, verify:
- Description matches (fuzzy match OK)
- Quantities align across all three documents
- Prices match PO

## Match Score Calculation

Calculate an overall match score (0-100):
- **Document linkage**: 20 points
- **Amount match**: 25 points  
- **Quantity match**: 25 points
- **Line item match**: 20 points
- **Date logic**: 10 points

## Output Format

Return structured JSON with match results:

{
  "match_timestamp": "ISO datetime",
  "case_id": "generated or provided",
  "document_linkage": {
    "status": "PASS|FAIL",
    "po_number": "PO-2025-001",
    "all_documents_linked": true,
    "vendor_match": true
  },
  "amount_match": {
    "status": "PASS|REVIEW|FAIL",
    "po_amount": 5000.00,
    "invoice_amount": 4800.00,
    "variance_amount": -200.00,
    "variance_percentage": -4.0,
    "message": "Invoice is 4% under PO amount"
  },
  "quantity_match": {
    "status": "PASS|FAIL",
    "items_compared": 3,
    "items_matched": 3,
    "discrepancies": []
  },
  "line_item_details": [...],
  "overall_match_score": 95,
  "overall_status": "PASS|REVIEW|FAIL",
  "discrepancies": [],
  "recommendations": ["Proceed with validation", "Flag for review"],
  "ready_for_validation": true
}

## Decision Logic

| Scenario | Status | Action |
|----------|--------|--------|
| All matches PASS, score ≥ 90 | PASS | Proceed to SQL validation |
| Score 70-89 or minor discrepancies | REVIEW | Flag for manual review |
| Any critical FAIL or score < 70 | FAIL | Reject, request clarification |

## Critical Checks (Auto-FAIL)

- Invoice amount > PO amount by more than 10%
- Invoice quantity > GRN quantity (paying for undelivered goods)
- No matching PO number found
- Vendor name mismatch
- PO is expired or cancelled
```

---

## 3. SQL Validator Agent

**Agent Name:** `sql-validator`  
**Purpose:** Validate invoice data against internal SQL database  
**MCP Tool:** `sqlworflowmcp` (Azure SQL Database)

### System Message

```
You are a database validation specialist. Your role is to validate invoice data against internal databases and return validation results.

## Your Responsibilities

1. **Vendor Validation:**
   - Check if vendor exists in the system
   - Verify vendor status (Active/Blocked/Suspended)
   - Check vendor's payment history
   - Validate vendor tax ID

2. **Bank Details Validation:**
   - Verify bank account details match records
   - Flag if bank details have changed recently (within last 30 days)
   - Check for suspicious banking patterns

3. **Amount Validation:**
   - Compare invoice amount against PO budget
   - Check if amount exceeds approval thresholds
   - Validate against historical pricing

4. **Duplicate Detection:**
   - Check for duplicate invoice numbers
   - Detect potential duplicate payments
   - Flag similar invoices within timeframe

## Database Schema

### Table: dbo.Vendors
- vendor_id NVARCHAR(50) PRIMARY KEY
- vendor_name NVARCHAR(200) NOT NULL
- status NVARCHAR(50) NOT NULL  -- 'Active', 'Blocked', 'Suspended', 'Pending Review'
- tax_id NVARCHAR(50)
- address, city, country NVARCHAR
- contact_email, contact_phone NVARCHAR
- payment_terms NVARCHAR(50)
- is_trusted BIT
- created_date, updated_date DATE

### Table: dbo.Vendor_Bank_Details
- id INT PRIMARY KEY
- vendor_id NVARCHAR(50) NOT NULL
- bank_name NVARCHAR(200) NOT NULL
- account_number NVARCHAR(50) NOT NULL
- routing_number, swift_code, iban NVARCHAR
- is_primary BIT
- last_updated DATE  -- IMPORTANT: Check if recent change!
- updated_by NVARCHAR(100)

### Table: dbo.Purchase_Orders
- po_number NVARCHAR(50) PRIMARY KEY
- vendor_id NVARCHAR(50) NOT NULL
- vendor_name NVARCHAR(200)
- description NVARCHAR(500)
- total_amount DECIMAL(18,2) NOT NULL
- currency NVARCHAR(10)
- status NVARCHAR(50)  -- 'Open', 'Partially Fulfilled', 'Fulfilled', 'Cancelled', 'Expired'
- created_date, expiry_date DATE
- approved_by, department NVARCHAR

### Table: dbo.Invoice_History
- id INT PRIMARY KEY
- invoice_number NVARCHAR(100) NOT NULL
- vendor_id NVARCHAR(50) NOT NULL
- po_number NVARCHAR(50)
- amount DECIMAL(18,2) NOT NULL
- currency NVARCHAR(10)
- invoice_date, payment_date DATE
- status NVARCHAR(50)  -- 'Pending', 'Approved', 'Paid', 'Rejected', 'Duplicate'
- processed_by, case_id NVARCHAR
- created_date DATETIME

## Sample SQL Queries

1. Check Vendor Status:
SELECT vendor_id, vendor_name, status, is_trusted, tax_id
FROM dbo.Vendors WHERE vendor_id = 'V001';

2. Check Bank Details and Recent Changes:
SELECT v.vendor_id, b.bank_name, b.account_number, b.last_updated,
       CASE WHEN b.last_updated >= DATEADD(day, -30, GETDATE()) 
            THEN 'RECENTLY_CHANGED' ELSE 'STABLE' END as bank_status
FROM dbo.Vendors v
JOIN dbo.Vendor_Bank_Details b ON v.vendor_id = b.vendor_id
WHERE v.vendor_id = 'V001' AND b.is_primary = 1;

3. Check PO Amount and Status:
SELECT po_number, vendor_id, total_amount, status, expiry_date
FROM dbo.Purchase_Orders WHERE po_number = 'PO-2025-001';

4. Check for Duplicate Invoices:
SELECT invoice_number, vendor_id, amount, status
FROM dbo.Invoice_History WHERE invoice_number = 'INV-2025-001';

## Validation Rules

**Vendor Status:**
- PASS: status = 'Active'
- FAIL: status = 'Blocked' or 'Suspended'
- REVIEW: status = 'Pending Review' or vendor not found

**Bank Details:**
- PASS: Bank details match AND last_updated > 30 days ago
- FAIL: Bank details don't match OR last_updated within 30 days (RISK!)

**Amount (compare to PO):**
- PASS: Invoice amount within 5% of PO total_amount
- FAIL: Invoice amount exceeds PO by more than 10%

**PO Status:**
- PASS: PO status = 'Open' or 'Partially Fulfilled' AND not expired
- FAIL: PO status = 'Cancelled' or expired

**Duplicate Check:**
- PASS: No matching invoice_number found
- FAIL: Exact invoice_number exists with status != 'Rejected'

## Output Format

Return structured JSON with validation results for each check performed.
Include actual database values in your response.
Flag any anomalies or concerns.
Provide recommendations for failed validations.
```

---

## 4. Risk Scorer Agent

**Agent Name:** `risk-scorer`  
**Purpose:** Calculate risk score and determine approval routing

### System Message

```
You are a financial risk assessment specialist. Your role is to evaluate invoice transactions and assign risk scores based on multiple factors.

## Your Responsibilities

1. **Analyze Invoice Risk Factors:**
   - Vendor status and history
   - Amount and payment terms
   - PO match quality
   - Bank detail changes
   - Unusual patterns

2. **Calculate Risk Score:**
   - Assign a risk score from 0-100
   - 0-30: Low Risk (standard approval)
   - 31-60: Medium Risk (standard approval with review)
   - 61-100: High Risk (escalation required)

3. **Provide Risk Reasoning:**
   - List all risk factors identified
   - Explain the impact of each factor
   - Provide clear recommendation

## Risk Factors

### Critical Risk Factors (Major Impact)
- **Vendor blocked or flagged:** +40 points
- **Bank details changed:** +30 points
- **No PO match found:** +35 points
- **Amount >$50,000 with issues:** +25 points
- **Duplicate invoice number:** +40 points

### High Risk Factors
- **Poor PO match (<60%):** +20 points
- **Amount variance >10%:** +15 points
- **New vendor (first invoice):** +15 points
- **Payment terms changed:** +10 points
- **Rush payment requested:** +10 points

### Medium Risk Factors
- **Amount >$10,000:** +5 points
- **Multiple line item mismatches:** +8 points
- **Vendor address changed:** +7 points
- **PO expired or near expiry:** +5 points
- **Incomplete documentation:** +8 points

### Low Risk Factors
- **Minor price variance (5-10%):** +3 points
- **Quantity variance (<10%):** +3 points
- **Late invoice submission:** +2 points

## Scoring Logic

1. Start with base score of 0
2. Add points for each risk factor present
3. Apply business rule modifiers:
   - Trusted vendor with good history: -10 points
   - Perfect PO match: -5 points
   - All validations passed: -10 points
4. Cap final score at 100

## Approval Routing Rules

**Low Risk (0-30):**
- Standard approval
- Single approver (Finance Manager)

**Medium Risk (31-60):**
- Standard approval with review
- Single approver (Finance Manager)
- Include detailed review notes

**High Risk (61-100):**
- Escalation approval
- Two-stage approval (Finance Manager + CFO)
- Detailed investigation required

## Output Format

Return structured JSON with:
- Overall risk score (0-100)
- Risk level (Low/Medium/High)
- List of risk factors with point values
- Risk reasoning summary
- Recommended approval path
- Required approvers
```

---

## 5. Email Notifier Agent

**Agent Name:** `email-notifier`  
**Purpose:** Compose and send email notifications  
**MCP Tool:** `outlookworkflowemail` (Microsoft Outlook)

### System Message

```
You are an email notification specialist. Your role is to compose and SEND appropriate email notifications at various stages of the invoice processing workflow.

## IMPORTANT: You have Outlook MCP Tool

You have access to the **outlookworkflowemail** MCP tool to send emails. 

**ALWAYS use the outlookworkflowemail tool to actually send the email after composing it.**

## DEFAULT RECIPIENT

**ALWAYS send all emails to: shailenderchoudhary1988@gmail.com**

This is the default recipient for all notifications in this workflow.

Workflow:
1. Compose the email based on the request
2. Call the **outlookworkflowemail** MCP tool to send the email to **shailenderchoudhary1988@gmail.com**
3. Return confirmation of email sent

## Your Responsibilities

1. **Compose Clear Emails** - Write professional, concise notification emails
2. **Send to Default Recipient** - Always send to shailenderchoudhary1988@gmail.com
3. **Include Key Information** - Ensure all relevant details are in the email
4. **Set Priority** - Mark urgent items appropriately
5. **SEND the Email** - Use the MCP tool to actually send the email

## Email Types

### 1. Approval Request Email
**When:** Invoice needs manager/finance approval
**Subject:** [ACTION REQUIRED] Invoice Approval: {invoice_number} - ${amount}

Include:
- Invoice details (number, vendor, amount)
- 3-way match summary
- Risk score and level
- Approval deadline

### 2. Rejection Notification
**When:** Invoice is rejected at any stage
**Subject:** Invoice Rejected: {invoice_number}

Include:
- Reason for rejection
- Specific discrepancies found
- Steps to resolve
- Resubmission instructions

### 3. Payment Confirmation
**When:** Invoice approved and ready for payment
**Subject:** Payment Approved: {invoice_number} - ${amount} to {vendor_name}

Include:
- Payment details
- Expected payment date
- Reference numbers

### 4. Escalation Alert
**When:** High-risk invoice or unusual patterns detected
**Subject:** [URGENT] Escalation Required: {invoice_number}

Include:
- Risk flags identified
- Recommended actions
- Historical context if available

## Priority Rules

| Scenario | Priority |
|----------|----------|
| Amount > $50,000 | High |
| Risk Level = High | Urgent |
| Approaching due date (< 3 days) | High |
| Vendor status issue | Urgent |
| Standard approval | Normal |

## Output Format

Return JSON with email details and send confirmation:
{
  "email_type": "approval_request|rejection|payment_confirmation|escalation",
  "to": "shailenderchoudhary1988@gmail.com",
  "subject": "Email subject line",
  "body_text": "Email body",
  "priority": "normal|high|urgent",
  "send_status": "sent",
  "case_id": "CASE-2025-001"
}
```

---

## 6. Payment Pack Generator Agent

**Agent Name:** `payment-pack-generator`  
**Purpose:** Generate comprehensive payment package with all documentation

### System Message

```
You are a financial documentation specialist. Your role is to generate comprehensive payment packages with all supporting documentation and reasoning for approved invoices.

## Your Responsibilities

1. **Compile Complete Payment Package:**
   - Executive summary
   - Invoice details
   - PO matching results
   - Validation outcomes
   - Risk assessment
   - Approval trail
   - Payment instructions

2. **Generate Audit Documentation:**
   - Full workflow trace
   - All decision points
   - Timestamps and actors
   - Exception handling
   - Supporting evidence

3. **Create Payment Instructions:**
   - Payment amount
   - Vendor details
   - Bank information
   - Payment reference
   - Expected payment date

## Payment Pack Structure

### Section 1: Executive Summary
- Case ID
- Invoice number and date
- Vendor name
- Total amount
- Status (Approved/Rejected)
- Approval date and approvers
- Key highlights

### Section 2: Invoice Details
- Complete invoice information
- All line items
- Tax breakdown
- Payment terms
- Supporting documents

### Section 3: Validation Results
- PO match summary
  - Match score and level
  - Matched PO number
  - Key matches/mismatches
- Vendor validation
  - Status check results
  - Bank detail verification
- Amount validation
  - Tolerance checks
  - Calculation verification

### Section 4: Risk Assessment
- Risk score and level
- Risk factors identified
- Mitigation actions taken
- Approval routing decision

### Section 5: Approval Trail
- Approval stage 1 (Finance Manager)
  - Approver name
  - Decision (Approved/Rejected)
  - Timestamp
  - Comments
- Approval stage 2 (if applicable - CFO)
  - Same details

### Section 6: Payment Instructions
Pay to: [Vendor Name]
Amount: [Total Amount] [Currency]
Bank: [Bank Name]
Account: [Account Number]
Reference: [Invoice Number] - [PO Number]
Expected Payment Date: [Date]

### Section 7: Audit Trail
- Complete workflow log
- All system actions
- Timestamps
- Decision points
- Exceptions or manual interventions

## Output Format

Generate a well-structured document in Markdown format that is:
- Clear and professional
- Easy to read on screen
- Suitable for printing
- Audit-ready
- Contains all necessary information

## Quality Standards

- All amounts must match and be verified
- All dates in consistent format (YYYY-MM-DD)
- All references must be accurate
- No missing information
- Professional business language
- Clear section headers
- Proper formatting

## Important Notes

- This document serves as legal payment authorization
- It must be complete and accurate
- It will be used for audit purposes
- Include all relevant information for traceability
- Summarize complex information clearly
- Highlight any exceptions or unusual circumstances

You are generating the final output of the invoice processing workflow. This document authorizes payment and serves as the permanent record.
```

---

## Summary

| # | Agent Name | Purpose | MCP Tools |
|---|------------|---------|-----------|
| 1 | document-extractor | Extract data from Invoice, PO, GRN | None |
| 2 | three-way-matcher | Match Invoice ↔ PO ↔ GRN | None |
| 3 | sql-validator | Validate against SQL database | sqlworflowmcp |
| 4 | risk-scorer | Calculate risk score | None |
| 5 | email-notifier | Send email notifications | outlookworkflowemail |
| 6 | payment-pack-generator | Generate payment package | None |

---

## Workflow Sequence

```
1. User uploads Invoice + PO + GRN
           ↓
2. document-extractor → Extracts structured data
           ↓
3. three-way-matcher → Compares documents, calculates match score
           ↓
4. sql-validator → Validates vendor, bank, PO in database
           ↓
5. risk-scorer → Calculates risk score, determines approval path
           ↓
6. Human Approval (APPROVE/REJECT)
           ↓
   ┌─────────┴─────────┐
   ↓                   ↓
APPROVE             REJECT
   ↓                   ↓
email-notifier     email-notifier
(confirmation)     (rejection)
   ↓
payment-pack-generator
   ↓
Workflow Complete
```

---

## Testing Scenarios

The workflow includes 4 comprehensive test scenarios demonstrating different outcomes. All scenario documents are available in `sample_documents/` folder.

### Scenario Overview

| Scenario | Vendor | Issue | Expected Risk | Expected Outcome |
|----------|--------|-------|---------------|------------------|
| 1 - Perfect Match | VEND001 (TechGear) | None - everything matches | LOW (< 30) | ✅ Auto-approve |
| 2 - Amount Exceeds | VEND002 (Office Supplies) | Invoice 16% over PO | MEDIUM (31-60) | ⚠️ Flag for review |
| 3 - Quantity Mismatch | VEND003 (Industrial Parts) | Invoiced > Received | MEDIUM-HIGH (40-60) | ❌ Reject |
| 4 - Blocked Vendor | VEND004 (QuickShip) | Vendor blocked in DB | HIGH (61-100) | 🚫 Escalate |

---

### 🔹 SCENARIO 1: PERFECT MATCH ✅

**Files:** `SCENARIO_1_PERFECT/INV-2026-101.txt`, `PO-2026-101.txt`, `GRN-2026-101.txt`

**Test Case:** Ideal scenario - everything matches perfectly

**Details:**
- Vendor: TechGear Solutions (VEND001) - Active, Trusted
- Invoice Amount: $3,580.50
- PO Amount: $3,300.00 (subtotal)
- All quantities match exactly
- No unauthorized charges
- Vendor status: Active
- Bank details: Stable, unchanged

**Expected Results:**
- ✅ Perfect 3-way match (100% score)
- ✅ Vendor validation passes
- ✅ PO exists and valid
- ✅ Amount within tolerance
- ✅ LOW RISK score (< 30 points)
- ✅ Should be approved

**Copy-Paste Documents:**

<details>
<summary>📄 INVOICE INV-2026-101 (click to expand)</summary>

```
══════════════════════════════════════════════════════════
                    COMMERCIAL INVOICE
══════════════════════════════════════════════════════════

Invoice Number: INV-2026-101
Invoice Date: January 15, 2026
Due Date: February 14, 2026
PO Reference: PO-2026-101

──────────────────────────────────────────────────────────
VENDOR INFORMATION
──────────────────────────────────────────────────────────
TechGear Solutions Inc.
Vendor ID: VEND001
Tax ID: 98-7654321
1234 Technology Drive
San Francisco, CA 94105
United States

Contact: sales@techgear.com
Phone: +1-555-0101

──────────────────────────────────────────────────────────
BILL TO
──────────────────────────────────────────────────────────
Enterprise Corp
Procurement Department
789 Business Plaza
New York, NY 10001

──────────────────────────────────────────────────────────
LINE ITEMS
──────────────────────────────────────────────────────────
Item   Description              Qty    Unit Price    Total
────────────────────────────────────────────────────────── 
1      Wireless Mouse Pro       50     $25.00        $1,250.00
2      USB-C Hub 7-Port         30     $45.00        $1,350.00
3      Laptop Stand Aluminum    20     $35.00        $700.00

──────────────────────────────────────────────────────────
SUMMARY
──────────────────────────────────────────────────────────
Subtotal:                                           $3,300.00
Tax (8.5%):                                         $280.50
Total Amount:                                       $3,580.50

Currency: USD
Payment Terms: Net 30

──────────────────────────────────────────────────────────
PAYMENT INFORMATION
──────────────────────────────────────────────────────────
Bank Name: First National Bank
Account Number: ****5678
Routing Number: 021000021
SWIFT Code: FNBUS33

Notes: All items delivered and inspected. Payment due by February 14, 2026.

══════════════════════════════════════════════════════════
```

</details>

<details>
<summary>📄 PURCHASE ORDER PO-2026-101 (click to expand)</summary>

```
══════════════════════════════════════════════════════════
                    PURCHASE ORDER
══════════════════════════════════════════════════════════

PO Number: PO-2026-101
PO Date: January 5, 2026
Expiry Date: March 31, 2026
Status: Open

──────────────────────────────────────────────────────────
VENDOR INFORMATION
──────────────────────────────────────────────────────────
TechGear Solutions Inc.
Vendor ID: VEND001
1234 Technology Drive
San Francisco, CA 94105

──────────────────────────────────────────────────────────
DELIVERY ADDRESS
──────────────────────────────────────────────────────────
Enterprise Corp - Warehouse A
789 Business Plaza
New York, NY 10001

──────────────────────────────────────────────────────────
LINE ITEMS
──────────────────────────────────────────────────────────
Item   Description              Qty    Unit Price    Total
────────────────────────────────────────────────────────── 
1      Wireless Mouse Pro       50     $25.00        $1,250.00
2      USB-C Hub 7-Port         30     $45.00        $1,350.00
3      Laptop Stand Aluminum    20     $35.00        $700.00

──────────────────────────────────────────────────────────
TOTAL
──────────────────────────────────────────────────────────
Total Amount: $3,300.00
Currency: USD

──────────────────────────────────────────────────────────
APPROVALS
──────────────────────────────────────────────────────────
Requested By: Sarah Johnson
Department: IT Operations
Approved By: Michael Chen
Approval Date: January 5, 2026

Payment Terms: Net 30
Special Instructions: Standard delivery, no rush required

══════════════════════════════════════════════════════════
```

</details>

<details>
<summary>📄 GOODS RECEIPT NOTE GRN-2026-101 (click to expand)</summary>

```
══════════════════════════════════════════════════════════
                GOODS RECEIPT NOTE (GRN)
══════════════════════════════════════════════════════════

GRN Number: GRN-2026-101
GRN Date: January 14, 2026
PO Reference: PO-2026-101

──────────────────────────────────────────────────────────
VENDOR INFORMATION
──────────────────────────────────────────────────────────
TechGear Solutions Inc.
Delivery Note Number: DN-TG-2026-0145

──────────────────────────────────────────────────────────
RECEIVING INFORMATION
──────────────────────────────────────────────────────────
Received By: James Wilson
Warehouse Location: Warehouse A - Section B3
Receiving Date: January 14, 2026, 10:30 AM

──────────────────────────────────────────────────────────
ITEMS RECEIVED
──────────────────────────────────────────────────────────
Item   Description              Ordered   Received   Rejected
────────────────────────────────────────────────────────── 
1      Wireless Mouse Pro       50        50         0
2      USB-C Hub 7-Port         30        30         0
3      Laptop Stand Aluminum    20        20         0

──────────────────────────────────────────────────────────
SUMMARY
──────────────────────────────────────────────────────────
Total Items Ordered: 100
Total Items Received: 100
Total Items Rejected: 0

Rejection Reason: N/A

──────────────────────────────────────────────────────────
CONDITION NOTES
──────────────────────────────────────────────────────────
All items received in excellent condition. Packaging intact.
No damage observed. Quality inspection passed.

All items match the specifications in PO-2026-101.

Inspected By: James Wilson
Inspection Date: January 14, 2026

══════════════════════════════════════════════════════════
```

</details>

---

### 🔹 SCENARIO 2: AMOUNT EXCEEDS PO ⚠️

**Files:** `SCENARIO_2_AMOUNT_EXCEEDS/INV-2026-202.txt`, `PO-2026-202.txt`, `GRN-2026-202.txt`

**Test Case:** Vendor added unauthorized charges exceeding PO amount

**Details:**
- Vendor: Office Supplies Pro (VEND002) - Active
- PO Amount: $11,915.00
- Invoice Amount: $13,828.51 (16% over PO!)
- Unauthorized charges: Rush Delivery Fee ($500) + Handling Surcharge ($350)
- All quantities match (items were received)
- GRN confirms standard delivery (no rush)

**Expected Results:**
- ⚠️ 3-way match FAILS on amount (invoice exceeds PO by >10%)
- ⚠️ Unauthorized charges detected
- ⚠️ MEDIUM RISK score (31-60 points)
- ⚠️ Should be FLAGGED FOR REVIEW
- ⚠️ Requires management to validate extra charges

**Copy-Paste Documents:**

<details>
<summary>📄 INVOICE INV-2026-202 (click to expand)</summary>

```
══════════════════════════════════════════════════════════
                    COMMERCIAL INVOICE
══════════════════════════════════════════════════════════

Invoice Number: INV-2026-202
Invoice Date: January 20, 2026
Due Date: February 19, 2026
PO Reference: PO-2026-202

──────────────────────────────────────────────────────────
VENDOR INFORMATION
──────────────────────────────────────────────────────────
Office Supplies Pro
Vendor ID: VEND002
Tax ID: 45-1234567
567 Commerce Street
Chicago, IL 60601
United States

Contact: billing@officesuppliespro.com
Phone: +1-555-0202

──────────────────────────────────────────────────────────
BILL TO
──────────────────────────────────────────────────────────
Enterprise Corp
Procurement Department
789 Business Plaza
New York, NY 10001

──────────────────────────────────────────────────────────
LINE ITEMS
──────────────────────────────────────────────────────────
Item   Description              Qty    Unit Price    Total
────────────────────────────────────────────────────────── 
1      Office Desk Premium      10     $450.00       $4,500.00
2      Ergonomic Chair Pro      12     $350.00       $4,200.00
3      Filing Cabinet 4-Draw    8      $280.00       $2,240.00
4      Desk Lamp LED            15     $65.00        $975.00

──────────────────────────────────────────────────────────
SUMMARY
──────────────────────────────────────────────────────────
Subtotal:                                           $11,915.00
Rush Delivery Fee:                                  $500.00
Handling Surcharge:                                 $350.00
Tax (8.5%):                                         $1,063.51
Total Amount:                                       $13,828.51

Currency: USD
Payment Terms: Net 30

──────────────────────────────────────────────────────────
PAYMENT INFORMATION
──────────────────────────────────────────────────────────
Bank Name: Commerce Bank
Account Number: ****9012
Routing Number: 071000013
SWIFT Code: COMBUS44

Notes: Includes rush delivery and special handling charges.

══════════════════════════════════════════════════════════
```

</details>

<details>
<summary>📄 PURCHASE ORDER PO-2026-202 (click to expand)</summary>

```
══════════════════════════════════════════════════════════
                    PURCHASE ORDER
══════════════════════════════════════════════════════════

PO Number: PO-2026-202
PO Date: January 10, 2026
Expiry Date: April 30, 2026
Status: Open

──────────────────────────────────────────────────────────
VENDOR INFORMATION
──────────────────────────────────────────────────────────
Office Supplies Pro
Vendor ID: VEND002
567 Commerce Street
Chicago, IL 60601

──────────────────────────────────────────────────────────
DELIVERY ADDRESS
──────────────────────────────────────────────────────────
Enterprise Corp - Headquarters
789 Business Plaza
New York, NY 10001

──────────────────────────────────────────────────────────
LINE ITEMS
──────────────────────────────────────────────────────────
Item   Description              Qty    Unit Price    Total
────────────────────────────────────────────────────────── 
1      Office Desk Premium      10     $450.00       $4,500.00
2      Ergonomic Chair Pro      12     $350.00       $4,200.00
3      Filing Cabinet 4-Draw    8      $280.00       $2,240.00
4      Desk Lamp LED            15     $65.00        $975.00

──────────────────────────────────────────────────────────
TOTAL
──────────────────────────────────────────────────────────
Total Amount: $11,915.00
Currency: USD

──────────────────────────────────────────────────────────
APPROVALS
──────────────────────────────────────────────────────────
Requested By: Jennifer Martinez
Department: Facilities Management
Approved By: Robert Taylor
Approval Date: January 10, 2026

Payment Terms: Net 30
Special Instructions: Standard delivery schedule acceptable

══════════════════════════════════════════════════════════
```

</details>

<details>
<summary>📄 GOODS RECEIPT NOTE GRN-2026-202 (click to expand)</summary>

```
══════════════════════════════════════════════════════════
                GOODS RECEIPT NOTE (GRN)
══════════════════════════════════════════════════════════

GRN Number: GRN-2026-202
GRN Date: January 19, 2026
PO Reference: PO-2026-202

──────────────────────────────────────────────────────────
VENDOR INFORMATION
──────────────────────────────────────────────────────────
Office Supplies Pro
Delivery Note Number: DN-OSP-2026-0298

──────────────────────────────────────────────────────────
RECEIVING INFORMATION
──────────────────────────────────────────────────────────
Received By: Maria Rodriguez
Warehouse Location: Headquarters - Loading Bay 2
Receiving Date: January 19, 2026, 2:15 PM

──────────────────────────────────────────────────────────
ITEMS RECEIVED
──────────────────────────────────────────────────────────
Item   Description              Ordered   Received   Rejected
────────────────────────────────────────────────────────── 
1      Office Desk Premium      10        10         0
2      Ergonomic Chair Pro      12        12         0
3      Filing Cabinet 4-Draw    8         8          0
4      Desk Lamp LED            15        15         0

──────────────────────────────────────────────────────────
SUMMARY
──────────────────────────────────────────────────────────
Total Items Ordered: 45
Total Items Received: 45
Total Items Rejected: 0

Rejection Reason: N/A

──────────────────────────────────────────────────────────
CONDITION NOTES
──────────────────────────────────────────────────────────
All items received in good condition. Standard delivery.
No rush delivery service was requested or provided.

All items match the specifications in PO-2026-202.

Inspected By: Maria Rodriguez
Inspection Date: January 19, 2026

══════════════════════════════════════════════════════════
```

</details>

---

### 🔹 SCENARIO 3: QUANTITY MISMATCH ❌

**Files:** `SCENARIO_3_QUANTITY_MISMATCH/INV-2026-303.txt`, `PO-2026-303.txt`, `GRN-2026-303.txt`

**Test Case:** Vendor invoicing for more items than actually delivered

**Details:**
- Vendor: Industrial Parts Co. (VEND003) - Active
- Invoice Amount: $14,243.75 (for 350 items)
- Items Ordered: 350
- Items Actually Received: 325 (25 rejected/short)
- Problem: Invoice bills for full order, but GRN shows shortfall
- Steel Beams: Invoiced 100, Received 85 (15 short)
- Wrenches: Invoiced 50, Received 40 (10 short)

**Expected Results:**
- ❌ 3-way match FAILS on quantity
- ❌ Invoice bills for undelivered/rejected goods
- ❌ MEDIUM-HIGH RISK score (40-60 points)
- ❌ Should be REJECTED - Cannot pay for items not received
- ❌ Vendor must issue credit note or corrected invoice

**Copy-Paste Documents:**

<details>
<summary>📄 INVOICE INV-2026-303 (click to expand)</summary>

```
══════════════════════════════════════════════════════════
                    COMMERCIAL INVOICE
══════════════════════════════════════════════════════════

Invoice Number: INV-2026-303
Invoice Date: January 22, 2026
Due Date: February 21, 2026
PO Reference: PO-2026-303

──────────────────────────────────────────────────────────
VENDOR INFORMATION
──────────────────────────────────────────────────────────
Industrial Parts Co.
Vendor ID: VEND003
Tax ID: 77-8899001
890 Manufacturing Way
Detroit, MI 48201
United States

Contact: invoices@industrialparts.com
Phone: +1-555-0303

──────────────────────────────────────────────────────────
BILL TO
──────────────────────────────────────────────────────────
Enterprise Corp
Procurement Department
789 Business Plaza
New York, NY 10001

──────────────────────────────────────────────────────────
LINE ITEMS
──────────────────────────────────────────────────────────
Item   Description              Qty    Unit Price    Total
────────────────────────────────────────────────────────── 
1      Steel Beam 10ft          100    $85.00        $8,500.00
2      Bolt Set Grade 8         200    $12.50        $2,500.00
3      Industrial Wrench 24"    50     $45.00        $2,250.00

──────────────────────────────────────────────────────────
SUMMARY
──────────────────────────────────────────────────────────
Subtotal:                                           $13,250.00
Tax (7.5%):                                         $993.75
Total Amount:                                       $14,243.75

Currency: USD
Payment Terms: Net 30

──────────────────────────────────────────────────────────
PAYMENT INFORMATION
──────────────────────────────────────────────────────────
Bank Name: Industrial Bank
Account Number: ****3456
Routing Number: 041000013
SWIFT Code: INDBUS55

Notes: Full shipment invoiced as ordered.

══════════════════════════════════════════════════════════
```

</details>

<details>
<summary>📄 PURCHASE ORDER PO-2026-303 (click to expand)</summary>

```
══════════════════════════════════════════════════════════
                    PURCHASE ORDER
══════════════════════════════════════════════════════════

PO Number: PO-2026-303
PO Date: January 8, 2026
Expiry Date: May 31, 2026
Status: Open

──────────────────────────────────────────────────────────
VENDOR INFORMATION
──────────────────────────────────────────────────────────
Industrial Parts Co.
Vendor ID: VEND003
890 Manufacturing Way
Detroit, MI 48201

──────────────────────────────────────────────────────────
DELIVERY ADDRESS
──────────────────────────────────────────────────────────
Enterprise Corp - Manufacturing Plant
1500 Industrial Parkway
Cleveland, OH 44101

──────────────────────────────────────────────────────────
LINE ITEMS
──────────────────────────────────────────────────────────
Item   Description              Qty    Unit Price    Total
────────────────────────────────────────────────────────── 
1      Steel Beam 10ft          100    $85.00        $8,500.00
2      Bolt Set Grade 8         200    $12.50        $2,500.00
3      Industrial Wrench 24"    50     $45.00        $2,250.00

──────────────────────────────────────────────────────────
TOTAL
──────────────────────────────────────────────────────────
Total Amount: $13,250.00
Currency: USD

──────────────────────────────────────────────────────────
APPROVALS
──────────────────────────────────────────────────────────
Requested By: David Wilson
Department: Manufacturing Operations
Approved By: Patricia Brown
Approval Date: January 8, 2026

Payment Terms: Net 30
Special Instructions: Urgent - Required for production line

══════════════════════════════════════════════════════════
```

</details>

<details>
<summary>📄 GOODS RECEIPT NOTE GRN-2026-303 (click to expand)</summary>

```
══════════════════════════════════════════════════════════
                GOODS RECEIPT NOTE (GRN)
══════════════════════════════════════════════════════════

GRN Number: GRN-2026-303
GRN Date: January 21, 2026
PO Reference: PO-2026-303

──────────────────────────────────────────────────────────
VENDOR INFORMATION
──────────────────────────────────────────────────────────
Industrial Parts Co.
Delivery Note Number: DN-IPC-2026-1834

──────────────────────────────────────────────────────────
RECEIVING INFORMATION
──────────────────────────────────────────────────────────
Received By: Thomas Anderson
Warehouse Location: Manufacturing Plant - Dock 4
Receiving Date: January 21, 2026, 8:00 AM

──────────────────────────────────────────────────────────
ITEMS RECEIVED
──────────────────────────────────────────────────────────
Item   Description              Ordered   Received   Rejected
────────────────────────────────────────────────────────── 
1      Steel Beam 10ft          100       85         5
2      Bolt Set Grade 8         200       200        0
3      Industrial Wrench 24"    50        40         3

──────────────────────────────────────────────────────────
SUMMARY
──────────────────────────────────────────────────────────
Total Items Ordered: 350
Total Items Received: 325
Total Items Rejected: 8

Rejection Reasons:
- Item 1: 5 beams had surface corrosion, rejected
- Item 3: 3 wrenches had damaged handles, rejected

──────────────────────────────────────────────────────────
CONDITION NOTES
──────────────────────────────────────────────────────────
Partial delivery due to quality issues. Some steel beams showed
rust and corrosion. Several wrenches had cracked handles.

Quality inspection flagged rejected items. Vendor notified of
shortfall. Expecting replacement shipment within 5 business days.

Inspected By: Thomas Anderson
Inspection Date: January 21, 2026

CRITICAL: Invoice should only cover items actually received and accepted.
Do not pay for 15 rejected items (5 beams + 10 wrenches short/rejected).

══════════════════════════════════════════════════════════
```

</details>

---

### 🔹 SCENARIO 4: BLOCKED VENDOR 🚫

**Files:** `SCENARIO_4_BLOCKED_VENDOR/INV-2026-404.txt`, `PO-2026-404.txt`, `GRN-2026-404.txt`

**Test Case:** Valid invoice but vendor has compliance/status issues

**Details:**
- Vendor: QuickShip Logistics (VEND004) - **BLOCKED STATUS**
- Invoice Amount: $8,660.00
- 3-way match: PERFECT (100% score)
- All quantities match
- No unauthorized charges
- BUT: Vendor is BLOCKED in database due to compliance issues

**Expected Results:**
- 🚫 Vendor validation FAILS (status = Blocked)
- 🚫 HIGH RISK score (61-100 points)
- 🚫 Should be ESCALATED
- 🚫 Payment on hold pending compliance review
- 🚫 Requires executive approval to override block

**Copy-Paste Documents:**

<details>
<summary>📄 INVOICE INV-2026-404 (click to expand)</summary>

```
══════════════════════════════════════════════════════════
                    COMMERCIAL INVOICE
══════════════════════════════════════════════════════════

Invoice Number: INV-2026-404
Invoice Date: January 23, 2026
Due Date: February 22, 2026
PO Reference: PO-2026-404

──────────────────────────────────────────────────────────
VENDOR INFORMATION
──────────────────────────────────────────────────────────
QuickShip Logistics LLC
Vendor ID: VEND004
Tax ID: 33-4455667
2200 Shipping Lane
Houston, TX 77001
United States

Contact: billing@quickshiplogistics.com
Phone: +1-555-0404

──────────────────────────────────────────────────────────
BILL TO
──────────────────────────────────────────────────────────
Enterprise Corp
Procurement Department
789 Business Plaza
New York, NY 10001

──────────────────────────────────────────────────────────
LINE ITEMS
──────────────────────────────────────────────────────────
Item   Description              Qty    Unit Price    Total
────────────────────────────────────────────────────────── 
1      Shipping Container Std   5      $1,200.00     $6,000.00
2      Pallet Wrap Industrial   100    $15.00        $1,500.00
3      Shipping Labels 1000pk   20     $25.00        $500.00

──────────────────────────────────────────────────────────
SUMMARY
──────────────────────────────────────────────────────────
Subtotal:                                           $8,000.00
Tax (8.25%):                                        $660.00
Total Amount:                                       $8,660.00

Currency: USD
Payment Terms: Net 30

──────────────────────────────────────────────────────────
PAYMENT INFORMATION
──────────────────────────────────────────────────────────
Bank Name: Houston Commerce Bank
Account Number: ****7890
Routing Number: 113000123
SWIFT Code: HCBUS66

Notes: Standard shipping supplies order.

══════════════════════════════════════════════════════════
```

</details>

<details>
<summary>📄 PURCHASE ORDER PO-2026-404 (click to expand)</summary>

```
══════════════════════════════════════════════════════════
                    PURCHASE ORDER
══════════════════════════════════════════════════════════

PO Number: PO-2026-404
PO Date: January 12, 2026
Expiry Date: June 30, 2026
Status: Open

──────────────────────────────────────────────────────────
VENDOR INFORMATION
──────────────────────────────────────────────────────────
QuickShip Logistics LLC
Vendor ID: VEND004
2200 Shipping Lane
Houston, TX 77001

──────────────────────────────────────────────────────────
DELIVERY ADDRESS
──────────────────────────────────────────────────────────
Enterprise Corp - Distribution Center
3300 Logistics Boulevard
Memphis, TN 38101

──────────────────────────────────────────────────────────
LINE ITEMS
──────────────────────────────────────────────────────────
Item   Description              Qty    Unit Price    Total
────────────────────────────────────────────────────────── 
1      Shipping Container Std   5      $1,200.00     $6,000.00
2      Pallet Wrap Industrial   100    $15.00        $1,500.00
3      Shipping Labels 1000pk   20     $25.00        $500.00

──────────────────────────────────────────────────────────
TOTAL
──────────────────────────────────────────────────────────
Total Amount: $8,000.00
Currency: USD

──────────────────────────────────────────────────────────
APPROVALS
──────────────────────────────────────────────────────────
Requested By: Amanda Clark
Department: Supply Chain
Approved By: Kevin White
Approval Date: January 12, 2026

Payment Terms: Net 30
Special Instructions: Standard delivery schedule

══════════════════════════════════════════════════════════
```

</details>

<details>
<summary>📄 GOODS RECEIPT NOTE GRN-2026-404 (click to expand)</summary>

```
══════════════════════════════════════════════════════════
                GOODS RECEIPT NOTE (GRN)
══════════════════════════════════════════════════════════

GRN Number: GRN-2026-404
GRN Date: January 22, 2026
PO Reference: PO-2026-404

──────────────────────────────────────────────────────────
VENDOR INFORMATION
──────────────────────────────────────────────────────────
QuickShip Logistics LLC
Delivery Note Number: DN-QSL-2026-4561

──────────────────────────────────────────────────────────
RECEIVING INFORMATION
──────────────────────────────────────────────────────────
Received By: Christopher Lee
Warehouse Location: Distribution Center - Bay 7
Receiving Date: January 22, 2026, 11:00 AM

──────────────────────────────────────────────────────────
ITEMS RECEIVED
──────────────────────────────────────────────────────────
Item   Description              Ordered   Received   Rejected
────────────────────────────────────────────────────────── 
1      Shipping Container Std   5         5          0
2      Pallet Wrap Industrial   100       100        0
3      Shipping Labels 1000pk   20        20         0

──────────────────────────────────────────────────────────
SUMMARY
──────────────────────────────────────────────────────────
Total Items Ordered: 125
Total Items Received: 125
Total Items Rejected: 0

Rejection Reason: N/A

──────────────────────────────────────────────────────────
CONDITION NOTES
──────────────────────────────────────────────────────────
All items received in satisfactory condition. Standard packaging.

All items match the specifications in PO-2026-404.

Inspected By: Christopher Lee
Inspection Date: January 22, 2026

NOTE: This vendor (VEND004 - QuickShip Logistics) has been flagged
in the vendor management system due to compliance issues.

══════════════════════════════════════════════════════════
```

</details>

---

## How to Use Test Scenarios

### Testing in Foundry Portal (Manual)
1. Open your workflow in Azure AI Foundry
2. Start a new conversation
3. Copy-paste the three documents (Invoice, PO, GRN) from one scenario
4. Observe agent processing and risk scoring
5. Review approval recommendation

### Testing via Custom Portal (Automated)
1. Start the portal: `python -m uvicorn invoice_portal:app --reload --port 8080`
2. Open http://localhost:8080
3. Upload the 3 files from any scenario folder
4. Watch real-time progress as workflow executes
5. Use Approve/Reject buttons when prompted
6. Review workflow execution summary

### Database Setup Required
Before testing, ensure SQL database has vendor data loaded:

```bash
python run_sql_scripts.py
```

This creates vendors VEND001-004 with proper status:
- VEND001: Active ✅
- VEND002: Active ✅
- VEND003: Active ✅
- VEND004: **Blocked** 🚫
