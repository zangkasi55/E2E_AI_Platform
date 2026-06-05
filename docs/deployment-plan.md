# Deployment Plan — Agentic AI Platform PoC

**Partners:** DataX / TechX × Microsoft (SCBX Group context)
**Region:** Southeast Asia (`southeastasia`, Singapore — Thailand-nearest serving)
**Resource group:** `rg-agentic-poc-sea` · **Prefix:** `agpoc` · **Env:** `dev`
**Data:** synthetic only (no production/PII) · **Deadline:** **2026-06-19**
**Today:** 2026-06-05 (T-14 days)

This plan is the operational companion to the Bicep in [`infra/`](../infra/) and
the pipelines in [`.github/workflows/`](../.github/workflows/). Every resource
name below is canonical (see [`POC_SPEC.md`](../../../working/POC_SPEC.md)).

---

## 1. Prerequisites

### Subscription & permissions
- An Azure subscription where you (or the deployer SP) hold **Owner** or
  **Contributor + User Access Administrator** (RBAC role assignments + Defender
  pricing are part of the deploy).
- Ability to create **Entra app registrations** (Application Developer or higher).
- Accept that `defender.bicep` changes **subscription-scoped** pricing — clear it
  with the subscription owner if the sub is shared.

### Region quota (do this first — long pole)
- **Azure OpenAI** capacity in `southeastasia` for `gpt-4o` (20K TPM) and
  `gpt-4o-mini` (50K TPM). Request a quota increase **now** if the default is
  lower; approval can take 1–3 business days.
- Confirm Azure OpenAI, API Management (Developer), Container Apps, Cosmos DB,
  AI Search, Purview, and Service Bus are all available in `southeastasia`.

### Tooling
- `az` CLI ≥ 2.60, `az bicep` ≥ 0.28, Docker not required (CI uses `az acr build`).
- A GitHub repo with the `dev` **Environment** + OIDC federated credential
  configured (see [`.github/workflows/README.md`](../.github/workflows/README.md)).

### Entra app registrations (created before/with identity phase — see §4)
- `agpoc-orchestrator`, `agpoc-tool-bridge`, `agpoc-ui` (canonical), plus a
  separate `agpoc-github-deployer` for CI OIDC.

---

## 2. Phase-by-phase deploy order

> The single `az deployment sub create` runs **all** phases (Bicep resolves the
> dependency graph). The phases below are how to **validate** and, if needed,
> **roll back** incrementally. Phase numbers match `main.bicep` comments and
> `infra/README.md`.

### Phase 0 — Entra prep (manual, pre-deploy)
- **Creates:** 3 runtime app regs + deployer app reg + federated credential +
  API scopes/app-roles on `agpoc-tool-bridge` (see §4).
- **Validate:** `az ad app list --display-name agpoc-tool-bridge` returns the
  app with `api://agpoc-tool-bridge` + roles `tools.read`, `tools.execute`,
  `tools.handoff`.
- **Rollback:** delete the app registrations (no infra created yet).

### Phase 1 — Observability (`observability.bicep`)
- **Creates:** `agpoc-law-dev` (Log Analytics), `agpoc-appi-dev` (App Insights,
  workspace-based), token-usage `savedSearch`.
- **Validate:** App Insights shows "workspace-based"; connection string output
  is non-empty.
- **Rollback:** delete the two resources; nothing depends on them yet.

### Phase 2 — Data / secrets / messaging
- **Creates:** `agpocstoragedev` (ADLS Gen2 + `synthetic`/`memos`/`templates`),
  `agpoc-kv-dev` (+ secret placeholders), `agpoc-cosmos-dev` (`agentaudit` →
  `runs`/`steps`/`handoffs`/`tokens`, all pk `/run_id`), `agpoc-aoai-dev`
  (+ `gpt-4o`, `gpt-4o-mini`), `agpoc-search-dev`, `agpoc-sb-dev`
  (+ `hitl-approvals`).
- **Validate:**
  - `az storage container list` shows the 3 containers.
  - `az cosmosdb sql container list` shows the 4 containers, pk `/run_id`.
  - `az cognitiveservices account deployment list` shows both models `Succeeded`.
- **Rollback:** delete individual resources; KV has purge-protection (soft-delete
  7 days) — to fully reuse the name, `az keyvault purge agpoc-kv-dev`.

### Phase 3 — Identity + RBAC (`identity.bicep`)
- **Creates:** UAMIs `agpoc-id-orchestrator-dev`, `agpoc-id-toolbridge-dev`,
  `agpoc-id-ui-dev`; least-privilege role assignments to KV (Secrets User), AOAI
  (OpenAI User), Search (Index Data Reader), Storage (Blob Data Reader), and the
  Cosmos data-plane Data Contributor role.
- **Validate:** `az role assignment list --assignee <orchestratorPrincipalId>`
  shows exactly the 4 Azure roles; `az cosmosdb sql role assignment list` shows
  the data-plane grant.
- **Rollback:** delete the role assignments + UAMIs (downstream apps not yet up).

### Phase 4 — APIM tool bridge (`apim.bicep`)
- **Creates:** `agpoc-apim-dev` (Developer SKU), `agent-tools` API with the
  inbound policy (JWT + scope + PII redaction + rate-limit + logging), App
  Insights logger, `agent-tools-product` + `orchestrator-sub` subscription.
- **Validate:** APIM provisioning **takes 30–45 min** (Developer SKU) — start
  this early. Confirm the policy attached (`az apim api policy show`).
- **Rollback:** delete the API/product/subscription, or the whole service.
- **Note:** the tool backend URL points at the (not-yet-published) Functions
  host; that is fine — APIM only proxies at call time.

### Phase 5 — Functions (`functions.bicep`)
- **Creates:** `agpoc-func-tools-dev`, `agpoc-func-durable-dev` (Consumption,
  Python 3.11), the runtime storage `agpocfxstordev`, Service Bus Data Owner
  RBAC for the tool-bridge identity.
- **Validate:** both apps `Running`; app settings show Key Vault references
  resolving (`az functionapp config appsettings list`); managed identity bound.
- **Rollback:** delete the two apps + plan + `agpocfxstordev`.

### Phase 6 — Container Apps (`containerapps.bicep`)
- **Creates:** ACA environment `agpoc-aca-env-dev`, orchestrator app
  `agpoc-aca-orch-dev` (external ingress :8000, orchestrator UAMI).
- **Validate:** `orchestratorFqdn` output resolves; `GET /healthz` returns 200
  after `backend.yml` pushes the real image.
- **Rollback:** delete the app (env can stay for re-deploys).

### Phase 7 — Purview (`purview.bicep`)
- **Creates:** `agpoc-purview-dev` + scanner Blob Data Reader on `agpocstoragedev`.
- **Validate:** account `Succeeded`; scanner identity has the storage role.
- **Rollback:** delete the account (releases the managed RG `*-managed`).

### Phase 8 — Defender for Cloud (`defender.bicep`, **subscription scope**)
- **Creates/updates:** CSPM tier + Defender plans (Key Vault / Storage / AI).
- **Validate:** `az security pricing list` shows the expected tiers.
- **Rollback:** set the plan(s) back to `Free`
  (`az security pricing create -n KeyVaults --tier Free`).

---

## 3. Post-infra application bring-up

1. `functions.yml` → publish tool + durable code.
2. `backend.yml` → build orchestrator image, push to ACR, update ACA (this also
   replaces the placeholder image set by infra).
3. `ui.yml` → build Vite UI, deploy to Static Web Apps; set `VITE_API_BASE_URL`
   to `orchestratorFqdn`.
4. Seed synthetic data: upload `data/credit_memo/*` and `data/banking/*` to the
   `synthetic` container; create the AI Search `credit-docs` index/indexer.

---

## 4. Entra ID setup (identities, scopes, RBAC)

| App registration | Purpose | Key config |
|------------------|---------|------------|
| `agpoc-orchestrator` | Orchestrator workload identity (paired with UAMI `agpoc-id-orchestrator-dev`). | Requests delegated/app scope `tools.execute` when calling APIM. |
| `agpoc-tool-bridge` | The protected tool API audience. | **Expose an API** `api://agpoc-tool-bridge`; define **app roles / scopes**: `tools.read` (read tools — search/get), `tools.execute` (compute/render), `tools.handoff` (UC2 `request_transaction_handoff`). |
| `agpoc-ui` | UI sign-in (paired with `agpoc-id-ui-dev`). | Delegated sign-in only; calls the orchestrator, never tools directly. |
| `agpoc-github-deployer` | CI/CD OIDC. | Federated credential `repo:<org>/<repo>:environment:dev`; Contributor + User Access Administrator on the subscription. |

**Workload identity model:** runtime apps use **user-assigned managed
identities** (no secrets). `AZURE_CLIENT_ID` app setting selects which UAMI
`DefaultAzureCredential` uses. The orchestrator acquires an Entra token for
`api://agpoc-tool-bridge` and presents it to APIM; APIM's `validate-jwt` +
scope check (deterministic zone) authorize the specific tool.

**Who gets what RBAC (least privilege):**
- orchestrator UAMI → KV Secrets User, AOAI OpenAI User, Search Index Data
  Reader, Storage Blob Data Reader, Cosmos Data Contributor.
- tool-bridge UAMI → same data roles **+** Service Bus Data Owner (HITL queue).
- ui UAMI → **no** data-plane Azure roles (calls orchestrator only).
- Purview scanner identity → Storage Blob Data Reader on `agpocstoragedev`.

---

## 5. APIM-as-tool-bridge configuration

1. **Named values** (created by Bicep): `tenant-id`, `tool-bridge-audience`,
   `required-scope`, `tools-backend-url`. Confirm in APIM → Named values.
2. **Import the tool OpenAPI:** publish the 9-tool contract from
   `agpoc-func-tools-dev` and import into the `agent-tools` API (`format: openapi`).
   Until then the API proxies all paths to the Functions host.
3. **Apply the inbound policy:** Bicep attaches
   [`infra/apim/policies/inbound-tool-call.xml`](../infra/apim/policies/inbound-tool-call.xml)
   at the API scope. Per-operation, set header `x-required-scope` to bind a
   tighter scope (e.g. `request_transaction_handoff` → `tools.handoff`).
4. **Product + subscription:** `agent-tools-product` is published with
   `orchestrator-sub`. Copy its key into KV secret `apim-subscription-key`
   (`az apim subscription show --query primaryKey` → `az keyvault secret set`).
5. **Verify controls end-to-end:**
   - Call a tool **without** a token → `401`.
   - Call with a token lacking the scope → `403 insufficient_scope`.
   - Exceed 60 calls/min → `429` (rate-limit).
   - Confirm PII fields are masked in the response (redaction stub).
   - Confirm the call appears in App Insights (logger).

---

## 6. Purview setup (governance + PII scan)

1. **Register data source:** add `agpocstoragedev` (ADLS Gen2) to the Purview
   data map (the scanner identity already has Blob Data Reader).
2. **Run a scan** over `synthetic`/`memos`/`templates` using the default + custom
   rule set (National ID / Phone / Account Number classifiers).
3. **Review classifications:** confirm the synthetic fields flagged as PII; use
   this list to extend the APIM `find-and-replace` redaction in
   `inbound-tool-call.xml`.
4. **Publish glossary/classifications:** mark the registered, classified sources
   as **approved sources** — the `doc_retrieval` agent only retrieves from
   sources governed here.
5. **Validate:** scan status `Succeeded` in Purview; `DataSensitivityLogEvent`
   rows appear in `agpoc-law-dev`.

---

## 7. Token-usage monitoring bring-up

1. **Confirm the metric is flowing:** after the first orchestrator run, query
   App Insights for `customEvents | where name == "gen_ai.token.usage"` — rows
   must carry `run_id/agent/step/model/total_tokens/est_cost_usd/use_case`.
2. **Import KQL:** load
   [`infra/observability/kql/token_usage.kql`](../infra/observability/kql/token_usage.kql)
   queries 1–6 into the workspace (savedSearches / a Workbook).
3. **Pin a Workbook/dashboard:** tiles = tokens-by-agent, tokens-by-model,
   cumulative cost, top runs by cost, per-run timeline. Pin to a shared
   dashboard for the demo.
4. **Cross-check Cosmos:** the same records exist in `agentaudit/tokens`
   (pk `/run_id`) — the UI Token Monitor reads these for per-run detail.

---

## 8. Cutover checklist — June 19 demo

- [ ] Infra deployed (`infra.yml` green); all outputs captured.
- [ ] Entra apps + scopes + federated credential in place.
- [ ] Functions published; APIM proxying tools; subscription key in KV.
- [ ] Orchestrator image deployed; `/healthz` 200; UAMI has AcrPull.
- [ ] UI deployed; `VITE_API_BASE_URL` set; loads against the orchestrator.
- [ ] Synthetic data uploaded; AI Search index built.
- [ ] Purview scan run; PII classifications reviewed; redaction list updated.
- [ ] Defender plans at expected tiers.
- [ ] Token Monitor showing live `gen_ai.token.usage`; Workbook pinned.
- [ ] **APIM negative tests pass** (401 / 403 / 429 / redaction).

### Run both use cases end to end
- **UC1 — Credit Memo (read-only, HITL):** loan-officer request → `memo_orchestrator`
  plans → `doc_retrieval`/`financial_ratio`/`bureau_summary` call tools via APIM →
  `memo_assembler` drafts → **Durable HITL pause** (approval on `hitl-approvals`,
  Teams reviewer approves/edits) → final audited memo in `memos`. **No memo is
  final without human approval.**
- **UC2 — Conversational Banking (deterministic):** "check balance; if > 5000 THB
  transfer 2000 to mom" → `banking_controller` decomposes intent → `get_balance`,
  `resolve_payee`, `check_transfer_eligibility` via APIM (scope-gated) → terminal
  `request_transaction_handoff` emits a handoff object with
  `requires_confirmation:true`, `requires_step_up_auth:true`. **No money moves.**

---

## 9. Timeline (T-14 → demo)

| Date | Window | Milestone |
|------|--------|-----------|
| **Jun 5–6** | Day 0–1 | Submit AOAI quota request; create Entra apps + scopes + deployer OIDC; wire GitHub `dev` env vars. |
| **Jun 7–8** | Day 2–3 | Run `infra.yml` (start APIM early — 30–45 min). Validate Phases 1–3. Seed synthetic data. |
| **Jun 9–10** | Day 4–5 | Publish Functions + tool OpenAPI into APIM; verify APIM negative tests. Build Search index. |
| **Jun 11–12** | Day 6–7 | Deploy orchestrator (`backend.yml`); wire Semantic Kernel agents; UC1 happy path. |
| **Jun 13** | Day 8 | Durable HITL + Teams approval loop; UC1 end to end with audit in Cosmos. |
| **Jun 14–15** | Day 9–10 | UC2 deterministic flow + handoff object; UI (`ui.yml`) + Token Monitor panel. |
| **Jun 16** | Day 11 | Purview scan + classifications; finalize PII redaction list in APIM. |
| **Jun 17** | Day 12 | Defender review; full dry-run of both use cases; pin Workbook/dashboard. |
| **Jun 18** | Day 13 | **Freeze.** Rehearse demo; cutover checklist; capture screenshots/fallback recording. |
| **Jun 19** | Demo | Present UC1 + UC2 live; show governance (APIM 403/redaction), HITL pause, token/cost dashboard. |

Buffer is intentionally front-loaded around the two long poles: **AOAI quota**
and **APIM provisioning**.

---

## 10. Develop with GitHub Copilot

**Recommended repo open order** (so Copilot has maximal context):
1. `working/POC_SPEC.md` — the single source of truth (pin it open).
2. `infra/README.md` → `infra/main.bicep` → the module you're editing.
3. `docs/deployment-plan.md` (this file).
4. `.github/workflows/README.md` + the relevant workflow.
5. `backend/` and `ui/` as you implement the agents/tools/UI.

**Where the TODOs live** — grep the tree:
- `grep -rn "TODO(" infra/ .github/` — operator/Copilot extension points.
- `grep -rn "NOTE" infra/modules` — production-hardening divergences.
Hot spots: AOAI RAI/content-filter (`openai.bicep`), private endpoints
(`storage.bicep`), full tool OpenAPI import + per-op scopes (`apim.bicep`,
`inbound-tool-call.xml`), ACR `AcrPull` for the orchestrator (`backend.yml`),
UI host choice SWA-vs-ACA (`ui.yml`).

**Copilot prompts to scaffold the remaining wiring:**
- *"In `apim.bicep`, add an `apis/operations` resource per tool from the canonical
  catalog and set `x-required-scope` per operation (`search_documents`→`tools.read`,
  `request_transaction_handoff`→`tools.handoff`)."*
- *"Generate `backend/scripts/create_search_index.py` that builds the `credit-docs`
  index + indexer over the `synthetic` blob container using azure-search-documents."*
- *"Add `infra/modules/privateendpoints.bicep` for Storage (blob+dfs), Key Vault,
  Cosmos, AOAI, Search, and APIM; flip each module's `publicNetworkAccess` to
  Disabled behind a feature flag."*
- *"In `functions.bicep`, switch the plan to Flex Consumption (sku FC1) and add
  `functionAppConfig.deployment` pointing at a deployment container in
  `agpocfxstordev`."*
- *"Write the Durable Functions HITL orchestrator in `backend/functions/durable`
  that posts an approval to `hitl-approvals` (sessionId = run_id) and waits for
  the external event `ApprovalReceived`."*
- *"Emit the canonical token record after each model call: write to Cosmos
  `tokens` (pk /run_id) and track the `gen_ai.token.usage` metric via
  azure-monitor-opentelemetry."*
