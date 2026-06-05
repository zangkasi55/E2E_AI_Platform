# Architecture & Component Design — Agentic AI Platform PoC

This document is the engineering reference for every component. It complements the editable architecture deck (`Agentic_AI_PoC_Architecture.pptx`) and the Bicep in `infra/`. Resource names are canonical (see `infra/main.bicepparam`).

---

## 1. System overview

```
 ┌───────────────────────── EXPERIENCE / CHANNEL ─────────────────────────┐
 │  Conversational Banking Chat UI (mock)   ·   Credit Memo Reviewer (Teams)│
 └───────────────┬───────────────────────────────────────┬────────────────┘
                 │                                         │
 ┌───────────────▼───── AGENT ORCHESTRATION (Foundry + Semantic Kernel) ───▼─┐
 │  Parent agents: memo_orchestrator · banking_controller                    │
 │  Sub-agents: doc_retrieval · financial_ratio · bureau_summary · assembler │
 │  Durable Functions: HITL pause/resume · checkpoint replay · idempotency   │
 └───────────────┬───────────────────────────────────────────────────────────┘
                 │  reason / plan (probabilistic)
 ══════════════ AI FOUNDATION DETERMINISTIC CONTROL BOUNDARY ═══════════════
                 │  tool calls (deterministic, policy-gated)
 ┌───────────────▼──── TOOL & INTEGRATION BRIDGE — Azure API Management ──────┐
 │  JWT/Entra validation · scope check · PII filter · rate limit · logging    │
 │  → Azure Functions (tool execution) · Logic Apps (orchestrated calls)      │
 └───────────────┬───────────────────────────────────────────────────────────┘
                 │
 ┌───────────────▼──── DATA & KNOWLEDGE ─────────────────────────────────────┐
 │  Azure AI Search (approved sources) · Synthetic datasets / mock APIs       │
 │  Storage: Blob · ADLS Gen2                                                 │
 └────────────────────────────────────────────────────────────────────────────┘

 Left rail  (cross-cutting): Entra ID · Managed Identities · Key Vault · APIM authz
 Right rail (cross-cutting): Purview · Defender · Foundry Tracing · App Insights ·
                             Azure Monitor/Log Analytics · Cosmos audit · CI/CD · registry
 Model serving: Azure OpenAI in Foundry Models (in-region, per-step, version-locked)
```

The single most important property: **the model sits above the boundary and can only request actions; deterministic policy + tools sit below it and decide.**

---

## 2. Agent orchestration

### 2.1 UC1 topology — `memo_orchestrator`
- **Parent** plans an ordered workflow and delegates (Semantic Kernel connected-agent pattern).
- **Sub-agents**
  - `doc_retrieval` → `search_documents` (Azure AI Search, approved sources only)
  - `financial_ratio` → `get_financials` + `calculate_ratios`
  - `bureau_summary` → `get_bureau_report`
  - `memo_assembler` → `render_memo` (template-driven)
- **HITL:** after assembly, Durable Functions persists state and raises an approval to Service Bus `hitl-approvals`; the reviewer acts in Teams; the workflow resumes idempotently.
- **Invariant:** `final` state is reachable only via human `approve`.

### 2.2 UC2 topology — `banking_controller`
- **Probabilistic stages:** intent decomposition (`SEQUENTIAL_CONDITIONAL`), slot filling (amount/payee, flag missing source account), conditional evaluation on deterministic balance.
- **Deterministic stages (below boundary):** `get_balance` → `resolve_payee` → `check_transfer_eligibility` → `request_transaction_handoff`.
- **Invariant:** terminal action is a **handoff object**, never a transfer. Guardrails are evaluated deterministically and cannot be overridden by prompt content.

### 2.3 Per-step record (emitted for every step)
`{run_id, step, agent, model, tool_called, params_hash, result_summary, latency_ms, prompt_tokens, completion_tokens, total_tokens, policy_result, ts}` → Cosmos `steps` + App Insights trace.

---

## 3. Component design — Microsoft Entra ID (identity)

**Goal:** every agent instance is a uniquely identifiable, least-privilege workload. No shared service accounts. Identity is validated *at the tool call*, tied to the workflow + session.

### 3.1 Registrations & identities
| Principal | Type | Purpose |
|---|---|---|
| `agpoc-orchestrator` | App registration + **user-assigned managed identity** | The Container Apps FastAPI orchestrator; acquires tokens to call APIM, Cosmos, AOAI, Search. |
| `agpoc-tool-bridge` | App registration (API) | Represents the APIM tool API; exposes scopes the orchestrator must hold. |
| `agpoc-ui` | App registration (SPA/public) | The web UI; user sign-in (PoC: optional, can run anonymous in mock). |
| Per-agent identity | Managed-identity *federated subject* / token claim | Each agent run stamps its agent name + run/session id into the token context used for the tool call. |

### 3.2 Scopes (APIM-enforced)
Define API scopes on `agpoc-tool-bridge`, one per tool family:
`tools.memo.read`, `tools.financials.read`, `tools.bureau.read`, `tools.memo.render`,
`tools.banking.balance.read`, `tools.banking.payee.read`, `tools.banking.eligibility.read`, `tools.banking.handoff.write`.

An agent gets only the scopes its job requires (e.g., `doc_retrieval` holds `tools.memo.read` only; `banking_controller` never holds a "move money" scope because none exists).

### 3.3 Token validation flow
1. Orchestrator/agent acquires a token (managed identity) for `agpoc-tool-bridge` with the minimal scope.
2. APIM `validate-jwt` checks issuer/audience/signature against the tenant; asserts the required `scp`/`roles` claim for the specific operation; asserts agent/run context headers.
3. On failure → `401/403` + audit record; the model never sees a path around this.

### 3.4 RBAC (Azure-plane, least privilege)
| Identity | Role | Scope |
|---|---|---|
| `agpoc-orchestrator` | Key Vault Secrets User | `agpoc-kv-dev` |
| `agpoc-orchestrator` | Cosmos DB Built-in Data Contributor | `agpoc-cosmos-dev` |
| `agpoc-orchestrator` | Cognitive Services OpenAI User | `agpoc-aoai-dev` |
| `agpoc-orchestrator` | Search Index Data Reader | `agpoc-search-dev` |
| Function identities | Storage Blob Data Reader | `agpocstoragedev` |

See `infra/modules/identity.bicep` for the assignments.

---

## 4. Component design — Azure API Management (the tool bridge / deterministic boundary)

**Goal:** APIM is the single deterministic gate between probabilistic agents and any real action. It implements the MCP/agent-tool-bridge pattern.

### 4.1 API surface
- One API: **Agent Tools** (`/tools/*`), backed by Azure Functions.
- Operations map 1:1 to the canonical tool catalog; each carries its OpenAPI schema (`backend/app/tools/mcp_schemas.py` is the source for these).
- Products: `agent-tools-uc1`, `agent-tools-uc2`; subscriptions issued to the orchestrator identity.

### 4.2 Inbound policy (per call) — see `infra/apim/policies/inbound-tool-call.xml`
1. **`validate-jwt`** against Entra (issuer, audience = `agpoc-tool-bridge`, signature).
2. **Scope check** — require the operation's `scp`/`roles` claim; else `403`.
3. **Context binding** — require `x-agent-name`, `x-run-id`, `x-session-id` headers; stamp into logs.
4. **Rate limit** — per subscription + per run, to bound runaway loops.
5. **Field-level PII filtering** — redact/transform configured PII fields in request and response (works with Purview classifications; see §5.4).
6. **Logging** — emit request/response metadata + policy decision to Application Insights.
7. **Backend routing** — `set-backend-service` to the Function tool.

### 4.3 Why APIM, not in-model logic
Policy lives in a managed gateway the model cannot edit or talk its way past. This is what makes "ignore the rules" prompt injection structurally ineffective: the model's words never reach the policy engine.

---

## 5. Component design — Microsoft Purview (data governance)

**Goal:** classify and PII-scan all (synthetic) data the agents can touch, so "approved sources" is a governed fact, not a convention, and so APIM's PII filtering is driven by real classifications.

### 5.1 Account & data map
- `agpoc-purview-dev` account with a collection `agentic-poc`.
- Registered sources: `agpocstoragedev` (Blob + ADLS Gen2), the Azure AI Search index, and (logically) the mock portfolio-company APIs.

### 5.2 Classification & scanning
- Run scans on the `synthetic`, `memos`, `templates` containers.
- Apply built-in + custom classifications: person name, national ID (Thai), account number, balance/amount, credit-bureau score.
- Even though data is synthetic, classifications are **structurally real** — they parameterize downstream PII filtering and prove the governance loop.

### 5.3 Glossary & lineage
- Publish a small business glossary (Applicant, Financial Statement, Bureau Report, Memo Template, Payee, Account).
- Capture lineage from source → AI Search index → tool → agent, so a reviewer can answer "where did this fact come from?".

### 5.4 Governance → runtime link
- Purview classifications are exported (or mirrored as config) to drive **APIM field-level PII filtering** and the AI Search field-level security. The PoC wires this as a documented mapping (`infra/modules/purview.bicep` comments) so production can automate it.

### 5.5 "Approved sources" enforcement
- `doc_retrieval` may only query the governed AI Search index; the tool has no path to ungoverned data. Purview is the system of record proving the index's contents are classified and approved.

### 5.6 Purview as an observability surface
Governance is not only configured — it is **observable**. The PoC demonstrates Purview's observability through four offline panels in `ui/purview-observability.html` (driven by the same `window.AGPOC` mock backend), reproducing the information shape of four real Purview surfaces:

1. **Data lineage graph** — a left-to-right provenance strip for one credit-memo fact: `Synthetic source (ADLS) → Purview classification → AI Search → search_documents (APIM) → doc_retrieval → memo section`. Clicking a node answers "where did this fact come from?".
2. **Classification coverage** — every synthetic field → its classification → sensitivity → **the APIM PII action it drives** (allow / mask / redact), making the governance→runtime link visible.
3. **Governance → runtime link** — Purview classifications feeding the APIM `inbound-tool-call` PII-filter step, so redaction is *driven by governance*, not hardcoded.
4. **Data Estate Insights tiles** — coverage KPIs (sources registered, % fields classified, sensitive-field count, approved-source count).

This is the **design-time / data-governance observability plane**; the **runtime / execution plane** is App Insights + Cosmos audit + the token metric (`ui/token-monitor.html`). Full design: `production-design-notes.md` §2. Together they answer both "is the data governed and where did it come from?" and "what did the agents do and what did it cost?".

---

## 6. Model serving — Azure OpenAI in Foundry Models
- `agpoc-aoai-dev` with deployments `gpt-4o`, `gpt-4o-mini`, in-region.
- Per-step model assignment (see `tech-stack.md` §5); model + version recorded on every step and token record.
- Content filters enabled; prompts version-pinned (prompt immutability requirement P4).

---

## 7. Data & knowledge
- **Azure AI Search** `agpoc-search-dev`: hybrid + semantic over the approved corpus (`data/credit_memo/documents.json`).
- **Storage** `agpocstoragedev` — **documented production target, not wired in the PoC.** Per the June 19 scope calibration (Data & Integration Simplification), the PoC runs entirely from local synthetic `data/`; no live Storage connection is required to demonstrate the patterns. The container model (`synthetic` datasets, `memos` rendered drafts, `templates` memo templates) and the production connectivity path (managed identity → `Storage Blob Data Reader`, private endpoints, ADLS Gen2 hierarchy) are delivered as a design note in `production-design-notes.md` §1 with enough specificity to assess feasibility and automate later.
- **Mock portfolio APIs**: the Functions tools read from `data/` to simulate financials/bureau/banking systems.

---

## 8. Governance, observability & lifecycle (right rail)

### 8.1 Audit store (Cosmos DB `agpoc-cosmos-dev`, db `agentaudit`)
| Container | Partition key | Holds |
|---|---|---|
| `runs` | `/run_id` | one doc per workflow run (use case, status, timestamps, requester). |
| `steps` | `/run_id` | per-step trace records (§2.3). |
| `handoffs` | `/run_id` | UC2 handoff objects (immutable). |
| `tokens` | `/run_id` | per-call token records (see `token-monitoring.md`). |

Queryable per instance: `GET /api/runs/{id}/trace`.

### 8.2 Observability
- **Application Insights** `agpoc-appi-dev` + **Log Analytics** `agpoc-law-dev` + Foundry Tracing.
- Distributed traces span agent → tool (APIM) → Function → data.
- Custom metric **`gen_ai.token.usage`** (see §9).
- Saved KQL in `infra/observability/kql/token_usage.kql`.

### 8.3 Lifecycle & CI/CD
- **Agent registry** states: Registered → Active → Suspended → Deprecated.
- **Promotion gate** with behavior validation (Foundry evals) in CI before an agent goes Active.
- GitHub Actions deploy infra/backend/functions/ui (see `.github/workflows/`).

### 8.4 Security
- **Key Vault** `agpoc-kv-dev` for all secrets (Key Vault references in app settings).
- **Defender for Cloud** plan on the subscription for posture + threat alerts.

---

## 9. Token & cost monitoring (summary; full spec in `token-monitoring.md`)
- Every model call → a token record (`run_id, agent, step, model, prompt/completion/total tokens, est_cost_usd, ts, use_case`) written to Cosmos `tokens` and emitted as App Insights custom metric `gen_ai.token.usage` (dimensions: agent, model, use_case).
- Backend exposes `GET /api/tokens/summary` and `GET /api/tokens/run/{id}`.
- UI `token-monitor.html` visualizes totals, by-agent, by-model, est. cost, per-run timeline.

---

## 10. End-to-end sequences

### 10.1 UC1 (credit memo)
```
Officer → POST /api/credit-memo/run
  orchestrator.plan()
  doc_retrieval → APIM → search_documents
  financial_ratio → APIM → get_financials, calculate_ratios
  bureau_summary → APIM → get_bureau_report
  memo_assembler → APIM → render_memo
  Durable HITL pause → Service Bus → Teams reviewer
Reviewer → POST /api/credit-memo/run/{id}/approve
  resume → state=final (audited)
(every arrow emits a step + token record)
```

### 10.2 UC2 (banking)
```
Customer → POST /api/banking/message
  banking_controller: decompose intent → fill slots → evaluate condition
  ── boundary ──
  APIM → get_balance → resolve_payee → check_transfer_eligibility
  PDP (RBAC/ABAC) + guardrails
  APIM → request_transaction_handoff  ⇒ handoff object {requires_confirmation, requires_step_up_auth}
  ← user-facing confirmation/clarification (NO money moved)
Unsafe variant → guardrail BLOCK + audit record
```

---

## 11. Traceability to requirements
Every PRD platform requirement P1–P13 maps to a component here: P1→§3, P2/P3→§4, P4→§6, P5→§5, P6/P7→§8.1–8.2, P8→§9, P9→§2.1, P10→§8.3, P11→§6, P12→§8.4, P13→§8.4.
