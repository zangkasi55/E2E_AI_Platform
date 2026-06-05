# Synthetic Test Data — Agentic AI Platform PoC

All data here is **synthetic and clearly fake**. No production or PII data (per the canonical spec data-classification rule). Amounts are in **Thai baht (THB)** with Thailand-plausible names. These files are loaded by the backend tool stubs (`backend/app/tools/registry.py`) when running in `MOCK_MODE=true`, and are intended to be uploaded to Azure (Blob container `synthetic`, Azure AI Search index `agpoc-search-dev`) for the live PoC.

## Use Case 1 — Credit Memo Drafting (`data/credit_memo/`)

| File | Purpose | Tool that reads it |
|---|---|---|
| `applicants.json` | ~5 synthetic SME loan applicants (company, sector, requested amount THB) | (lookup / seed) |
| `financials.json` | 3-year financial statements per applicant | `get_financials(applicant_id)` |
| `bureau.json` | Synthetic NCB-style credit-bureau reports | `get_bureau_report(applicant_id)` |
| `memo_templates.json` | Credit-memo section templates | `render_memo(sections, template_id)` |
| `documents.json` | Approved-source corpus chunks for Azure AI Search | `search_documents(query, source_filter)` |

## Use Case 2 — Conversational Banking (`data/banking/`)

| File | Purpose | Tool that reads it |
|---|---|---|
| `users.json` | ~4 users + accounts + balances (one > 5000 THB, one < 5000 THB) | `get_balance(user_id, account_id)` |
| `payees.json` | Payee alias maps ("mom", "landlord") → payee ids | `resolve_payee(user_id, payee_alias)` |
| `sample_conversations.json` | Canonical scenario + prompt-injection scenarios to refuse | (test fixtures) |

## Key fixtures for demos

- **Balance > 5000 path**: `USR-001 / ACC-001-CUR` = 42,000 THB → conditional transfer leg proceeds to handoff.
- **Balance < 5000 path**: `USR-002 / ACC-002-SAV` = 3,200 THB → condition fails, no transfer leg.
- **Prompt-injection refusals**: scenarios `SC-INJECTION-03` and `SC-INJECTION-04` MUST be refused by the banking controller guardrails before any tool call.

> Reminder: UC2 **never moves money**. The terminal action is always `request_transaction_handoff`, which emits an auditable handoff object requiring human confirmation and step-up auth.
