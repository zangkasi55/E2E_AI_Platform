# Agentic AI Platform PoC

**Partners:** DataX / TechX × Microsoft (SCBX Group context)
**Region:** Azure Southeast Asia (Singapore), Thailand-nearest model serving
**Status:** Proof of Concept — synthetic data only, no production/PII
**Target demo date:** 2026-06-19
**Build tooling:** GitHub Copilot (this repo is structured to be Copilot-friendly — typed code, clear READMEs, inline `TODO:` markers where live Azure wiring is needed)

---

## What this is

A buildable scaffold for a Microsoft-native agentic AI platform that proves two regulated-banking use cases while enforcing an **AI Foundation deterministic control boundary** — the probabilistic agent reasons and plans, but every high-risk action is gated by deterministic policy and tools.

| Use case | What it proves |
|---|---|
| **UC1 — Credit Memo Drafting Agent** | Read-only, multi-agent orchestration with human-in-the-loop approval. The agent *drafts*; a human *decides*. Every step is audited. |
| **UC2 — Conversational Banking Control Pattern** | Deterministic transaction control. The agent decomposes intent and fills slots, but **no money is ever moved** — it produces an auditable handoff object requiring confirmation + step-up auth. |

---

## Repository map

```
agentic-ai-poc/
├── README.md                  ← you are here
├── docs/
│   ├── PLATFORM-GUIDE.md           ← complete end-to-end guide (capabilities, features, stack, deploy)
│   ├── PRD.md                      ← product requirements, scope, success criteria
│   ├── tech-stack.md              ← chosen technologies + rationale
│   ├── architecture.md            ← full component design (Purview, Entra ID, APIM, all services)
│   ├── token-monitoring.md        ← token-usage tracking design + dashboard contract
│   ├── deployment-plan.md         ← phase-by-phase deploy + Copilot build guide
│   ├── fit-gap.md                 ← June 19 scope calibration: minimum items + assessment criteria, Demonstrated/Mocked/Documented
│   └── production-design-notes.md ← production design notes (Azure Storage connectivity §1, Purview observability §2)
├── backend/                   ← FastAPI + Semantic Kernel orchestration, tools, telemetry
├── frontend/                  ← React 18 + TypeScript + Vite SPA (production UI)
├── ui/                        ← runnable HTML/JS prototype (legacy reference)
├── data/                      ← synthetic test data for both use cases
├── infra/                     ← Bicep IaC for every Azure component
│   └── terraform/             ← Terraform IaC (full parity with Bicep)
└── .github/workflows/         ← GitHub Actions CI/CD (OIDC)
```

> **New here?** Start with **[`docs/PLATFORM-GUIDE.md`](docs/PLATFORM-GUIDE.md)** —
> the complete end-to-end reference covering capabilities, features, the full
> technology stack, architecture, and both deployment paths (Bicep **and** Terraform).

---

## The 5-minute tour

1. **See the design** — open `ui/index.html` in a browser (runs offline). Walk both agent-flow demos, the token monitor, the **test-expectations conformance dashboard** (`ui/test-expectations.html` — live view of `docs/fit-gap.md`), and the **Purview observability view** (`ui/purview-observability.html` — lineage, classification → PII action, governance→runtime link).
2. **Read the plan** — `docs/PRD.md` → `docs/architecture.md` → `docs/deployment-plan.md`. For the scope-calibration response: `docs/fit-gap.md` + `docs/production-design-notes.md`.
3. **Run the backend in mock mode** — `cd backend`, set `MOCK_MODE=true`, `uvicorn app.main:app --reload`. No Azure needed; canned model responses drive the flow.
4. **Provision Azure** — choose your IaC: `infra/` (Bicep) **or** `infra/terraform/` (Terraform — full parity). Deploy order is in `docs/deployment-plan.md`.
5. **Wire it live** — flip `MOCK_MODE=false`, point env at your deployed resources, redeploy via GitHub Actions.

---

## The deterministic control boundary (the core idea)

```
        PROBABILISTIC  (Foundry Agent Service + Azure OpenAI)
        intent · planning · slot-filling · drafting
   ─────────────────────────────────────────────────────────  ← enforced boundary
        DETERMINISTIC  (Azure API Management + policy + tools)
        scope check · PDP (RBAC/ABAC) · PII filter · audit · handoff
```

The model never executes a high-risk action directly. It can only *request* an action through an APIM-fronted tool, where a deterministic policy decides whether the call is allowed, with what scope, and emits an audit record. For UC2 the terminal action is a **handoff**, not a transfer.

---

## Governance & monitoring at a glance

- **Identity:** every agent instance runs under a unique Microsoft Entra workload identity — no shared service accounts. Validated at tool invocation.
- **Data governance:** Microsoft Purview classifies and PII-scans all (synthetic) sources; APIM applies field-level PII filtering at the tool boundary.
- **Audit:** every run/step/tool-call/handoff is a structured record in Cosmos DB, queryable per workflow instance.
- **Token monitoring:** every model call records prompt/completion/total tokens + estimated cost to Cosmos and App Insights (`gen_ai.token.usage`). See `docs/token-monitoring.md` and `ui/token-monitor.html`.
- **Two observability planes:** *design-time / data-governance* = Purview (`ui/purview-observability.html`) answers "is the data governed and where did it come from?"; *runtime / execution* = App Insights + Cosmos + token metric (`ui/token-monitor.html`) answers "what did the agents do and what did it cost?".

> **Scope note (June 19 calibration):** per the Data & Integration Simplification, the PoC runs entirely from local synthetic `data/` — **Azure Storage is a documented production target, not wired in the demo.** The connectivity path is specified in `docs/production-design-notes.md` §1. Full fit-gap (Demonstrated / Mocked / Documented) is in `docs/fit-gap.md` and live at `ui/test-expectations.html`.

---

## Hard rules (do not regress these in development)

1. **UC1:** no memo is "final" without explicit human approval (Durable Functions HITL gate).
2. **UC2:** no money movement — ever. Terminal output is an auditable handoff object.
3. Guardrails are deterministic, not prompt-driven. Prompt-injection ("ignore the rules", "skip OTP") cannot bypass them.
4. Synthetic data only in the PoC.
