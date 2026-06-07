# Deploy the Agentic AI Platform PoC

One command provisions **everything** into your own Azure subscription and brings
the demo fully online — infrastructure, configuration, the six Foundry agents,
and both agent **workflows** (UC1 credit-memo, UC2 banking-control). No manual
portal steps.

| Platform | Command |
|----------|---------|
| Windows / PowerShell 7+ | `./deploy/deploy.ps1` |
| Linux / macOS / WSL | `./deploy/deploy.sh` |

---

## What it deploys

| Stage | Creates |
|------:|---------|
| 1. Pre-flight | Verifies tooling + login, registers resource providers, creates the resource group |
| 2. AI core (`infra/foundry.bicep`) | Foundry account + project, `gpt-4o` + `gpt-4o-mini`, App Insights, Cosmos audit store, Key Vault, orchestrator managed identity + RBAC |
| 3. App hosting (`infra/app.bicep`) | Container Registry, Container Apps environment + orchestrator Container App, Static Web App, `AcrPull` + `Azure AI User` role assignments |
| 4. Backend | Builds the orchestrator image in ACR and rolls the Container App to it |
| 5. Agents + workflows | 6 agents (`memo-orchestrator`, `doc-retrieval`, `financial-ratio`, `bureau-summary`, `memo-assembler`, `banking-controller`) and 2 workflow agents (`credit-memo-workflow`, `banking-control-workflow`) |
| 6. Frontend | Builds the React SPA and deploys it to the Static Web App |
| 7. Summary | Prints the orchestrator API + Web UI URLs |

Everything is **idempotent** — re-running updates in place.

---

## Prerequisites

- **Azure CLI** ≥ 2.60 (`az --version`) and **Bicep** (the script installs it if missing)
- **Python** 3.11+ (for agent provisioning) and **Node** 20+ (for the frontend)
- An Azure identity with **Owner** — or **Contributor + User Access Administrator** —
  on the target subscription (the deploy creates RBAC role assignments)
- **Azure OpenAI `gpt-4o` quota** in the target region.
  `swedencentral` has quota; `southeastasia` does **not**.
- Logged in: `az login` (and `az account set --subscription <id>` if you have several)

---

## Run it

```powershell
# Windows (PowerShell 7+)
az login
./deploy/deploy.ps1
```

```bash
# Linux / macOS / WSL
az login
chmod +x ./deploy/deploy.sh
./deploy/deploy.sh
```

### Customize

Defaults target a clean, self-consistent `dev` stack. Override as needed:

```powershell
./deploy/deploy.ps1 `
  -SubscriptionId <sub-guid> `
  -ResourceGroup  rg-scbx-poc `
  -Location       swedencentral `
  -Prefix         agpoc `
  -Env            dev `
  -ProjectName    SCBXAIplatformPOC
```

```bash
SUBSCRIPTION_ID=<sub-guid> \
RESOURCE_GROUP=rg-scbx-poc \
LOCATION=swedencentral \
PROJECT_NAME=SCBXAIplatformPOC \
./deploy/deploy.sh
```

> **Tip:** deploy into a **fresh resource group** for a clean, isolated stack.

### Re-run only part of it

| Goal | PowerShell | Bash |
|------|-----------|------|
| Skip infra | `-SkipInfra` | `SKIP_INFRA=1` |
| Skip backend image | `-SkipBackend` | `SKIP_BACKEND=1` |
| Skip agents/workflows | `-SkipAgents` | `SKIP_AGENTS=1` |
| Skip frontend | `-SkipFrontend` | `SKIP_FRONTEND=1` |

Example — re-provision just the agents and workflows:

```bash
SKIP_INFRA=1 SKIP_BACKEND=1 SKIP_FRONTEND=1 ./deploy/deploy.sh
```

---

## How "agents + workflows auto-create" works

The agent definitions (instructions, model, guardrails) and the two workflow
graphs are committed in the repo, and the deploy script applies them every run:

- Agents and workflow YAML live in
  [`backend/scripts/`](../backend/scripts/) — the catalog in
  [`provision_foundry_agents.py`](../backend/scripts/provision_foundry_agents.py)
  plus [`credit_memo_workflow.yaml`](../backend/scripts/credit_memo_workflow.yaml)
  and [`banking_control_workflow.yaml`](../backend/scripts/banking_control_workflow.yaml).
- The provisioner is **idempotent**: it creates missing agents/workflows, updates
  drifted instructions to a new version, and leaves unchanged ones alone. The
  `logical_name → agent_version_id` map is written to
  `backend/app/foundry_agent_ids.json` so the orchestrator binds to the live
  Foundry agents at runtime (`USE_FOUNDRY_AGENTS=true`).

To change an agent's behavior, edit its `instructions` in the catalog (or a
workflow YAML) and re-run with `-SkipInfra -SkipBackend -SkipFrontend`.

---

## After it finishes

The summary prints two URLs:

- **Web UI** — the Static Web App. Open it, go to **Credit Memo** or
  **Conversational Banking**, and run a scenario.
- **Orchestrator API** — the Container App (`/healthz` returns `200`).

The agents and workflows appear in the **Microsoft Foundry** portal under your
project (Agents, and Workflows (Preview)).

---

## Teardown

```bash
az group delete --name <resource-group> --yes --no-wait
```

> Key Vault has soft-delete enabled; its name is reserved for the retention
> window. Purge with `az keyvault purge --name <vault>` to reuse it immediately.

---

## CI/CD alternative

For pipeline-based deployment (federated OIDC, remote Terraform state), use the
GitHub Actions workflow [`.github/workflows/platform.yml`](../.github/workflows/platform.yml),
which performs the same end-to-end flow on `workflow_dispatch`.
