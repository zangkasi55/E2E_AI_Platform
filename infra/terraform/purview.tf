# =============================================================================
# purview.tf
# Microsoft Purview governance. Azure permits one Purview account per tenant,
# so this either CREATES a new account or REFERENCES an existing one (default,
# matching infra/main.bicepparam: pview-isaru66-default-001). Either way the
# Purview managed identity is granted Storage Blob Data Reader so its PII scan
# can read the synthetic data.
# =============================================================================

resource "azurerm_purview_account" "new" {
  count               = var.use_existing_purview ? 0 : 1
  name                = local.names.purview
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  tags                = local.tags

  identity {
    type = "SystemAssigned"
  }
}

data "azurerm_purview_account" "existing" {
  count               = var.use_existing_purview ? 1 : 0
  name                = var.existing_purview_account_name
  resource_group_name = var.existing_purview_resource_group_name
}

locals {
  purview_identity_principal_id = var.use_existing_purview ? data.azurerm_purview_account.existing[0].identity[0].principal_id : azurerm_purview_account.new[0].identity[0].principal_id
  purview_account_name          = var.use_existing_purview ? var.existing_purview_account_name : local.names.purview
}

resource "azurerm_role_assignment" "purview_storage_reader" {
  scope              = azurerm_storage_account.data.id
  role_definition_id = "/providers/Microsoft.Authorization/roleDefinitions/${local.roles.storage_blob_data_reader}"
  principal_id       = local.purview_identity_principal_id
}
