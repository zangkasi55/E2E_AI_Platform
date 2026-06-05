# Infrastructure (Bicep) — Agentic AI Platform PoC

Infrastructure-as-Code for the **Agentic AI Platform PoC** (DataX / TechX ×
Microsoft, SCBX context). Everything is parameterized to the canonical names in
[`/working/POC_SPEC.md`](../../../working/POC_SPEC.md) and tagged
`project=agentic-poc`, `env=dev`, `owner=datax-techx`.

> Region: **southeastasia** (Singapore, Thailand-nearest model serving)
> Resource group: **rg-agentic-poc-sea** · Prefix: **agpoc** · Suffix: **dev**

---

## Layout

```
infra/
  main.bicep                      # subscription-scoped composition root (creates the RG)
  main.bicepparam                 # dev parameters
  modules/
    observability.bicep           # Log Analytics + App Insights (+ token-usage savedSearch)
    storage.bicep                 # Storage (ADLS Gen2) + containers synthetic/memos/templates
    keyvault.bicep                # Key Vault (RBAC) + secret placeholders
    cosmos.bicep                  # Cosmos NoSQL: db agentaudit, containers runs/steps/handoffs/tokens
    openai.bicep                  # Azure OpenAI + gpt-4o / gpt-4o-mini deployments
    search.bicep                  # Azure AI Search
    servicebus.bicep              # Service Bus + queue hitl-approvals
    identity.bicep                # 3 user-assigned identities + least-privilege RBAC
    apim.bicep                    # API Management = MCP/agent tool bridge (loads policy XML)
    functions.bicep               # Function Apps: tools + durable HITL (+ Service Bus RBAC)
    containerapps.bicep           # Container Apps env + FastAPI orchestrator
    purview.bicep                 # Microsoft Purview + scanner RBAC on synthetic storage
    defender.bicep                # Defender for Cloud plans (SUBSCRIPTION scope)
  apim/policies/
    inbound-tool-call.xml         # full APIM inbound policy (JWT + scope + PII + rate-limit + log)
  observability/kql/
    token_usage.kql               # saved KQL: by agent / model / cost / per-run timeline
```

---

## Deploy order (encoded as module dependencies in `main.bicep`)

| Phase | Module(s) | Why this order |
|------:|-----------|----------------|
| 1 | `observability` | Everyone sends diagnostics + traces here first. |
| 2 | `storage`, `keyvault`, `cosmos`, `openai`, `search`, `servicebus` | Foundational data/secrets/messaging. Deploy in parallel; only depend on Phase 1. |
| 3 | `identity` | Creates the 3 UAMIs **and** the least-privilege RBAC — needs Phase 2 resources to exist as RBAC scopes. |
| 4 | `apim` | Tool bridge. Backend URL is derived from the (deterministic) Functions name, so APIM can precede Functions. |
| 5 | `functions` | Tool execution + durable HITL. Consumes the tool-bridge UAMI + endpoints; adds Service Bus RBAC. |
| 6 | `containerapps` | FastAPI orchestrator. Consumes the orchestrator UAMI, APIM URL, and all endpoints. |
| 7 | `purview` | Data governance. Grants its scanner identity read on the synthetic storage. |
| 8 | `defender` | **Subscription-scoped** plans (no `scope: rg`). Run last. |

Bicep resolves these automatically from `outputs` references — you do not deploy
modules by hand; `main.bicep` orchestrates the whole graph in one deployment.

---

## How to deploy

```bash
# Subscription-scoped (creates rg-agentic-poc-sea + Defender plans).
az deployment sub create \
  --location southeastasia \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam

# Preview first (what-if) — wired into .github/workflows/infra.yml:
az deployment sub what-if \
  --location southeastasia \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam
```

CI/CD does this via OIDC in [`.github/workflows/infra.yml`](../.github/workflows/infra.yml).

---

## Parameters (`main.bicep`)

| Param | Default | Notes |
|-------|---------|-------|
| `location` | `southeastasia` | Canonical region. |
| `resourceGroupName` | `rg-agentic-poc-sea` | Canonical RG. |
| `prefix` / `env` | `agpoc` / `dev` | Drive every canonical resource name (see `var names`). |
| `tags` | canonical set | `project/env/owner`. |
| `apimPublisherEmail` | placeholder | Set to the real distro list. |
| `orchestratorImage` | quickstart placeholder | `backend.yml` overrides with the ACR tag. |
| `enableStandardCspm` | `false` | Paid CSPM off by default. |
| `enableDefenderPaidPlans` | `true` | Key Vault / Storage / AI plans. Set `false` in shared subs. |

---

## What each module produces (key outputs)

- **observability** → `logAnalyticsId`, `appInsightsConnectionString`, `tokenUsageMetricName` (`gen_ai.token.usage`).
- **storage** → `storageAccountName`, `blobEndpoint`, `dfsEndpoint` (ADLS Gen2).
- **keyvault** → `keyVaultUri`, `keyVaultName` (RBAC scope).
- **cosmos** → `cosmosEndpoint`, `databaseName` (`agentaudit`).
- **openai** → `openAiEndpoint`, `deploymentNames` (`gpt-4o`, `gpt-4o-mini`).
- **search** → `searchEndpoint`.
- **servicebus** → `serviceBusFqdn`, `queueName` (`hitl-approvals`).
- **identity** → `orchestratorClientId`, `toolBridgeClientId`, `uiClientId` + identity resource IDs.
- **apim** → `apimGatewayUrl`, `toolApiPath` → composed `toolBridgeUrl`.
- **functions** → `toolsFunctionAppHostname`, `durableFunctionAppHostname`.
- **containerapps** → `orchestratorFqdn` (UI base URL).
- **purview** → `purviewCatalogEndpoint`.

---

## Production hardening (intentionally NOT in the PoC)

Each module carries a TODO/NOTE where it diverges from production:
- Private Endpoints + `publicNetworkAccess: Disabled` on Storage / KV / Cosmos / AOAI / Search / APIM.
- `disableLocalAuth: true` everywhere (Entra-only).
- Split Service Bus Data Owner into Sender/Receiver.
- Attach an FSI content-filter (RAI policy) to the AOAI deployments.
- Import the full 9-tool OpenAPI into APIM and pin CORS to the SWA origin.

Search the tree for `TODO(` and `NOTE` to find every extension point — they are
written for GitHub Copilot to expand.
