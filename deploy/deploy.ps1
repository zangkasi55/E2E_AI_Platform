#requires -Version 7.0
<#
.SYNOPSIS
  One-command deployment for the Agentic AI Platform PoC.

.DESCRIPTION
  Provisions the entire stack into a single Azure subscription and brings the
  demo fully online — no manual portal steps:

    1. Pre-flight   — verifies az / python / node, login, registers providers
    2. AI core      — deploys infra/foundry.bicep (Foundry account + project,
                      gpt-4o / gpt-4o-mini, App Insights, Cosmos audit store,
                      Key Vault, orchestrator managed identity + RBAC)
    3. App hosting  — deploys infra/app.bicep (Container Registry, Container
                      Apps env, orchestrator Container App, Static Web App,
                      AcrPull + Azure AI User role assignments)
    4. Backend      — builds the orchestrator image in ACR and rolls the
                      Container App to it
    5. Agents       — provisions the 6 Foundry agents + 2 workflow agents
                      (UC1 credit-memo, UC2 banking-control) — idempotent
    6. Frontend     — builds the React SPA and deploys it to the Static Web App
    7. Summary      — prints every endpoint

  Everything is idempotent: re-running updates in place. Configuration, agents
  and agent workflows are all created automatically.

.EXAMPLE
  ./deploy/deploy.ps1

.EXAMPLE
  ./deploy/deploy.ps1 -ResourceGroup rg-scbx-poc -Location swedencentral -ProjectName SCBXAIplatformPOC

.NOTES
  Requires: Azure CLI >= 2.60, Bicep, Python 3.11+, Node 20+, and an Azure
  identity with Owner (or Contributor + User Access Administrator) on the
  target subscription (RBAC role assignments are part of the deploy).
  Region note: swedencentral has gpt-4o quota; southeastasia does not.
#>
[CmdletBinding()]
param(
  [string]$SubscriptionId,
  [string]$Location       = 'swedencentral',
  [string]$ResourceGroup  = 'rg-agentic-poc-swc',
  [string]$Prefix         = 'agpoc',
  [string]$Env            = 'dev',
  [string]$ProjectName    = 'SCBXAIplatformPOC',
  [string]$ImageName      = 'agpoc-orch',

  [switch]$SkipInfra,
  [switch]$SkipBackend,
  [switch]$SkipAgents,
  [switch]$SkipFrontend
)

$ErrorActionPreference = 'Stop'
$ProgressPreference     = 'SilentlyContinue'

# --- Resolve paths (script lives in <repo>/deploy) ---------------------------
$RepoRoot   = Split-Path -Parent $PSScriptRoot
$InfraDir   = Join-Path $RepoRoot 'infra'
$BackendDir = Join-Path $RepoRoot 'backend'
$FrontendDir= Join-Path $RepoRoot 'frontend'

function Write-Stage([string]$Text) {
  Write-Host ''
  Write-Host ('=' * 72) -ForegroundColor Cyan
  Write-Host "  $Text" -ForegroundColor Cyan
  Write-Host ('=' * 72) -ForegroundColor Cyan
}
function Write-Step([string]$Text) { Write-Host "  -> $Text" -ForegroundColor Gray }
function Write-Ok  ([string]$Text) { Write-Host "  [OK] $Text" -ForegroundColor Green }
function Fail      ([string]$Text) { Write-Host "  [X] $Text" -ForegroundColor Red; exit 1 }

function Require-Command([string]$Name, [string]$Hint) {
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    Fail "'$Name' is not installed or not on PATH. $Hint"
  }
}

# =============================================================================
# 1. PRE-FLIGHT
# =============================================================================
Write-Stage '1/7  Pre-flight checks'

Require-Command az     'Install: https://learn.microsoft.com/cli/azure/install-azure-cli'
if (-not $SkipAgents)   { Require-Command python 'Install Python 3.11+: https://www.python.org/downloads/' }
if (-not $SkipFrontend) { Require-Command npm    'Install Node.js 20+: https://nodejs.org/' }

Write-Step 'Verifying Azure login'
$acct = az account show -o json 2>$null | ConvertFrom-Json
if (-not $acct) { Fail "Not logged in. Run 'az login' first." }

if ($SubscriptionId) {
  az account set --subscription $SubscriptionId | Out-Null
  $acct = az account show -o json | ConvertFrom-Json
}
$SubscriptionId = $acct.id
Write-Ok "Subscription: $($acct.name) ($SubscriptionId)"

Write-Step 'Ensuring Bicep is installed'
az bicep install 2>$null | Out-Null
az bicep upgrade 2>$null | Out-Null

Write-Step 'Registering required resource providers'
$providers = @(
  'Microsoft.App', 'Microsoft.CognitiveServices', 'Microsoft.DocumentDB',
  'Microsoft.OperationalInsights', 'Microsoft.Insights', 'Microsoft.KeyVault',
  'Microsoft.ContainerRegistry', 'Microsoft.ManagedIdentity', 'Microsoft.Web',
  'Microsoft.Authorization'
)
foreach ($p in $providers) { az provider register --namespace $p --wait 2>$null | Out-Null }
Write-Ok 'Providers registered'

Write-Step "Ensuring resource group '$ResourceGroup' in '$Location'"
az group create --name $ResourceGroup --location $Location --tags project=agentic-ai-poc env=$Env data=synthetic-only | Out-Null
Write-Ok "Resource group ready"

# Shared state across stages (populated by infra outputs or by live lookups).
$foundry = $null
$app     = $null

# =============================================================================
# 2 + 3. INFRASTRUCTURE (AI core + app hosting)
# =============================================================================
if ($SkipInfra) {
  Write-Stage '2-3/7  Infrastructure (SKIPPED)'
} else {
  Write-Stage '2/7  AI core (infra/foundry.bicep)'
  Write-Step 'Deploying Foundry account, project, models, telemetry, Cosmos, Key Vault, identity'
  $foundryJson = az deployment group create `
    --resource-group $ResourceGroup `
    --name "foundry-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))" `
    --template-file (Join-Path $InfraDir 'foundry.bicep') `
    --parameters location=$Location prefix=$Prefix env=$Env projectName=$ProjectName `
    --query properties.outputs -o json
  if ($LASTEXITCODE -ne 0) { Fail 'Foundry deployment failed.' }
  $foundry = $foundryJson | ConvertFrom-Json
  Write-Ok "Foundry project endpoint: $($foundry.foundryProjectEndpoint.value)"

  Write-Stage '3/7  App hosting (infra/app.bicep)'
  Write-Step 'Deploying Container Registry, Container Apps env + orchestrator, Static Web App, RBAC'
  $appJson = az deployment group create `
    --resource-group $ResourceGroup `
    --name "app-$([DateTime]::UtcNow.ToString('yyyyMMddHHmmss'))" `
    --template-file (Join-Path $InfraDir 'app.bicep') `
    --parameters `
      location=$Location prefix=$Prefix env=$Env `
      orchestratorIdentityResourceId=$($foundry.orchestratorIdentityResourceId.value) `
      orchestratorIdentityClientId=$($foundry.orchestratorIdentityClientId.value) `
      orchestratorIdentityPrincipalId=$($foundry.orchestratorIdentityPrincipalId.value) `
      foundryAccountName=$($foundry.foundryAccountName.value) `
      foundryProjectEndpoint=$($foundry.foundryProjectEndpoint.value) `
      foundryProjectName=$($foundry.projectName.value) `
      aoaiEndpoint=$($foundry.aoaiEndpoint.value) `
      cosmosEndpoint=$($foundry.cosmosEndpoint.value) `
      keyVaultUri=$($foundry.keyVaultUri.value) `
      appInsightsConnectionString=$($foundry.appInsightsConnectionString.value) `
    --query properties.outputs -o json
  if ($LASTEXITCODE -ne 0) { Fail 'App-hosting deployment failed.' }
  $app = $appJson | ConvertFrom-Json
  Write-Ok "Orchestrator FQDN: https://$($app.orchestratorFqdn.value)"
  Write-Ok "Static Web App:    https://$($app.staticWebAppDefaultHostname.value)"
}

# Resolve the resource names we need downstream (from outputs or by lookup).
$acrName  = if ($app) { $app.acrName.value }           else { (az acr list -g $ResourceGroup --query "[0].name" -o tsv) }
$acaName  = if ($app) { $app.containerAppName.value }  else { "$Prefix-aca-orch-$Env" }
$swaName  = if ($app) { $app.staticWebAppName.value }  else { (az staticwebapp list -g $ResourceGroup --query "[0].name" -o tsv) }
$acaFqdn  = if ($app) { $app.orchestratorFqdn.value }  else { (az containerapp show -n $acaName -g $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv) }
$projEndpoint = if ($foundry) { $foundry.foundryProjectEndpoint.value } `
                else { (az containerapp show -n $acaName -g $ResourceGroup --query "properties.template.containers[0].env[?name=='FOUNDRY_PROJECT_ENDPOINT'].value | [0]" -o tsv) }
$foundryAccount = if ($foundry) { $foundry.foundryAccountName.value } else { "$Prefix-aifoundry-$Env" }

# =============================================================================
# 4. BACKEND IMAGE
# =============================================================================
if ($SkipBackend) {
  Write-Stage '4/7  Backend image (SKIPPED)'
} else {
  Write-Stage '4/7  Build + deploy orchestrator image'
  if (-not $acrName) { Fail 'Could not resolve the Container Registry name.' }
  $tag = "$ImageName-$([DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss'))"
  Write-Step "Building image in ACR '$acrName' (tag $tag)"
  az acr build --registry $acrName `
    --image "${ImageName}:$tag" --image "${ImageName}:latest" `
    --file (Join-Path $BackendDir 'Dockerfile') $BackendDir
  if ($LASTEXITCODE -ne 0) { Fail 'ACR build failed.' }

  Write-Step "Rolling Container App '$acaName' to the new image"
  $rev = az containerapp update --name $acaName --resource-group $ResourceGroup `
    --image "$acrName.azurecr.io/${ImageName}:$tag" `
    --query 'properties.latestRevisionName' -o tsv
  if ($LASTEXITCODE -ne 0) { Fail 'Container App update failed.' }
  Write-Ok "Active revision: $rev"
}

# =============================================================================
# 5. FOUNDRY AGENTS + WORKFLOWS
# =============================================================================
if ($SkipAgents) {
  Write-Stage '5/7  Foundry agents + workflows (SKIPPED)'
} else {
  Write-Stage '5/7  Provision Foundry agents + workflows'
  if (-not $projEndpoint) { Fail 'Could not resolve FOUNDRY_PROJECT_ENDPOINT.' }

  # Grant the *current* deployer the data-plane role needed to create agents.
  Write-Step 'Granting current user "Azure AI User" on the Foundry account (best-effort)'
  $me = az ad signed-in-user show --query id -o tsv 2>$null
  $foundryId = az cognitiveservices account show -n $foundryAccount -g $ResourceGroup --query id -o tsv 2>$null
  if ($me -and $foundryId) {
    az role assignment create --assignee-object-id $me --assignee-principal-type User `
      --role 'Azure AI User' --scope $foundryId 2>$null | Out-Null
    Write-Step 'Waiting 30s for the role assignment to propagate'
    Start-Sleep -Seconds 30
  } else {
    Write-Step 'Could not resolve signed-in user or Foundry id; assuming the role already exists'
  }

  Write-Step 'Installing the provisioning dependency (azure-identity)'
  python -m pip install --quiet --disable-pip-version-check azure-identity 2>$null

  Write-Step 'Creating 6 agents + 2 workflow agents (idempotent)'
  $env:FOUNDRY_PROJECT_ENDPOINT = $projEndpoint
  python (Join-Path $BackendDir 'scripts/provision_foundry_agents.py')
  if ($LASTEXITCODE -ne 0) { Fail 'Agent/workflow provisioning failed.' }
  Write-Ok 'Agents + workflows provisioned'
}

# =============================================================================
# 6. FRONTEND
# =============================================================================
if ($SkipFrontend) {
  Write-Stage '6/7  Frontend (SKIPPED)'
} else {
  Write-Stage '6/7  Build + deploy frontend (Static Web App)'
  if (-not $swaName) { Fail 'Could not resolve the Static Web App name.' }
  if (-not $acaFqdn) { Fail 'Could not resolve the orchestrator FQDN.' }

  Write-Step 'Installing dependencies + building (Vite)'
  Push-Location $FrontendDir
  try {
    $env:VITE_API_BASE_URL = "https://$acaFqdn"
    $env:VITE_USE_MOCK     = 'false'
    npm ci
    if ($LASTEXITCODE -ne 0) { Fail 'npm ci failed.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { Fail 'Frontend build failed.' }

    Write-Step "Deploying to Static Web App '$swaName'"
    $swaToken = az staticwebapp secrets list --name $swaName --resource-group $ResourceGroup `
      --query 'properties.apiKey' -o tsv
    if (-not $swaToken) { Fail 'Could not read the Static Web App deployment token.' }
    npx -y @azure/static-web-apps-cli deploy ./dist --deployment-token $swaToken --env production
    if ($LASTEXITCODE -ne 0) { Fail 'Static Web App deploy failed.' }
  } finally {
    Pop-Location
  }
  Write-Ok 'Frontend deployed'
}

# =============================================================================
# 7. SUMMARY
# =============================================================================
Write-Stage '7/7  Deployment complete'
Write-Host ''
Write-Host '  Resource group   : ' -NoNewline; Write-Host $ResourceGroup -ForegroundColor White
Write-Host '  Region           : ' -NoNewline; Write-Host $Location -ForegroundColor White
Write-Host '  Foundry project  : ' -NoNewline; Write-Host $ProjectName -ForegroundColor White
if ($acaFqdn) { Write-Host '  Orchestrator API : ' -NoNewline; Write-Host "https://$acaFqdn" -ForegroundColor White }
$swaHost = if ($app) { $app.staticWebAppDefaultHostname.value } elseif ($swaName) { az staticwebapp show -n $swaName -g $ResourceGroup --query defaultHostname -o tsv } else { $null }
if ($swaHost) { Write-Host '  Web UI           : ' -NoNewline; Write-Host "https://$swaHost" -ForegroundColor White }
Write-Host ''
Write-Host '  Agents : memo-orchestrator, doc-retrieval, financial-ratio, bureau-summary, memo-assembler, banking-controller' -ForegroundColor Gray
Write-Host '  Flows  : credit-memo-workflow (UC1), banking-control-workflow (UC2)' -ForegroundColor Gray
Write-Host ''
Write-Ok 'All configuration, agents and workflows created.'
