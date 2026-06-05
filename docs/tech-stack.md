# Tech Stack — Agentic AI Platform PoC

Every choice below is Microsoft-native where possible, in-region (Southeast Asia), and selected to (a) prove the control boundary and (b) be buildable with GitHub Copilot in ~2 weeks.

---

## 1. Layer-by-layer

| Layer | Technology | Why |
|---|---|---|
| **Orchestration runtime** | Microsoft Foundry Agent Service + **Semantic Kernel** (connected-agent / delegation) on **Azure Container Apps** (FastAPI) | First-class multi-agent delegation; SK gives planner + tool-calling; Container Apps = simple, identity-aware, scale-to-zero host. |
| **Model serving** | **Azure OpenAI in Microsoft Foundry Models** — `gpt-4o` (reasoning/assembly), `gpt-4o-mini` (cheap sub-steps) | In-region, version-locked, per-step model assignment, content filters, audited. |
| **Retrieval** | **Azure AI Search** | Retrieval restricted to approved/governed sources; hybrid + semantic ranking. |
| **Tool bridge** | **Azure API Management** (MCP server pattern) | The deterministic boundary: OpenAPI tool schemas, JWT/Entra validation, per-call scope/policy, PII filtering, logging, rate limiting. |
| **Tool execution** | **Azure Functions** (Python v2) | Lightweight, identity-bound tool implementations behind APIM. |
| **HITL workflow** | **Azure Durable Functions** + **Service Bus** (`hitl-approvals`) | Durable pause/resume, checkpoint replay, idempotency for human approval. |
| **Identity** | **Microsoft Entra ID** (workload identities, app registrations, federated creds) | Per-agent unique identity; no shared service accounts; token validation at tool call. |
| **Secrets** | **Azure Key Vault** | No secrets in code/config; Key Vault references in app settings. |
| **Data governance** | **Microsoft Purview** | Classification, PII scanning, data map over approved sources. |
| **Security posture** | **Microsoft Defender for Cloud** | Threat protection + posture for the PoC subscription. |
| **Audit + state** | **Azure Cosmos DB** (NoSQL) | Per-instance, queryable audit (`runs`, `steps`, `handoffs`, `tokens`). |
| **Observability** | **Application Insights** + **Azure Monitor / Log Analytics** + Foundry Tracing | Distributed traces, custom metric `gen_ai.token.usage`, KQL dashboards. |
| **Storage** | **Azure Blob + ADLS Gen2** (`synthetic`, `memos`, `templates`) | The decided group storage layer. **Documented production target, not wired in the PoC** — per the June 19 calibration the demo runs from local synthetic `data/`; connectivity path (managed identity → `Storage Blob Data Reader`, Private Link/Entra) is specified in `production-design-notes.md` §1. |
| **Eventing** | **Azure Service Bus** | HITL approval queue; decouples reviewer action from workflow. |
| **UI (prototype)** | Self-contained **HTML + CSS + vanilla JS** (offline) | Instant demo, no build, shows agent flow + token monitor. |
| **UI (production target)** | **React 18 + TypeScript + Vite**, Fluent-inspired | Component model maps 1:1 to the prototype; see `ui/DESIGN.md`. |
| **IaC** | **Bicep** (modular) | Native Azure, parameterized, Copilot-friendly. |
| **CI/CD** | **GitHub Actions** (OIDC `azure/login`) | Matches the user's GitHub Copilot workflow; no stored cloud creds. |

---

## 2. Backend dependencies (Python 3.11)

```
fastapi · uvicorn · pydantic · python-dotenv
semantic-kernel
openai                       # Azure OpenAI client
azure-identity               # DefaultAzureCredential / workload identity
azure-cosmos                 # audit + token store
azure-monitor-opentelemetry  # traces + custom token metric
httpx                        # tool calls through APIM
```

A `MOCK_MODE=true` switch makes the whole backend runnable with **zero Azure** — model calls return canned responses and tokens are estimated (`len/4` heuristic). This keeps the demo and UI unblocked while infra is provisioned.

---

## 3. Why these vs. alternatives

- **Semantic Kernel over a hand-rolled loop:** native connected-agent delegation and tool-calling, less glue code for Copilot to maintain.
- **APIM as the tool bridge over calling Functions directly:** APIM *is* the deterministic control point — moving scope/PII/policy out of the model and into a managed gateway is the whole thesis of the PoC.
- **Container Apps over AKS:** AKS is overkill for a PoC; Container Apps gives managed identity, ingress, and scale-to-zero with far less ops.
- **Durable Functions over a custom state machine:** durable pause/resume + replay are exactly the HITL guarantees we must demonstrate.
- **Cosmos DB over SQL for audit:** schema-flexible per-step records, partition by `run_id`, cheap point/range reads for trace queries.
- **Bicep over Terraform:** native, fewer moving parts for an all-Azure PoC; Copilot autocompletes it well.

---

## 4. Environments & config

- One environment: `dev` (suffix on every resource).
- All config via env vars (`.env.example` provided), secrets via Key Vault references.
- Canonical resource names live in `infra/main.bicepparam` and `backend/.env.example` — keep them in sync (they trace to the spec).

---

## 5. Model assignment policy (per-step, version-locked)

| Step / agent | Model | Rationale |
|---|---|---|
| `memo_orchestrator` planning, `memo_assembler` | `gpt-4o` | Highest-quality synthesis. |
| `doc_retrieval`, `financial_ratio`, `bureau_summary` | `gpt-4o-mini` | Cheap, structured sub-tasks. |
| `banking_controller` intent/slots/conditional | `gpt-4o-mini` | Deterministic tools do the heavy lifting; model only parses. |

Model + version are recorded on every step and every token record, so cost and behavior are fully attributable.
