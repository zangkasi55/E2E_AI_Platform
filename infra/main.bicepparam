// =============================================================================
// main.bicepparam — DEV environment parameters for the Agentic AI Platform PoC.
// Consumed by: az deployment sub create -f infra/main.bicep -p infra/main.bicepparam
//
// Values mirror POC_SPEC.md canonical settings. Override per environment by
// copying this file (e.g. main.staging.bicepparam) — never hardcode secrets.
// =============================================================================
using 'main.bicep'

// Canonical region / RG / naming
param location = 'southeastasia'
param resourceGroupName = 'rg-agentic-poc-sea'
param prefix = 'agpoc'
param env = 'dev'

// Canonical tag set (project=agentic-poc, env=dev, owner=datax-techx)
param tags = {
  project: 'agentic-poc'
  env: 'dev'
  owner: 'datax-techx'
}

// APIM notifications. TODO(operator): set to the real DataX/TechX distro list.
param apimPublisherEmail = 'datax-techx@example.com'

// Orchestrator image. CI (backend.yml) overrides this with the ACR-pushed tag
// on subsequent deploys; the placeholder lets the first infra deploy succeed.
param orchestratorImage = 'mcr.microsoft.com/k8se/quickstart:latest'

// Tenant has an existing Purview account; reuse it to satisfy one-account-per-tenant constraint.
param useExistingPurview = true
param existingPurviewResourceGroupName = 'rg-isaru66-purview'
param existingPurviewAccountName = 'pview-isaru66-default-001'

// Defender for Cloud (subscription-scoped — see defender.bicep).
// PoC default: Free CSPM only. Paid Defender plans are subscription-scoped and
// bill every matching resource across the WHOLE subscription, so they stay OFF
// on this shared corporate sub. Flip enableDefenderPaidPlans=true for a
// dedicated security-posture demo.
param enableStandardCspm = true
param enableDefenderPaidPlans = true
