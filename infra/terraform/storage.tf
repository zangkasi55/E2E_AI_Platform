# =============================================================================
# storage.tf
# ADLS Gen2 storage for synthetic data, generated memos, and templates.
# HNS enabled, TLS 1.2 floor, blob soft-delete, diagnostics to Log Analytics.
# =============================================================================

resource "azurerm_storage_account" "data" {
  name                            = local.storage_name
  resource_group_name             = azurerm_resource_group.platform.name
  location                        = azurerm_resource_group.platform.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  is_hns_enabled                  = true # ADLS Gen2
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  tags                            = local.tags

  blob_properties {
    delete_retention_policy {
      days = 7
    }
    container_delete_retention_policy {
      days = 7
    }
  }
}

resource "azurerm_storage_container" "synthetic" {
  name                  = "synthetic"
  storage_account_id    = azurerm_storage_account.data.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "memos" {
  name                  = "memos"
  storage_account_id    = azurerm_storage_account.data.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "templates" {
  name                  = "templates"
  storage_account_id    = azurerm_storage_account.data.id
  container_access_type = "private"
}

resource "azurerm_monitor_diagnostic_setting" "storage_blob" {
  name                       = "to-law"
  target_resource_id         = "${azurerm_storage_account.data.id}/blobServices/default"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id

  enabled_log {
    category = "StorageRead"
  }
  enabled_log {
    category = "StorageWrite"
  }
  enabled_metric {
    category = "Transaction"
  }
}
