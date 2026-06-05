# =============================================================================
# defender.tf
# Microsoft Defender for Cloud plans at SUBSCRIPTION scope. CSPM is always set
# (Standard or Free); the paid plans (Key Vault, Storage V2, AI) are toggled by
# enable_defender_paid_plans. The AI plan delivers prompt-injection / anomaly
# detection for the Azure OpenAI workload — the threat-protection half of the
# governance story (Purview is the data-posture half).
# =============================================================================

resource "azurerm_security_center_subscription_pricing" "cspm" {
  tier          = var.enable_standard_cspm ? "Standard" : "Free"
  resource_type = "CloudPosture"
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

resource "azurerm_security_center_subscription_pricing" "ai" {
  count         = var.enable_defender_paid_plans ? 1 : 0
  tier          = "Standard"
  resource_type = "AI"
}
