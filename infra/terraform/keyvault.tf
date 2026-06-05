# =============================================================================
# keyvault.tf
# RBAC-enabled Key Vault with purge protection. Holds the secrets that the
# orchestrator and tool bridge resolve at runtime via managed identity.
# The 5 placeholder secrets carry REPLACE_ME values — rotate post-deploy.
# =============================================================================

resource "azurerm_key_vault" "kv" {
  name                       = local.names.key_vault
  location                   = azurerm_resource_group.platform.location
  resource_group_name        = azurerm_resource_group.platform.name
  tenant_id                  = local.tenant_id
  sku_name                   = "standard"
  enable_rbac_authorization  = true
  purge_protection_enabled   = true
  soft_delete_retention_days = 7
  tags                       = local.tags
}

# Allow the deployer to write the placeholder secrets during apply.
resource "azurerm_role_assignment" "kv_deployer_officer" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

locals {
  kv_placeholder_secrets = [
    "aoai-api-key",
    "search-admin-key",
    "cosmos-connection-string",
    "servicebus-connection-string",
    "apim-subscription-key",
  ]
}

resource "azurerm_key_vault_secret" "placeholders" {
  for_each     = toset(local.kv_placeholder_secrets)
  name         = each.value
  value        = "REPLACE_ME"
  key_vault_id = azurerm_key_vault.kv.id
  content_type = "placeholder"

  depends_on = [azurerm_role_assignment.kv_deployer_officer]

  lifecycle {
    ignore_changes = [value] # don't clobber a real secret once rotated
  }
}
