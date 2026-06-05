# =============================================================================
# functions.tf
# Two Linux Consumption (Y1) Function Apps on a shared dynamic plan:
#   - tools host   (agpoc-func-tools-dev)  : the real tool implementations
#                                            APIM routes to after policy checks
#   - durable host (agpoc-func-durable-dev): the HITL approval orchestration
# Both run Python 3.11 under the toolbridge user-assigned identity.
# =============================================================================

resource "azurerm_storage_account" "functions" {
  name                            = local.functions_storage
  resource_group_name             = azurerm_resource_group.platform.name
  location                        = azurerm_resource_group.platform.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  account_kind                    = "StorageV2"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  tags                            = local.tags
}

resource "azurerm_service_plan" "functions" {
  name                = local.names.func_plan
  resource_group_name = azurerm_resource_group.platform.name
  location            = azurerm_resource_group.platform.location
  os_type             = "Linux"
  sku_name            = "Y1" # Consumption
  tags                = local.tags
}

locals {
  function_common_app_settings = {
    FUNCTIONS_WORKER_RUNTIME = "python"
    MOCK_MODE                = "false"
    COSMOS_ENDPOINT          = azurerm_cosmosdb_account.audit.endpoint
    COSMOS_DATABASE          = local.cosmos_database
    SERVICEBUS_NAMESPACE     = "${azurerm_servicebus_namespace.sb.name}.servicebus.windows.net"
    SERVICEBUS_HITL_QUEUE    = azurerm_servicebus_queue.hitl_approvals.name
    AZURE_CLIENT_ID          = azurerm_user_assigned_identity.toolbridge.client_id
  }
}

resource "azurerm_linux_function_app" "tools" {
  name                       = local.names.func_tools
  resource_group_name        = azurerm_resource_group.platform.name
  location                   = azurerm_resource_group.platform.location
  service_plan_id            = azurerm_service_plan.functions.id
  storage_account_name       = azurerm_storage_account.functions.name
  storage_account_access_key = azurerm_storage_account.functions.primary_access_key
  tags                       = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.toolbridge.id]
  }

  site_config {
    application_insights_connection_string = azurerm_application_insights.appi.connection_string
    application_stack {
      python_version = "3.11"
    }
  }

  app_settings = local.function_common_app_settings
}

resource "azurerm_linux_function_app" "durable" {
  name                       = local.names.func_durable
  resource_group_name        = azurerm_resource_group.platform.name
  location                   = azurerm_resource_group.platform.location
  service_plan_id            = azurerm_service_plan.functions.id
  storage_account_name       = azurerm_storage_account.functions.name
  storage_account_access_key = azurerm_storage_account.functions.primary_access_key
  tags                       = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.toolbridge.id]
  }

  site_config {
    application_insights_connection_string = azurerm_application_insights.appi.connection_string
    application_stack {
      python_version = "3.11"
    }
  }

  app_settings = merge(local.function_common_app_settings, {
    DURABLE_TASK_HUB = "agpochitl"
  })
}
