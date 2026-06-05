# Fit-Gap Summary — Agentic AI Platform PoC

**Demo date:** 2026-06-19 · **Context:** DataX / TechX × Microsoft, SCBX Group
**Purpose:** This document answers the customer's explicit ask in *Scope Calibration for June 19 Completion* — **Minimum Expected Implementation #8** ("A fit-gap summary covering what was implemented, what was mocked, and what would be required for production") and **Assessment criterion #6** ("Transparency of fit-gap assessment").

It is the single, honest disclosure of what runs, what is simulated, and what is documented-only. The live conformance view of this table is `ui/test-expectations.html`.

---

## 1. How to read this document

Every capability is tagged with one status:

| Status | Meaning |
|---|---|
| **Demonstrated** | Runs end-to-end in the PoC (mock mode), observable in the UI and/or backend. |
| **Mocked** | The *pattern* runs, but against synthetic data / simulated services instead of live Azure or bank systems. The contract and code path are real; the data source is not. |
| **Documented** | Not executed in the PoC window. Delivered as a production design note with enough specificity to assess feasibility (per the customer's design-note template). |

The calibration document explicitly permits Mocked and Documented in place of full implementation (*Permitted Scope Reduction* §1–§10), provided the reduction is explicit. This table is that explicit disclosure.

---

## 2. Minimum Expected Implementation — conformance

The eight items the customer listed as the minimum bar, each mapped to where it is satisfied.

| # | Customer minimum item | Status | Where it runs / evidence |
|---|---|---|---|
| 1 | Credit memo drafting flow using synthetic data | **Demonstrated** | `ui/credit-memo.html` — `memo_orchestrator` plans → 4 sub-agents → HITL pause → final. Data: `data/credit_memo/*.json`. |
| 2 | Chat-based conversational banking control-pattern flow using mock tools | **Demonstrated** | `ui/banking.html` — `banking_controller`, prob/det zones, 4 deterministic tools via APIM. Data: `data/banking/*.json`. |
| 3 | Controlled agent tool invocation | **Demonstrated** | Every tool call routes through the APIM tool bridge (`architecture.md` §4): JWT/Entra validate → scope check → PII filter → rate limit → log → backend. No tool is callable around the gate. |
| 4 | Structured intermediate outputs | **Demonstrated** | Per-step records (`{run_id, step, agent, model, tool_called, params_hash, result_summary, policy_result, tokens, ts}`); ratios object, memo sections array, resolved slots, handoff object — all structured, all in the step trace. |
| 5 | Basic policy or guardrail enforcement | **Demonstrated** | APIM scope check + PDP (RBAC/ABAC) on UC2; deterministic guardrail **block path** (`banking_blocked` run) where an injected "ignore the rules / skip OTP" directive is refused with zero tools invoked. |
| 6 | Trace or audit evidence for agent execution | **Demonstrated** | Per-step audit line on every step; Cosmos `steps` / `handoffs` / `tokens` containers (`architecture.md` §8.1). Sample traces are visible in each demo's audit rail. |
| 7 | Clear distinction between probabilistic AI behavior and deterministic control points | **Demonstrated** | The **AI Foundation Deterministic Control Boundary** is the spine of the architecture: model reasons/plans above it, policy + tools decide below it. UC2 explicitly tags each stage `prob` vs `det`. |
| 8 | Fit-gap summary (implemented / mocked / production-required) | **Demonstrated** | This document + the live dashboard `ui/test-expectations.html`. |
| — | **Constraint:** banking must NOT execute money movement — handoff object only | **Demonstrated** | Terminal UC2 action is handoff `HO-5521` with `money_moved:false, requires_confirmation:true, requires_step_up_auth:true`. No tool exists that moves money. |

**Result: 8 / 8 minimum items demonstrated, plus the no-money-movement constraint.**

---

## 3. Component-level fit-gap

What is real code vs. simulated, component by component, so the reviewer can see exactly where the mock boundary sits.

| Component | Status | What is real in the PoC | What is mocked / deferred |
|---|---|---|---|
| Multi-agent orchestration (parent + 4 sub-agents) | **Demonstrated** | SK connected-agent topology, plan→delegate→assemble, per-step model assignment. | Runs in `MOCK_MODE` — model responses are canned; the delegation graph and step records are real. |
| Deterministic control boundary (APIM) | **Demonstrated / Mocked** | The policy *sequence* (validate-jwt → scope → PII → rate limit → log) is implemented as APIM policy XML (`infra/apim/policies/inbound-tool-call.xml`). | Not deployed to a live APIM instance in the demo; runs against the simulated bridge. Bicep provisions the real gate. |
| Tool execution (Azure Functions) | **Mocked** | Tool contracts + OpenAPI schemas (`backend/app/tools/mcp_schemas.py`); tools read from `data/`. | Real Functions deployment + real portco/bank APIs. |
| HITL pause/resume (Durable Functions + Service Bus) | **Demonstrated (pattern)** | Pause → external approval → idempotent resume is shown in UC1; `final` is unreachable without `approve`. | Live Durable Functions + Service Bus `hitl-approvals` + Teams reviewer connector. |
| Token & cost monitoring | **Demonstrated** | Canonical token record on every model call; aggregations (by agent / model / run); `ui/token-monitor.html`. Live-mode emits `gen_ai.token.usage`. | App Insights ingestion is live-mode only; demo uses the `len/4` estimate (identical schema). |
| Identity (Entra, per-agent workload identity) | **Documented / Mocked** | Scope model + RBAC table designed (`architecture.md` §3); context headers (`x-agent-name`, `x-run-id`) defined. | Real Entra app registrations + federated credentials + managed identities. |
| Data governance (Purview) | **Documented** | Classification → PII-filter mapping designed (`architecture.md` §5). | Live Purview scans + classification export to APIM. |
| Retrieval (Azure AI Search) | **Mocked** | `search_documents` contract + approved-sources concept. | Live hybrid/semantic index over a governed corpus. |
| **Azure Storage (Blob / ADLS Gen2)** | **Documented** | Per calibration §"Data and Integration Simplification": Azure interop is **not required** in the PoC. | Production connectivity is delivered as a design note → `production-design-notes.md`. |
| Security posture (Defender for Cloud) | **Documented** | Plan + scope identified (`architecture.md` §8.4). | Live Defender plan + alerts. |
| CI/CD (GitHub Actions, OIDC) | **Demonstrated (config)** | Four workflows authored (`.github/workflows/`). | Live OIDC federation + real deploy to a subscription. |
| IaC (Bicep) | **Demonstrated (config)** | Modular Bicep for all resources (`infra/`), incl. storage as a documented production target. | `az deployment` against a live subscription. |

---

## 4. Deliberate scope decisions (and why)

The calibration permits reducing to **one parent + one sub-agent** (§5) and **one policy enforcement point** (§6). We chose to **keep the fuller pattern** for two reasons:

1. It already runs in mock mode with zero Azure cost, so the reduction buys nothing.
2. The calibration's stated preference is *"smaller but well-controlled and well-documented … preferable to a broader demo that does not show governance."* Our breadth is matched by the governance evidence (boundary, audit, guardrail block, token attribution), so it does not trade against control.

Where we **did** reduce, it is explicit:

| Decision | Calibration clause invoked |
|---|---|
| Synthetic data for both use cases; no live customer data. | Permitted Reduction §1; "No production customer data will be provided." |
| Mock portco / banking tools, not real services. | Permitted Reduction §2, §3. |
| One representative workflow per use case (not all variants). | Permitted Reduction §4. |
| One HITL approval pattern (UC1), not a full HITL operating model. | Permitted Reduction §8. |
| Sample audit traces, not full live observability ingestion. | Permitted Reduction §7. |
| **No direct Azure Storage connection**; documented production design instead. | Data & Integration Simplification; Permitted Reduction §9. |
| Preview/roadmap dependencies called out. | Permitted Reduction §10; see `production-design-notes.md` §"Dependencies on preview or roadmap features." |

---

## 5. What would be required for production

Summarized here; full design notes (with the customer's 10-point template) are in `production-design-notes.md`.

| Capability | Production requirement (one line) |
|---|---|
| Azure Storage connectivity | Private Link + managed identity + Entra RBAC to Blob/ADLS in-region; see design note §1. |
| Live model serving | AOAI deployments in `southeastasia`, version-pinned, content filters on. |
| Tool execution | Functions deployed behind the live APIM product; real portco/bank API integration. |
| Identity | Entra app registrations, per-agent federated identities, scope grants. |
| Governance | Purview scans on real sources; classification export wired to APIM PII filtering. |
| Observability | App Insights + Log Analytics ingestion; saved KQL + alerts (runaway-token guard). |
| HITL | Durable Functions + Service Bus + Teams reviewer experience. |
| Security | Defender for Cloud plan; Key Vault references for all secrets. |

---

## 6. Mapping to the assessment criteria

How this PoC answers each of the customer's *Assessment Approach Under Reduced Scope* criteria.

| # | Assessment criterion | Where addressed |
|---|---|---|
| 1 | Working capability demonstrated by June 19 | §2 (8/8 minimum items run in mock mode). |
| 2 | Quality and realism of the architecture pattern | `architecture.md`, `Agentic_AI_PoC_Architecture.pptx`. |
| 3 | Clarity of the deterministic control model | The boundary (§3 row 2); UC2 prob/det tagging. |
| 4 | Strength of tool governance | APIM gate: scope + PDP + PII + rate limit (`architecture.md` §4). |
| 5 | Quality of trace and audit evidence | Per-step records + Cosmos audit (`architecture.md` §8.1; `token-monitoring.md`). |
| 6 | Transparency of fit-gap assessment | **This document** + `ui/test-expectations.html`. |
| 7 | Practicality of the production path | `production-design-notes.md`, `deployment-plan.md`. |
| 8 | Quality of joint engineering collaboration | Process — GitHub-Copilot-buildable repo, modular Bicep, clear READMEs. |
| 9 | Responsiveness in resolving blockers | Process — `MOCK_MODE` unblocks UI/demo while infra provisions. |
| 10 | Clear disclosure of what was mocked / simplified / deferred | **This document** (§3, §4) — every mock boundary stated. |
