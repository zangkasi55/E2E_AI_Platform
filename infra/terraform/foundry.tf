# =============================================================================
# foundry.tf
# Microsoft AI Foundry live stack used by the backend when USE_FOUNDRY_AGENTS
# is enabled. This mirrors infra/foundry.bicep:
#   - separate resource group in swedencentral
#   - observability (Log Analytics + App Insights)
#   - Foundry account + project + App Insights connection
#   - gpt-4o and gpt-4o-mini deployments
#   - Cosmos audit store + Key Vault
#   - orchestrator UAMI + least-privilege role assignments
#
# The backend provisioning script uses the output project endpoint to create the
# 6 prompt agents and 2 workflow agents in the live Foundry project.
# =============================================================================

resource "azurerm_resource_group" "foundry" {
  name     = var.foundry_resource_group_name
  location = var.foundry_location
  tags     = local.tags
}

resource "azurerm_log_analytics_workspace" "foundry_law" {
  name                = "${var.name_prefix}-law-${var.environment}"
  location            = azurerm_resource_group.foundry.location
  resource_group_name = azurerm_resource_group.foundry.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_application_insights" "foundry_appi" {
  name                = "${var.name_prefix}-appi-${var.environment}"
  location            = azurerm_resource_group.foundry.location
  resource_group_name = azurerm_resource_group.foundry.name
  workspace_id        = azurerm_log_analytics_workspace.foundry_law.id
  application_type    = "web"
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "foundry_orchestrator" {
  name                = local.names.id_orchestrator
  location            = azurerm_resource_group.foundry.location
  resource_group_name = azurerm_resource_group.foundry.name
  tags                = local.tags
}

resource "azurerm_cognitive_account" "foundry" {
  name                          = "${var.name_prefix}-aifoundry-${var.environment}"
  location                      = azurerm_resource_group.foundry.location
  resource_group_name           = azurerm_resource_group.foundry.name
  kind                          = "AIServices"
  sku_name                      = "S0"
  custom_subdomain_name         = "${var.name_prefix}-aifoundry-${var.environment}"
  public_network_access_enabled = true
  tags                          = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azapi_resource" "foundry_project" {
  type      = "Microsoft.CognitiveServices/accounts/projects@2025-06-01"
  name      = var.foundry_project_name
  parent_id = azurerm_cognitive_account.foundry.id
  location  = azurerm_resource_group.foundry.location
  tags      = local.tags

  body = jsonencode({
    identity = {
      type = "SystemAssigned"
    }
    properties = {
      displayName = "Agentic AI PoC"
      description = "DataX/TechX x Microsoft — credit memo + conversational banking agents."
    }
  })
}

resource "azapi_resource" "foundry_appinsights_connection" {
  type      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01"
  name      = azurerm_application_insights.foundry_appi.name
  parent_id = azapi_resource.foundry_project.id

  body = jsonencode({
    properties = {
      category    = "AppInsights"
      target      = azurerm_application_insights.foundry_appi.id
      authType    = "ApiKey"
      isSharedToAll = true
      credentials = {
        key = azurerm_application_insights.foundry_appi.connection_string
      }
      metadata = {
        ApiType    = "Azure"
        ResourceId = azurerm_application_insights.foundry_appi.id
      }
    }
  })
}

resource "azurerm_cognitive_deployment" "foundry_gpt4o" {
  name                 = "gpt-4o"
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = "OpenAI"
    name    = "gpt-4o"
    version = var.gpt4o_model_version
  }

  sku {
    name     = "GlobalStandard"
    capacity = 30
  }

  rai_policy_name = "Microsoft.DefaultV2"
}

resource "azurerm_cognitive_deployment" "foundry_gpt4o_mini" {
  name                 = "gpt-4o-mini"
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = "OpenAI"
    name    = "gpt-4o-mini"
    version = var.gpt4o_mini_model_version
  }

  sku {
    name     = "GlobalStandard"
    capacity = var.gpt4o_mini_capacity
  }

  rai_policy_name = "Microsoft.DefaultV2"
  depends_on      = [azurerm_cognitive_deployment.foundry_gpt4o]
}

resource "azurerm_cosmosdb_account" "foundry" {
  name                = "${var.name_prefix}-cosmos-${var.environment}-${substr(md5(azurerm_resource_group.foundry.id), 0, 5)}"
  location            = azurerm_resource_group.foundry.location
  resource_group_name = azurerm_resource_group.foundry.name
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
    location          = azurerm_resource_group.foundry.location
    failover_priority = 0
  }

  backup {
    type = "Continuous"
    tier = "Continuous7Days"
  }
}

resource "azurerm_cosmosdb_sql_database" "foundry_audit" {
  name                = local.cosmos_database
  resource_group_name = azurerm_resource_group.foundry.name
  account_name        = azurerm_cosmosdb_account.foundry.name

  autoscale_settings {
    max_throughput = 1000
  }
}

resource "azurerm_cosmosdb_sql_container" "foundry_containers" {
  for_each              = toset(local.cosmos_containers)
  name                  = each.value
  resource_group_name    = azurerm_resource_group.foundry.name
  account_name          = azurerm_cosmosdb_account.foundry.name
  database_name         = azurerm_cosmosdb_sql_database.foundry_audit.name
  partition_key_paths   = ["/run_id"]
  partition_key_version = 2
  default_ttl           = 31536000
}

resource "azurerm_key_vault" "foundry" {
  name                       = "${var.name_prefix}kv${var.environment}${substr(md5(azurerm_resource_group.foundry.id), 0, 8)}"
  location                   = azurerm_resource_group.foundry.location
  resource_group_name        = azurerm_resource_group.foundry.name
  tenant_id                  = local.tenant_id
  sku_name                   = "standard"
  enable_rbac_authorization  = true
  purge_protection_enabled   = true
  soft_delete_retention_days = 7
  tags                       = local.tags
}

resource "azurerm_role_assignment" "foundry_orchestrator_openai" {
  scope                = azurerm_cognitive_account.foundry.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = azurerm_user_assigned_identity.foundry_orchestrator.principal_id
}

resource "azurerm_role_assignment" "foundry_orchestrator_kv" {
  scope                = azurerm_key_vault.foundry.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.foundry_orchestrator.principal_id
}

resource "azurerm_cosmosdb_sql_role_assignment" "foundry_orchestrator_data" {
  resource_group_name = azurerm_resource_group.foundry.name
  account_name        = azurerm_cosmosdb_account.foundry.name
  role_definition_id  = "${azurerm_cosmosdb_account.foundry.id}/sqlRoleDefinitions/${local.cosmos_data_contributor_role}"
  principal_id        = azurerm_user_assigned_identity.foundry_orchestrator.principal_id
  scope               = azurerm_cosmosdb_account.foundry.id
}
output "foundry_orchestrator_client_id" {
  value = azurerm_user_assigned_identity.foundry_orchestrator.client_id
}
