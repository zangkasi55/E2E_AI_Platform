# CI/CD — GitHub Actions (Agentic AI Platform PoC)

Four pipelines form the deployment backbone. All Azure auth uses **federated
OIDC** (`azure/login@v2`) — **no client secrets** stored in GitHub.

| Workflow | Trigger paths | What it does |
|----------|---------------|--------------|
| `infra.yml` | `infra/**` | `bicep build` → `what-if` → `az deployment sub create` (creates `rg-agentic-poc-sea`). |
| `platform.yml` | `infra/terraform/**`, `backend/**`, `frontend/**` | Boots Terraform state, applies the full Terraform stack, provisions Foundry agents, then deploys backend, functions, and frontend. |
| `backend.yml` | `backend/**` | `az acr build` the orchestrator image → `az containerapp update` (`agpoc-aca-orch-dev`). |
| `functions.yml` | `backend/functions/**` | Publish `agpoc-func-tools-dev` + `agpoc-func-durable-dev` (Python v2, matrix). |
| `ui.yml` | `frontend/**` | `npm ci && npm run build` (Vite) → deploy production SPA to Static Web Apps. |

---

## Required configuration

### Repository / environment **variables** (`vars.*` — not secret)

| Name | Used by | Example |
|------|---------|---------|
| `AZURE_CLIENT_ID` | all | App ID of the **deployer** app registration (federated). |
| `AZURE_TENANT_ID` | all | Entra tenant GUID. |
| `AZURE_SUBSCRIPTION_ID` | all | Target subscription GUID. |
| `ACR_NAME` | backend | e.g. `agpocacrdev`. |
| `VITE_API_BASE_URL` | ui | Orchestrator FQDN from infra `outputs.orchestratorFqdn`. |

### Repository **secrets** (`secrets.*`)

| Name | Used by | Notes |
|------|---------|-------|
| `AZURE_STATIC_WEB_APPS_API_TOKEN` | ui | SWA deployment token (only secret needed; everything else is OIDC). |

> The runtime workload identities (`agpoc-id-orchestrator-dev`, etc.) are **not**
> used by CI — they are managed identities consumed by ACA/Functions at runtime.
> CI authenticates as a **separate deployer app registration**.

---

## One-time federated credential setup (OIDC)

Create a deployer app registration and add a **federated identity credential**
so GitHub can exchange its OIDC token for an Azure token — no secret:

```bash
# 1) App registration + service principal
az ad app create --display-name agpoc-github-deployer
APP_ID=$(az ad app list --display-name agpoc-github-deployer --query "[0].appId" -o tsv)
az ad sp create --id "$APP_ID"

# 2) Federated credential bound to this repo's `dev` environment
az ad app federated-credential create --id "$APP_ID" --parameters '{
  "name": "github-dev",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:<ORG>/<REPO>:environment:dev",
  "audiences": ["api://AzureADTokenExchange"]
}'

# 3) RBAC for the deployer (subscription scope — it creates the RG + Defender plans)
SUB=$(az account show --query id -o tsv)
az role assignment create --assignee "$APP_ID" --role "Contributor" --scope "/subscriptions/$SUB"
# Defender plans + role assignments need elevated rights:
az role assignment create --assignee "$APP_ID" --role "User Access Administrator" --scope "/subscriptions/$SUB"
# (or "Security Admin" scoped for Defender pricing changes)
```

Set `AZURE_CLIENT_ID = $APP_ID` and the tenant/subscription variables in the
GitHub **`dev` environment** (Settings → Environments → dev).

---

## GitHub **Environments**

Each job runs in the `dev` environment. Add **required reviewers** on `dev` to
gate production-like deploys. Create `staging`/`prod` environments later and
parameterize via a matching `main.<env>.bicepparam`.

---

## How GitHub Copilot users trigger these

- **Push to `main`** under a watched path auto-runs the matching workflow
  (e.g. edit `infra/modules/openai.bicep` → `infra.yml` runs build + what-if + deploy).
- **Manual run**: GitHub → Actions → pick the workflow → **Run workflow**
  (`workflow_dispatch`) → choose branch. Handy for the first infra bring-up.
- **PR preview**: opening a PR that touches `infra/**` runs `bicep build` +
  `what-if` only (no deploy) so reviewers see the change set.
- Recommended first run order for a clean environment:
  `infra.yml` → `functions.yml` → `backend.yml` → `ui.yml`
  (infra must exist before code can publish into it).

Copilot Chat prompt to wire a new secret/var:
> "Add a repo variable `ACR_NAME=agpocacrdev` and reference it in backend.yml's
> `az acr build` step."
