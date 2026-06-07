#!/usr/bin/env bash
# =============================================================================
# deploy.sh — One-command deployment for the Agentic AI Platform PoC.
#
# Brings the entire demo online in a single Azure subscription with no manual
# portal steps. Idempotent: re-running updates in place. Configuration, agents
# and agent workflows are all created automatically.
#
#   1. Pre-flight   — verifies az / python / node, login, registers providers
#   2. AI core      — infra/foundry.bicep (Foundry account + project, gpt-4o /
#                     gpt-4o-mini, App Insights, Cosmos audit, Key Vault, UAMI)
#   3. App hosting  — infra/app.bicep (ACR, Container Apps env + orchestrator,
#                     Static Web App, AcrPull + Azure AI User RBAC)
#   4. Backend      — builds the orchestrator image in ACR and rolls the app
#   5. Agents       — 6 Foundry agents + 2 workflow agents (UC1 + UC2)
#   6. Frontend     — builds the React SPA and deploys it to the Static Web App
#   7. Summary      — prints every endpoint
#
# Requires: Azure CLI >= 2.60, Bicep, Python 3.11+, Node 20+, and an identity
# with Owner (or Contributor + User Access Administrator) on the subscription.
# Region note: swedencentral has gpt-4o quota; southeastasia does not.
#
# Usage:
#   ./deploy/deploy.sh
#   RESOURCE_GROUP=rg-scbx-poc LOCATION=swedencentral ./deploy/deploy.sh
#   SKIP_FRONTEND=1 ./deploy/deploy.sh
# =============================================================================
set -euo pipefail

# --- Configuration (override via environment variables) ----------------------
SUBSCRIPTION_ID="${SUBSCRIPTION_ID:-}"
LOCATION="${LOCATION:-swedencentral}"
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-agentic-poc-swc}"
PREFIX="${PREFIX:-agpoc}"
ENV_SUFFIX="${ENV_SUFFIX:-dev}"
PROJECT_NAME="${PROJECT_NAME:-SCBXAIplatformPOC}"
IMAGE_NAME="${IMAGE_NAME:-agpoc-orch}"
SKIP_INFRA="${SKIP_INFRA:-0}"
SKIP_BACKEND="${SKIP_BACKEND:-0}"
SKIP_AGENTS="${SKIP_AGENTS:-0}"
SKIP_FRONTEND="${SKIP_FRONTEND:-0}"

# --- Paths -------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INFRA_DIR="${REPO_ROOT}/infra"
BACKEND_DIR="${REPO_ROOT}/backend"
FRONTEND_DIR="${REPO_ROOT}/frontend"

# --- Helpers -----------------------------------------------------------------
C_CYAN='\033[0;36m'; C_GREEN='\033[0;32m'; C_RED='\033[0;31m'; C_GRAY='\033[0;90m'; C_OFF='\033[0m'
stage() { echo; printf "${C_CYAN}%s\n  %s\n%s${C_OFF}\n" "$(printf '=%.0s' {1..72})" "$1" "$(printf '=%.0s' {1..72})"; }
step()  { printf "${C_GRAY}  -> %s${C_OFF}\n" "$1"; }
ok()    { printf "${C_GREEN}  [OK] %s${C_OFF}\n" "$1"; }
fail()  { printf "${C_RED}  [X] %s${C_OFF}\n" "$1" >&2; exit 1; }
need()  { command -v "$1" >/dev/null 2>&1 || fail "'$1' is not installed or not on PATH. $2"; }
ts()    { date -u +%Y%m%d%H%M%S; }

# =============================================================================
# 1. PRE-FLIGHT
# =============================================================================
stage "1/7  Pre-flight checks"
need az "Install: https://learn.microsoft.com/cli/azure/install-azure-cli"
[[ "${SKIP_INFRA}"    == "1" ]] || need jq      "Install jq: https://stedolan.github.io/jq/download/"
[[ "${SKIP_AGENTS}"   == "1" ]] || need python3 "Install Python 3.11+: https://www.python.org/downloads/"
[[ "${SKIP_FRONTEND}" == "1" ]] || need npm     "Install Node.js 20+: https://nodejs.org/"

step "Verifying Azure login"
az account show >/dev/null 2>&1 || fail "Not logged in. Run 'az login' first."
[[ -n "${SUBSCRIPTION_ID}" ]] && az account set --subscription "${SUBSCRIPTION_ID}"
SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
ok "Subscription: $(az account show --query name -o tsv) (${SUBSCRIPTION_ID})"

step "Ensuring Bicep is installed"
az bicep install >/dev/null 2>&1 || true

step "Registering required resource providers"
for p in Microsoft.App Microsoft.CognitiveServices Microsoft.DocumentDB \
         Microsoft.OperationalInsights Microsoft.Insights Microsoft.KeyVault \
         Microsoft.ContainerRegistry Microsoft.ManagedIdentity Microsoft.Web \
         Microsoft.Authorization; do
  az provider register --namespace "$p" --wait >/dev/null 2>&1 || true
done
ok "Providers registered"

step "Ensuring resource group '${RESOURCE_GROUP}' in '${LOCATION}'"
az group create --name "${RESOURCE_GROUP}" --location "${LOCATION}" \
  --tags project=agentic-ai-poc env="${ENV_SUFFIX}" data=synthetic-only >/dev/null
ok "Resource group ready"

FOUNDRY_OUT=""; APP_OUT=""

# =============================================================================
# 2 + 3. INFRASTRUCTURE
# =============================================================================
if [[ "${SKIP_INFRA}" == "1" ]]; then
  stage "2-3/7  Infrastructure (SKIPPED)"
else
  stage "2/7  AI core (infra/foundry.bicep)"
  step "Deploying Foundry account, project, models, telemetry, Cosmos, Key Vault, identity"
  FOUNDRY_OUT="$(az deployment group create \
    --resource-group "${RESOURCE_GROUP}" \
    --name "foundry-$(ts)" \
    --template-file "${INFRA_DIR}/foundry.bicep" \
    --parameters location="${LOCATION}" prefix="${PREFIX}" env="${ENV_SUFFIX}" projectName="${PROJECT_NAME}" \
    --query properties.outputs -o json)"
  ok "Foundry project endpoint: $(echo "${FOUNDRY_OUT}" | jq -r '.foundryProjectEndpoint.value')"

  stage "3/7  App hosting (infra/app.bicep)"
  step "Deploying Container Registry, Container Apps env + orchestrator, Static Web App, RBAC"
  fv() { echo "${FOUNDRY_OUT}" | jq -r ".$1.value"; }
  APP_OUT="$(az deployment group create \
    --resource-group "${RESOURCE_GROUP}" \
    --name "app-$(ts)" \
    --template-file "${INFRA_DIR}/app.bicep" \
    --parameters \
      location="${LOCATION}" prefix="${PREFIX}" env="${ENV_SUFFIX}" \
      orchestratorIdentityResourceId="$(fv orchestratorIdentityResourceId)" \
      orchestratorIdentityClientId="$(fv orchestratorIdentityClientId)" \
      orchestratorIdentityPrincipalId="$(fv orchestratorIdentityPrincipalId)" \
      foundryAccountName="$(fv foundryAccountName)" \
      foundryProjectEndpoint="$(fv foundryProjectEndpoint)" \
      foundryProjectName="$(fv projectName)" \
      aoaiEndpoint="$(fv aoaiEndpoint)" \
      cosmosEndpoint="$(fv cosmosEndpoint)" \
      keyVaultUri="$(fv keyVaultUri)" \
      appInsightsConnectionString="$(fv appInsightsConnectionString)" \
    --query properties.outputs -o json)"
  ok "Orchestrator FQDN: https://$(echo "${APP_OUT}" | jq -r '.orchestratorFqdn.value')"
  ok "Static Web App:    https://$(echo "${APP_OUT}" | jq -r '.staticWebAppDefaultHostname.value')"
fi

# Resolve downstream names (from outputs or by lookup).
av() { echo "${APP_OUT}" | jq -r ".$1.value"; }
if [[ -n "${APP_OUT}" ]]; then
  ACR_NAME="$(av acrName)"; ACA_NAME="$(av containerAppName)"; SWA_NAME="$(av staticWebAppName)"
  ACA_FQDN="$(av orchestratorFqdn)"
else
  ACR_NAME="$(az acr list -g "${RESOURCE_GROUP}" --query '[0].name' -o tsv)"
  ACA_NAME="${PREFIX}-aca-orch-${ENV_SUFFIX}"
  SWA_NAME="$(az staticwebapp list -g "${RESOURCE_GROUP}" --query '[0].name' -o tsv)"
  ACA_FQDN="$(az containerapp show -n "${ACA_NAME}" -g "${RESOURCE_GROUP}" --query properties.configuration.ingress.fqdn -o tsv)"
fi
if [[ -n "${FOUNDRY_OUT}" ]]; then
  PROJ_ENDPOINT="$(echo "${FOUNDRY_OUT}" | jq -r '.foundryProjectEndpoint.value')"
  FOUNDRY_ACCOUNT="$(echo "${FOUNDRY_OUT}" | jq -r '.foundryAccountName.value')"
else
  PROJ_ENDPOINT="$(az containerapp show -n "${ACA_NAME}" -g "${RESOURCE_GROUP}" --query "properties.template.containers[0].env[?name=='FOUNDRY_PROJECT_ENDPOINT'].value | [0]" -o tsv)"
  FOUNDRY_ACCOUNT="${PREFIX}-aifoundry-${ENV_SUFFIX}"
fi

# =============================================================================
# 4. BACKEND IMAGE
# =============================================================================
if [[ "${SKIP_BACKEND}" == "1" ]]; then
  stage "4/7  Backend image (SKIPPED)"
else
  stage "4/7  Build + deploy orchestrator image"
  [[ -n "${ACR_NAME}" ]] || fail "Could not resolve the Container Registry name."
  TAG="${IMAGE_NAME}-$(date -u +%Y%m%d-%H%M%S)"
  step "Building image in ACR '${ACR_NAME}' (tag ${TAG})"
  az acr build --registry "${ACR_NAME}" \
    --image "${IMAGE_NAME}:${TAG}" --image "${IMAGE_NAME}:latest" \
    --file "${BACKEND_DIR}/Dockerfile" "${BACKEND_DIR}"
  step "Rolling Container App '${ACA_NAME}' to the new image"
  REV="$(az containerapp update --name "${ACA_NAME}" --resource-group "${RESOURCE_GROUP}" \
    --image "${ACR_NAME}.azurecr.io/${IMAGE_NAME}:${TAG}" \
    --query 'properties.latestRevisionName' -o tsv)"
  ok "Active revision: ${REV}"
fi

# =============================================================================
# 5. FOUNDRY AGENTS + WORKFLOWS
# =============================================================================
if [[ "${SKIP_AGENTS}" == "1" ]]; then
  stage "5/7  Foundry agents + workflows (SKIPPED)"
else
  stage "5/7  Provision Foundry agents + workflows"
  [[ -n "${PROJ_ENDPOINT}" ]] || fail "Could not resolve FOUNDRY_PROJECT_ENDPOINT."

  step 'Granting current user "Azure AI User" on the Foundry account (best-effort)'
  ME="$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)"
  FOUNDRY_ID="$(az cognitiveservices account show -n "${FOUNDRY_ACCOUNT}" -g "${RESOURCE_GROUP}" --query id -o tsv 2>/dev/null || true)"
  if [[ -n "${ME}" && -n "${FOUNDRY_ID}" ]]; then
    az role assignment create --assignee-object-id "${ME}" --assignee-principal-type User \
      --role "Azure AI User" --scope "${FOUNDRY_ID}" >/dev/null 2>&1 || true
    step "Waiting 30s for the role assignment to propagate"; sleep 30
  fi

  step "Installing the provisioning dependency (azure-identity)"
  python3 -m pip install --quiet --disable-pip-version-check azure-identity || true

  step "Creating 6 agents + 2 workflow agents (idempotent)"
  FOUNDRY_PROJECT_ENDPOINT="${PROJ_ENDPOINT}" python3 "${BACKEND_DIR}/scripts/provision_foundry_agents.py"
  ok "Agents + workflows provisioned"
fi

# =============================================================================
# 6. FRONTEND
# =============================================================================
if [[ "${SKIP_FRONTEND}" == "1" ]]; then
  stage "6/7  Frontend (SKIPPED)"
else
  stage "6/7  Build + deploy frontend (Static Web App)"
  [[ -n "${SWA_NAME}" ]] || fail "Could not resolve the Static Web App name."
  [[ -n "${ACA_FQDN}" ]] || fail "Could not resolve the orchestrator FQDN."
  pushd "${FRONTEND_DIR}" >/dev/null
  step "Installing dependencies + building (Vite)"
  VITE_API_BASE_URL="https://${ACA_FQDN}" VITE_USE_MOCK="false" npm ci
  VITE_API_BASE_URL="https://${ACA_FQDN}" VITE_USE_MOCK="false" npm run build
  step "Deploying to Static Web App '${SWA_NAME}'"
  SWA_TOKEN="$(az staticwebapp secrets list --name "${SWA_NAME}" --resource-group "${RESOURCE_GROUP}" --query 'properties.apiKey' -o tsv)"
  [[ -n "${SWA_TOKEN}" ]] || fail "Could not read the Static Web App deployment token."
  npx -y @azure/static-web-apps-cli deploy ./dist --deployment-token "${SWA_TOKEN}" --env production
  popd >/dev/null
  ok "Frontend deployed"
fi

# =============================================================================
# 7. SUMMARY
# =============================================================================
stage "7/7  Deployment complete"
echo
echo "  Resource group   : ${RESOURCE_GROUP}"
echo "  Region           : ${LOCATION}"
echo "  Foundry project  : ${PROJECT_NAME}"
[[ -n "${ACA_FQDN}" ]] && echo "  Orchestrator API : https://${ACA_FQDN}"
SWA_HOST="$(az staticwebapp show -n "${SWA_NAME}" -g "${RESOURCE_GROUP}" --query defaultHostname -o tsv 2>/dev/null || true)"
[[ -n "${SWA_HOST}" ]] && echo "  Web UI           : https://${SWA_HOST}"
echo
echo "  Agents : memo-orchestrator, doc-retrieval, financial-ratio, bureau-summary, memo-assembler, banking-controller"
echo "  Flows  : credit-memo-workflow (UC1), banking-control-workflow (UC2)"
echo
ok "All configuration, agents and workflows created."
