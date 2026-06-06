# Terraform IaC — Agentic AI Platform PoC

This is the **Terraform parity** of the Bicep IaC in [`infra/`](../). It provisions
the identical Microsoft-native agentic platform (`dev` environment, Southeast
Asia) using the `azurerm` + `azapi` providers. Use **either** Bicep **or**
Terraform — they target the same resource group and produce the same topology.

> ⚠️ Do **not** run both Bicep and Terraform against the same resource group at
> the same time — they each own the resources and would fight over state.

---

## What gets deployed

| File | Resources |
|------|-----------|
| `main.tf` | Resource group `rg-agentic-poc-sea` |
| `observability.tf` | Log Analytics `agpoc-law-dev`, App Insights `agpoc-appi-dev`, saved KQL search |
| `storage.tf` | ADLS Gen2 `agpocstoragedev` (HNS, soft-delete, 3 containers, diagnostics) |
| `keyvault.tf` | Key Vault `agpoc-kv-dev` (RBAC, purge protection) + 5 placeholder secrets |
| `cosmos.tf` | Cosmos `agpoc-cosmos-dev` → DB `agentaudit` → containers runs/steps/handoffs/tokens |
| `openai.tf` | Azure OpenAI `agpoc-aoai-dev` + gpt-4o & gpt-4o-mini deployments |
| `search.tf` | Azure AI Search `agpoc-search-dev` (basic, semantic free) |
| `servicebus.tf` | Service Bus `agpoc-sb-dev` + session-enabled `hitl-approvals` queue |
| `identity.tf` | 3 user-assigned identities + least-privilege role assignments (incl. Cosmos data-plane) |
| `apim.tf` | API Management `agpoc-apim-dev`, named values, tool API, raw policy, product, subscription |
| `functions.tf` | Y1 plan + tools & durable Function Apps (Python 3.11) |
| `containerapps.tf` | Container Apps env + FastAPI orchestrator (external ingress :8000) |
| `purview.tf` | New **or** existing Purview account + Storage Blob Data Reader grant |
| `defender.tf` | Defender for Cloud plans (CSPM, Key Vault, Storage V2, AI) at subscription scope |
| `staticwebapp.tf` | Static Web App for the React SPA (optional) |
| `foundry.tf` | Live AI Foundry stack in `swedencentral` (project, models, telemetry, audit store, secrets, identity) |

Variable defaults mirror [`infra/main.bicepparam`](../main.bicepparam).

---

## Prerequisites

- Terraform >= 1.6
- Azure CLI, logged in: `az login`
- Subscription selected: `az account set --subscription <id>`
- Permission to create resources **and** assign roles (Owner or
  User Access Administrator) — the config creates RBAC role assignments and
  subscription-scoped Defender plans.
- Quota for Azure OpenAI gpt-4o in the chosen region.
- Quota for gpt-4o in `swedencentral` for the Foundry stack.

---

## Deploy

```bash
cd infra/terraform

# (optional) customize — every value already has a default
cp terraform.tfvars.example terraform.tfvars

terraform init
terraform plan -out tfplan
terraform apply tfplan
```

To reproduce the exact canonical `dev` environment, you can skip `terraform.tfvars`
entirely and just `terraform init && terraform apply`.

### Useful outputs

```bash
terraform output orchestrator_fqdn        # UI points VITE_API_BASE_URL here
terraform output tool_bridge_url          # APIM tool bridge base URL
terraform output openai_endpoint
terraform output -raw application_insights_connection_string
```

---

## Post-deploy wiring

1. **Build & push the orchestrator image**, then set `orchestrator_image` to your
   ACR image (`<acr>.azurecr.io/orchestrator:<tag>`) and re-apply, or update the
   Container App via CI (see `.github/workflows/backend.yml`).
2. **Rotate Key Vault secrets** — the five secrets deploy with `REPLACE_ME`
   placeholders. The `value` is `ignore_changes`d so real secrets survive applies.
3. **Deploy the tool/durable Function code** (`.github/workflows/functions.yml`).
4. **Deploy the SPA** to the Static Web App (`.github/workflows/ui.yml`).
5. **Provision Foundry agents** by running `backend/scripts/provision_foundry_agents.py`
  after Terraform finishes. The script reads the `foundry_project_endpoint`
  output and writes `backend/app/foundry_agent_ids.json`.

---

## Notes & design choices

- **Purview**: Azure allows one Purview account per tenant, so the default
  (`use_existing_purview = true`) references `pview-isaru66-default-001`. Set it
  to `false` to create `agpoc-purview-dev` instead.
- **Foundry**: the `foundry.tf` stack lives in a separate resource group in
  `swedencentral` and is the source of truth for the live prompt agents used by
  `USE_FOUNDRY_AGENTS=true`.
- **Cosmos data-plane RBAC**: document read/write uses
  `azurerm_cosmosdb_sql_role_assignment` (Cosmos built-in *Data Contributor*),
  which is distinct from Azure RBAC `azurerm_role_assignment`.
- **Defender plans** are `azurerm_security_center_subscription_pricing` at
  subscription scope — they affect the whole subscription, not just this RG.
- **OpenAI deployments** are serialized with `depends_on` because the Cognitive
  Services control plane rejects parallel deployment writes on one account.
- **APIM Developer SKU** takes ~30–45 minutes to provision on first apply.

---

## Destroy

```bash
terraform destroy
```

> Key Vault has purge protection enabled; a destroyed vault is recoverable for
> the soft-delete window and the name cannot be reused until purged.
