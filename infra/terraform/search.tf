# =============================================================================
# search.tf
# Azure AI Search — basic SKU, system-assigned identity, free semantic ranker.
# Backs the document-retrieval tool for UC1.
# =============================================================================

resource "azurerm_search_service" "search" {
  name                = local.names.search
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  sku                 = "basic"
  replica_count       = 1
  partition_count     = 1
  semantic_search_sku = "free"
  tags                = local.tags

  identity {
    type = "SystemAssigned"
  }
}
