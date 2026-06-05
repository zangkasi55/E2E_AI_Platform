# =============================================================================
# cosmos.tf
# Cosmos DB (SQL API) audit store. System-assigned identity, session
# consistency, continuous (7-day) backup. One autoscale database `agentaudit`
# with four containers partitioned by /run_id and a 365-day TTL.
# =============================================================================

resource "azurerm_cosmosdb_account" "audit" {
  name                = local.names.cosmos
  location            = azurerm_resource_group.platform.location
  resource_group_name = azurerm_resource_group.platform.name
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"
  tags                = local.tags

  identity {
    type = "SystemAssigned"
  }

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = azurerm_resource_group.platform.location
    failover_priority = 0
  }

  backup {
    type                = "Continuous"
    tier                = "Continuous7Days"
  }
}

resource "azurerm_cosmosdb_sql_database" "agentaudit" {
  name                = local.cosmos_database
  resource_group_name = azurerm_resource_group.platform.name
  account_name        = azurerm_cosmosdb_account.audit.name

  autoscale_settings {
    max_throughput = 1000
  }
}

resource "azurerm_cosmosdb_sql_container" "containers" {
  for_each              = toset(local.cosmos_containers)
  name                  = each.value
  resource_group_name   = azurerm_resource_group.platform.name
  account_name          = azurerm_cosmosdb_account.audit.name
  database_name         = azurerm_cosmosdb_sql_database.agentaudit.name
  partition_key_paths   = ["/run_id"]
  partition_key_version = 2
  default_ttl           = 31536000 # 365 days

  indexing_policy {
    indexing_mode = "consistent"
    included_path {
      path = "/*"
    }
  }
}
