# =============================================================================
# defender.tf
# Microsoft Defender for Cloud plans at SUBSCRIPTION scope. CSPM is always set
# (Standard or Free); the paid plans (Key Vault, Storage V2, AI) are toggled by
# enable_defender_paid_plans.
#
# This module delivers BOTH halves of the AI security-posture story:
#   * Defender for AI Services (resource_type = "AI") — runtime threat
#     protection for Azure OpenAI / Foundry (prompt-injection, wallet abuse,
#     anomalous model calls, credential exfiltration alerts).
#   * Data Security Posture Management (DSPM) for AI — the Defender CSPM
#     "Sensitive Data Discovery" extension gives Defender the data context that
#     powers DSPM for AI: it discovers sensitive data in AI grounding sources
#     and maps attack paths that reach AI resources. Requires Standard CSPM.
# Together with Purview (data classification) this is the full data + threat
# governance posture for the agentic workload.
# =============================================================================

locals {
  # Defender CSPM extensions that power DSPM for AI. Setting an explicit list
  # makes Terraform the source of truth for which CSPM components are on.
  dspm_cspm_extensions = ["SensitiveDataDiscovery"]
}

resource "azurerm_security_center_subscription_pricing" "cspm" {
  tier          = var.enable_standard_cspm ? "Standard" : "Free"
  resource_type = "CloudPosture"

  # DSPM for AI — sensitive-data discovery. Only valid on Standard CSPM.
  dynamic "extension" {
    for_each = (var.enable_standard_cspm && var.enable_dspm_for_ai) ? toset(local.dspm_cspm_extensions) : toset([])
    content {
      name = extension.value
    }
  }
}

resource "azurerm_security_center_subscription_pricing" "key_vaults" {
  count         = var.enable_defender_paid_plans ? 1 : 0
  tier          = "Standard"
  resource_type = "KeyVaults"
}

resource "azurerm_security_center_subscription_pricing" "storage" {
  count         = var.enable_defender_paid_plans ? 1 : 0
  tier          = "Standard"
  resource_type = "StorageAccounts"
  subplan       = "DefenderForStorageV2"
}

# Defender for AI Services — runtime threat protection for the Azure OpenAI /
# Foundry workload. The DSPM-for-AI data context above complements this.
resource "azurerm_security_center_subscription_pricing" "ai" {
  count         = var.enable_defender_paid_plans ? 1 : 0
  tier          = "Standard"
  resource_type = "AI"
}
