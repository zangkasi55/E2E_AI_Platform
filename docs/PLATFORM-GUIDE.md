# E2E AI Platform — Complete Platform Guide

**Project:** Agentic AI Platform PoC
**Partners:** DataX / TechX × Microsoft (SCBX Group context)
**Region:** Azure Southeast Asia (Singapore) — Thailand-nearest model serving
**Status:** Proof of Concept — synthetic data only, no production PII
**Build tooling:** GitHub Copilot–assisted, typed code, infrastructure-as-code (Bicep **and** Terraform)

This document is the single, end-to-end reference for the platform: **what it
does, how it was developed, its capabilities and features, the full technology
stack, the architecture, and how to deploy everything** with either Bicep or
Terraform. For deeper dives, the linked documents under [`docs/`](.) remain the
source of truth for each topic.

## Latest implementation update (2026-06-06)

### What changed

- Resolved production HTTP 500 failures in UC1 and UC2 caused by missing runtime fixture files in the deployed orchestrator container.
- Added runtime synthetic data into backend build context under `backend/data/`.
- Updated container build to include this folder (`backend/Dockerfile` uses `COPY data ./data`).
- Updated backend default data path (`backend/app/config.py`) to `data`, which resolves to `/app/data` inside the container.

### Why this issue happened

The deployment pipeline builds from `./backend`. Any files outside that folder (for example root `data/`) are excluded from image build context. Orchestration then tried to load JSON fixture files that were not present in the container filesystem, producing `FileNotFoundError` and endpoint 500s.

### How the fix works end-to-end

1. Data files are now present in backend build context (`backend/data`).
2. Docker image copy step includes these files at build time.
3. Runtime path resolution points orchestration to in-image data (`/app/data`).
4. Registry JSON loaders in UC1 and UC2 can resolve required files deterministically.
5. Post-deploy validation confirms behavior with probes, stress tests, Purview DSPM events, and dependency telemetry (`/msi/token`, `invoke_agent`).

---

## Table of contents

1. [What this platform is](#1-what-this-platform-is)
2. [Capabilities](#2-capabilities)
3. [Features](#3-features)
4. [Technology stack](#4-technology-stack)
5. [How it was developed](#5-how-it-was-developed)
6. [Architecture](#6-architecture)
7. [Repository structure](#7-repository-structure)
8. [Running locally (mock mode)](#8-running-locally-mock-mode)
9. [Deploying to Azure — Bicep](#9-deploying-to-azure--bicep)
10. [Deploying to Azure — Terraform](#10-deploying-to-azure--terraform)
11. [CI/CD](#11-cicd)
12. [Governance, security & observability](#12-governance-security--observability)
13. [Hard safety rules](#13-hard-safety-rules)

---

## 1. What this platform is

A Microsoft-native, production-shaped agentic AI platform that proves two
regulated-banking use cases while enforcing an **AI Foundation deterministic
control boundary**: the probabilistic agent reasons, plans, and drafts — but
every high-risk action is gated by deterministic policy and tools. *The model
proposes; only deterministic controls dispose.*

| Use case | What it proves |
|---|---|
| **UC1 — Credit Memo Drafting** | Read-only multi-agent orchestration with human-in-the-loop approval. Agents draft; a human decides; every step is audited. |
| **UC2 — Conversational Banking Control** | Deterministic transaction control. The agent decomposes intent and fills slots, but **no money is ever moved** — the terminal output is an auditable handoff requiring confirmation + step-up auth. |

```
        PROBABILISTIC  (Azure OpenAI / Foundry Agent Service)
        intent · planning · slot-filling · drafting
   ─────────────────────────────────────────────────────────  ← enforced boundary
        DETERMINISTIC  (Azure API Management + policy + tools)
        scope check · PDP (RBAC/ABAC) · PII filter · audit · handoff
```

---

## 2. Capabilities

- **Multi-agent orchestration** — a parent planner delegates to specialized
  sub-agents (document retrieval, financial ratios, bureau summary, memo
  assembly) using a Semantic Kernel connected-agent pattern.
- **Deterministic transaction control** — intent decomposition above the
  boundary, scoped/audited tool calls below it, with a terminal handoff object
  that physically has no "move money" code path.
- **Human-in-the-loop (HITL)** — UC1 pauses for a reviewer decision (approve /
  edit / reject) before any memo becomes final; backed by Service Bus +
  Durable Functions in live mode.
- **Per-agent workload identity** — every agent runs under a unique Microsoft
  Entra identity; no shared service accounts. Validated at every tool call.
- **Deterministic guardrails** — prompt-injection / jailbreak attempts ("ignore
  the rules", "skip OTP") are blocked by code regexes *before* any tool runs;
  they cannot be overridden by prompt content.
- **Data governance** — Microsoft Purview sensitivity-label resolution gates
  document ingestion (Confidential / Highly Confidential are blocked); DSPM for
  AI surfaces data-security events.
- **Token monitoring & cost** — every model call records prompt/completion/total
  tokens and an estimated USD cost to Cosmos DB and to the App Insights metric
  `gen_ai.token.usage`.
- **Full audit trail** — every run, step, tool call, and handoff is a structured
  record in Cosmos DB, partitioned by `run_id`.
- **Two observability planes** — Purview (design-time / data governance) and
  App Insights + Cosmos + token metric (runtime / execution).
- **Mock-first development** — the entire platform runs offline (`MOCK_MODE=true`)
  with canned model responses, so the demo works with no Azure dependency.

---

## 3. Features

### UC1 — Credit Memo Drafting
- Parent orchestrator (`gpt-4o`) plans; sub-agents (`gpt-4o-mini`) retrieve
  documents, compute financial ratios (DSCR, leverage, liquidity), summarize the
  credit bureau report, and assemble a 4-section memo.
- Purview sensitivity-label gate rejects blocked documents *before* drafting.
- Deterministic verification of each step (chunk presence, DSCR ≥ 1.25, leverage
  ≤ 3.0, bureau score ≥ 680, required memo sections).
- HITL pause → reviewer approves/edits/rejects → `final_memo` (auditable).

### UC2 — Conversational Banking
- Deterministic guardrail scan **before** any tool call.
- Heuristic intent decomposition (`SEQUENTIAL_CONDITIONAL` / `SEQUENTIAL`),
  slot-filling (amount, payee, threshold, source account).
- Scoped deterministic tools: `get_balance`, `resolve_payee`,
  `check_transfer_eligibility`, `request_transaction_handoff`.
- Terminal `HandoffObject` with immutable `requires_confirmation = True`,
  `requires_step_up_auth = True`, and **no money moved**.

### Cross-cutting
- APIM tool bridge: JWT validation, per-tool scope, rate limiting, PII redaction,
  routing, correlation IDs.
- React SPA with live agent-flow visualization, HITL approval UI, token
  dashboard, governance/DSPM panels, and a fit-gap conformance dashboard.

---

## 4. Technology stack

| Layer | Technology |
|---|---|
| **Frontend** | React 18, TypeScript 5.5, Vite 5, React Router 6 |
| **Backend** | Python 3.11, FastAPI, Uvicorn, Pydantic v2 |
| **Agent orchestration** | Semantic Kernel 1.3 (connected-agent pattern) |
| **Model serving** | Azure OpenAI (`gpt-4o`, `gpt-4o-mini`); optional Foundry Agent Service |
| **Tool bridge / PDP** | Azure API Management (Developer SKU) with raw inbound policy |
| **Tool / HITL compute** | Azure Functions (Python 3.11, Consumption Y1) + Durable Functions |
| **App host** | Azure Container Apps (orchestrator), Azure Static Web Apps (SPA) |
| **State / audit** | Azure Cosmos DB (SQL API) — `runs`, `steps`, `handoffs`, `tokens` |
| **Secrets** | Azure Key Vault (RBAC, purge protection) |
| **Search** | Azure AI Search (basic, semantic free) |
| **Eventing** | Azure Service Bus (session-enabled `hitl-approvals` queue) |
| **Storage** | Azure Storage / ADLS Gen2 |
| **Identity** | Microsoft Entra ID workload identities + Azure RBAC |
| **Data governance** | Microsoft Purview + DSPM for AI |
| **Threat protection** | Microsoft Defender for Cloud (CSPM, Key Vault, Storage V2, AI) |
| **Observability** | OpenTelemetry → Azure Monitor / Application Insights / Log Analytics; metric `gen_ai.token.usage` |
| **IaC** | Bicep (`infra/`) **and** Terraform (`infra/terraform/`) |
| **CI/CD** | GitHub Actions with Entra OIDC (no stored secrets) |

Per-step model assignment: planning/assembly on `gpt-4o`, retrieval/ratios/bureau
on the cheaper `gpt-4o-mini` — rationale in [`docs/tech-stack.md`](tech-stack.md).

---

## 5. How it was developed

- **Mock-first, contract-driven.** The backend defines canonical Pydantic
  models (`TokenRecord`, `StepTrace`, `RunState`, `HandoffObject`, …) that the
  frontend mirrors in TypeScript. Both sides run against an in-memory mock
  backend, so the whole experience is buildable and demoable offline.
- **Deterministic boundary as a first principle.** Every design choice routes
  high-risk actions through APIM policy and scoped tools, never through prompt
  text. There is deliberately no `execute_transfer` tool anywhere in the
  registry — enforced by a unit test.
- **Two execution modes.** `MOCK_MODE` (canned), `LIVE_LLM` (real Azure OpenAI),
  and `USE_FOUNDRY_AGENTS` (Foundry Agent Service) can be toggled independently,
  enabling a hybrid demo (live model, mocked tools).
- **Observability built in, not bolted on.** Each model call is wrapped in an
  OpenTelemetry GenAI span and emits the `gen_ai.token.usage` metric, so cost and
  behavior are visible from day one.
- **Infrastructure as code, twice.** The platform ships with both Bicep and
  Terraform so customers can adopt whichever IaC standard they already use. Both
  encode the same names, SKUs, role assignments, and policies.
- **Copilot-friendly structure.** Typed code, clear per-folder READMEs, and
  inline `TODO:` markers wherever live Azure wiring is intentionally deferred.

---

## 6. Architecture

```
            ┌──────────────────────── React SPA (Static Web Apps) ───────────────────────┐
            │  Demo hub · UC1 flow · UC2 zones · Token dashboard · Governance / DSPM       │
            └───────────────┬─────────────────────────────────────────────────────────────┘
                            │ HTTPS (external ingress)
                  ┌─────────▼──────────┐
                  │  FastAPI orchestrator│  Container Apps (orchestrator identity)
                  │  SK multi-agent      │
                  └───┬───────────┬──────┘
   probabilistic ─────┤           │──── deterministic
        Azure OpenAI ◄┘           └─► APIM tool bridge ──► Functions (tools) ──► AI Search / data
   (gpt-4o, gpt-4o-mini)             (validate-jwt, scope,      │
                                      rate-limit, PII, route)   └─► Durable Functions (HITL) ◄─ Service Bus
                            │
            ┌───────────────┼───────────────┬───────────────┬───────────────┐
        Cosmos DB        Key Vault      Application       Microsoft        Microsoft
        (audit:           (secrets)     Insights /        Purview          Defender
        runs/steps/                     Log Analytics     (DSPM for AI)    for Cloud
        handoffs/tokens)               gen_ai.token.usage
```

Full component design: [`docs/architecture.md`](architecture.md). Production
deferrals: [`docs/production-design-notes.md`](production-design-notes.md).

---

## 7. Repository structure

```
E2E_AI_Platform/
├── README.md                    ← project overview + 5-minute tour
├── docs/
│   ├── PLATFORM-GUIDE.md            ← this document
│   ├── PRD.md                       ← product requirements, scope, success criteria
│   ├── architecture.md              ← full component design
│   ├── tech-stack.md                ← technology choices + rationale
│   ├── deployment-plan.md           ← phase-by-phase deploy guide
│   ├── token-monitoring.md          ← token-usage tracking design
│   ├── fit-gap.md                   ← Demonstrated / Mocked / Documented status
│   └── production-design-notes.md   ← production wiring deferrals
├── backend/                     ← FastAPI + Semantic Kernel orchestration, tools, telemetry
│   └── app/{agents,orchestration,tools,telemetry,durable,governance}
├── frontend/                    ← React 18 + TypeScript + Vite SPA
├── data/                        ← synthetic data (banking, credit_memo, policies)
├── infra/                       ← Bicep IaC (subscription-scoped) + modules
│   └── terraform/               ← Terraform IaC (parity with Bicep)
├── ui/                          ← legacy static HTML prototypes (reference only)
└── .github/workflows/           ← GitHub Actions CI/CD (OIDC)
```

---

## 8. Running locally (mock mode)

**Backend:**
```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
set MOCK_MODE=true            # PowerShell: $env:MOCK_MODE="true"
uvicorn app.main:app --reload
# http://localhost:8000/healthz  ·  http://localhost:8000/docs
```

**Frontend:**
```bash
cd frontend
npm ci
npm run dev      # http://localhost:5173
```

**Tests:**
```bash
cd backend && pytest        # offline smoke tests (incl. the no-money-movement guarantee)
```

---

## 9. Deploying to Azure — Bicep

Subscription-scoped deployment (creates the resource group and all resources):

```bash
az deployment sub create \
  --location southeastasia \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam
```

Deploy order encoded in the template: observability → (storage, key vault,
cosmos, openai, search, service bus) → identity → apim → functions →
container apps → purview → defender. See [`infra/README.md`](../infra/README.md)
and [`docs/deployment-plan.md`](deployment-plan.md).

---

## 10. Deploying to Azure — Terraform

Equivalent deployment with the `azurerm` + `azapi` providers:

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # optional — defaults reproduce `dev`
terraform init
terraform plan -out tfplan
terraform apply tfplan
```

Key outputs: `orchestrator_fqdn`, `tool_bridge_url`, `openai_endpoint`. Full
guidance in [`infra/terraform/README.md`](../infra/terraform/README.md).

> Use **either** Bicep or Terraform, not both against the same resource group.

---

## 11. CI/CD

GitHub Actions, authenticated via **Entra OIDC federated credentials** (no stored
secrets):

| Workflow | Trigger | Action |
|---|---|---|
| `backend.yml` | `backend/**` | `az acr build` → `az containerapp update` |
| `ui.yml` | `frontend/**` | `npm ci && npm run build` → Static Web Apps deploy |
| `functions.yml` | `backend/functions/**` | Publish tools + durable Function Apps (matrix) |

Runtime secrets (App Insights, Cosmos) are pulled from Key Vault via managed
identity, never stored in the pipeline.

---

## 12. Governance, security & observability

- **Identity:** per-agent Entra workload identities; tokens validated at the APIM
  boundary (issuer, audience, signature, `scp`/`roles` scope claim).
- **Least-privilege RBAC:** orchestrator and tool bridge each receive only
  Key Vault Secrets User, Cognitive Services OpenAI User, Search Index Data
  Reader, Storage Blob Data Reader, and the Cosmos *Data Contributor*
  data-plane role; the tool bridge additionally gets Service Bus Data Owner.
- **Data governance:** Purview sensitivity-label resolution + DSPM for AI;
  blocked labels (Confidential, Highly Confidential) stop document ingestion.
- **Threat protection:** Defender for Cloud CSPM + Key Vault + Storage V2 + AI
  plans (the AI plan delivers prompt-injection/anomaly detection for Azure OpenAI).
- **Audit:** every run/step/tool-call/handoff persisted to Cosmos.
- **Cost:** `gen_ai.token.usage` metric + per-call `est_cost_usd`
  (`gpt-4o` $0.005/$0.015 per 1K, `gpt-4o-mini` $0.00015/$0.0006 per 1K).
  See [`docs/token-monitoring.md`](token-monitoring.md).

---

## 13. Hard safety rules

These are non-negotiable and verified in code/tests:

1. **UC1:** no memo is `final` without explicit human approval.
2. **UC2:** no money movement — ever. The terminal artifact is an auditable
   handoff object. There is no `execute_transfer` / `make_payment` / `move_money`
   tool in the registry (enforced by `backend/tests/test_smoke.py`).
3. **Guardrails are deterministic, not prompt-driven.** Prompt-injection cannot
   bypass them; only a code change can.
4. **Synthetic data only** in the PoC — no production PII.
