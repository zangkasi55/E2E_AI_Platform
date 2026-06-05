# =============================================================================
# main.tf
# Resource group that scopes the platform. Equivalent to the RG targeted by
# `az deployment sub create -p infra/main.bicepparam`.
# =============================================================================

resource "azurerm_resource_group" "platform" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.tags
}
