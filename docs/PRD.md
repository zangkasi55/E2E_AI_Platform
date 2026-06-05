# Product Requirements Document — Agentic AI Platform PoC

**Version:** 1.0 · **Date:** 2026-06-05 · **Owner:** DataX/TechX × Microsoft
**Status:** Approved for build · **Target demo:** 2026-06-19

---

## 1. Purpose & background

DataX/TechX (SCBX Group) needs to validate that a **Microsoft-native agentic AI platform** can support regulated banking workloads where AI assists humans but never autonomously executes high-risk actions. This PoC delivers a thin but complete vertical slice across two use cases, proving the platform's control, identity, governance, observability, and lifecycle capabilities on **synthetic data**.

The defining architectural principle is the **AI Foundation Deterministic Control Boundary**: probabilistic agent reasoning is cleanly separated from deterministic policy and tool execution. The model can *propose*; only deterministic controls *dispose*.

---

## 2. Goals & non-goals

### Goals
- G1. Demonstrate multi-agent orchestration with a parent agent delegating to sub-agents (UC1).
- G2. Demonstrate deterministic transaction control where the agent produces a **handoff**, not a transaction (UC2).
- G3. Enforce per-agent **workload identity** (Entra ID) validated at tool invocation.
- G4. Front all tools through **Azure API Management** as an MCP/agent tool bridge with scope checks, PII filtering, and logging.
- G5. Govern data with **Microsoft Purview** (classification + PII scanning of approved sources).
- G6. Produce a **structured, queryable audit trail** for every run, step, tool call, and handoff.
- G7. Provide **human-in-the-loop** approval via a durable, resumable workflow (UC1).
- G8. **Monitor token usage and cost** per agent, per model, per run, with a live dashboard.
- G9. Deliver a UI that visibly shows the **agent flow** and **which agent is working** at any moment.
- G10. Be fully buildable/deployable with **GitHub Copilot** + GitHub Actions on Azure.

### Non-goals (explicitly out of scope for the PoC)
- N1. Real customer data or production core-banking integration (synthetic + mock only).
- N2. Actual money movement or real payment rails.
- N3. Production-grade scale, HA, or DR.
- N4. Full model fine-tuning (use base Foundry models).
- N5. Mobile-native apps (web UI prototype only).

---

## 3. Personas

| Persona | Use case | Needs |
|---|---|---|
| **Loan Officer** | UC1 | Request a credit memo, receive a well-structured draft fast. |
| **Credit Reviewer** | UC1 | Review/edit/approve the AI draft in Teams; final accountability stays human. |
| **Retail Banking Customer** | UC2 | Conversational balance check + transfer *intent*; safety they can trust. |
| **Platform/Risk Engineer** | both | Audit trails, policy enforcement, token/cost visibility, lifecycle controls. |
| **Compliance Officer** | both | Evidence that AI cannot bypass controls; full traceability. |

---

## 4. Use case requirements

### UC1 — Credit Memo Drafting Agent (read-only, HITL)
**Narrative:** A loan officer requests a credit memo for an SME applicant. The `memo_orchestrator` parent agent plans a multi-step workflow and delegates to sub-agents, each calling approved tools through APIM. It assembles a structured draft, then **pauses** for a human reviewer in Teams. On approval, the memo is finalized and the full run is auditable.

**Functional requirements**
- F1.1 Accept a memo request (applicant id) and create a tracked run.
- F1.2 `memo_orchestrator` plans steps and invokes `doc_retrieval`, `financial_ratio`, `bureau_summary`, `memo_assembler`.
- F1.3 Sub-agents call tools `search_documents`, `get_financials`, `calculate_ratios`, `get_bureau_report`, `render_memo` via APIM (scope-checked, logged).
- F1.4 Retrieval is restricted to **approved sources** (Azure AI Search index over governed data).
- F1.5 Assemble a structured memo (sections: applicant overview, financials, ratios, bureau summary, risk assessment, recommendation).
- F1.6 **Durable HITL pause** → route to reviewer → resume on approve/edit.
- F1.7 No memo reaches "final/audited" state without explicit human approval.
- F1.8 Every step emits a structured audit record (identity, tools, latency, tokens).

**Acceptance**
- A1.1 A run completes end-to-end in mock mode and (when wired) live mode.
- A1.2 The reviewer can Approve or Request Edits; state transitions are persisted and resumable.
- A1.3 The audit trail for a run is retrievable via `GET /api/runs/{id}/trace`.
- A1.4 Token usage for the run is retrievable and attributed per agent/model.

### UC2 — Conversational Banking Control Pattern (deterministic)
**Narrative:** A customer says *"Check my balance. If I have more than 5,000 baht, transfer 2,000 baht to mom."* The `banking_controller` decomposes intent (SEQUENTIAL_CONDITIONAL), fills slots (amount, payee; flags missing source account → multi-turn clarify), evaluates the condition on a mock balance, then crosses into the deterministic zone to call tools through APIM. The terminal action is a **handoff object** — never a transfer.

**Functional requirements**
- F2.1 Parse intent into ordered sub-intents (`QUERY_BALANCE`, `TRANSFER_MONEY`) with the conditional relationship.
- F2.2 Slot filling with explicit `missing` slots → multi-turn clarification.
- F2.3 Conditional logic evaluated only on deterministic tool results (mock `get_balance`).
- F2.4 Tools `get_balance`, `resolve_payee`, `check_transfer_eligibility`, `request_transaction_handoff` via APIM with scope enforcement + PDP (RBAC/ABAC).
- F2.5 Terminal `request_transaction_handoff` returns `{requires_confirmation:true, requires_step_up_auth:true, tool_trace, policy_result}` and moves **no money**.
- F2.6 Deterministic guardrails reject unsafe instructions (e.g., "ignore the bank rules", "do not ask for OTP", prompt injection) regardless of prompt content.
- F2.7 Full trace: message, intent, slots, state transitions, tools available/called, params/results, policy checks, handoff, final response.

**Acceptance**
- A2.1 The canonical scenario yields a handoff object and a user-facing confirmation/clarification — no transaction executed.
- A2.2 The unsafe-instruction scenario is **blocked** by guardrails with an audit record.
- A2.3 Trace is queryable by session/run id.

---

## 5. Cross-cutting platform requirements

| # | Requirement |
|---|---|
| P1 | **Agent identity:** each agent instance = unique Entra workload identity; no shared service accounts; validated at tool invocation. |
| P2 | **Tool bridge:** all tools fronted by APIM (MCP server pattern) with OpenAPI schemas, per-call policy eval, field-level PII filtering, logging. |
| P3 | **Policy enforcement:** deterministic Policy Decision Point (RBAC + ABAC) outside the model. |
| P4 | **Prompt immutability:** system prompts/version-pinned; agent behavior not user-overridable. |
| P5 | **Data governance:** Microsoft Purview classification + PII scanning of approved sources. |
| P6 | **Observability:** Foundry Tracing + Application Insights + Azure Monitor/Log Analytics. |
| P7 | **Audit store:** per-instance, queryable (Cosmos DB). |
| P8 | **Token & cost monitoring:** per call/agent/model/run, surfaced in a dashboard. |
| P9 | **HITL durability:** pause/resume, checkpoint replay, idempotency (Durable Functions). |
| P10 | **Lifecycle:** agent registry Registered→Active→Suspended→Deprecated; promotion gate with behavior validation; CI/CD with evals. |
| P11 | **Model serving:** Azure OpenAI in Foundry Models, in-region, per-step model assignment, version-locked. |
| P12 | **Secrets:** Azure Key Vault; no secrets in code/config. |
| P13 | **Security posture:** Microsoft Defender for Cloud. |

---

## 6. Success criteria (demo-ready definition of done)

1. Both use cases run end-to-end (mock mode mandatory; live mode if Azure provisioned).
2. UI clearly shows the agent flow and the active agent at each step, for both use cases.
3. UC2 visibly produces a handoff with no money movement; unsafe instruction visibly blocked.
4. UC1 visibly pauses for human approval and resumes.
5. Token-usage dashboard shows tokens + estimated cost by agent and model for a run.
6. Audit trail retrievable for any run.
7. Every component (incl. Purview, Entra ID, APIM) has IaC + a deployment step.
8. A GitHub Copilot user can clone the repo and follow `deployment-plan.md` to stand it up.

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| AOAI capacity/quota in-region | Request quota early; fall back to nearest compliant region; document in deploy plan. |
| Scope creep beyond PoC | This PRD's non-goals are binding; mock/synthetic only. |
| Control boundary "leaks" (model executing actions) | Tools only via APIM; UC2 terminal = handoff; deterministic guardrails; tests assert no-money-movement. |
| Timeline (14 days) | Mock-mode-first so UI/demo never blocks on Azure; parallel workstreams; Copilot-assisted wiring. |

---

## 8. Timeline (to 2026-06-19)

| Dates | Milestone |
|---|---|
| Jun 5–7 | Repo + mock-mode backend + UI prototype reviewable. |
| Jun 8–10 | Provision Azure (identity → data → AOAI/Search → APIM). |
| Jun 11–13 | Wire live mode; Functions tools; Durable HITL; Cosmos audit. |
| Jun 14–16 | Purview scan; token dashboard live; guardrail + audit hardening. |
| Jun 17–18 | End-to-end rehearsals (both use cases); fix list. |
| Jun 19 | Demo. |
