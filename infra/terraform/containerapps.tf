# =============================================================================
# containerapps.tf
# Container Apps environment + the FastAPI orchestrator app. External ingress
# on 8000 (the UI calls this directly; it is NOT fronted by APIM). Runs under
# the orchestrator identity, scales 1->3 on HTTP concurrency.
# =============================================================================

resource "azurerm_container_app_environment" "env" {
  name                       = local.names.aca_env
  location                   = azurerm_resource_group.platform.location
  resource_group_name        = azurerm_resource_group.platform.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
  tags                       = local.tags
}

resource "azurerm_container_app" "orchestrator" {
  name                         = local.names.aca_orchestrator
  container_app_environment_id = azurerm_container_app_environment.env.id
  resource_group_name          = azurerm_resource_group.platform.name
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.orchestrator.id]
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    min_replicas = 1
    max_replicas = 3

    container {
      name   = "orchestrator"
      image  = var.orchestrator_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "MOCK_MODE"
        value = "false"
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.orchestrator.client_id
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_cognitive_account.openai.endpoint
      }
      env {
        name  = "AZURE_OPENAI_DEPLOYMENT_GPT4O"
        value = azurerm_cognitive_deployment.gpt4o.name
      }
      env {
        name  = "AZURE_OPENAI_DEPLOYMENT_GPT4O_MINI"
        value = azurerm_cognitive_deployment.gpt4o_mini.name
      }
      env {
        name  = "APIM_BASE_URL"
        value = "https://${azurerm_api_management.apim.name}.azure-api.net/tools"
      }
      env {
        name  = "AZURE_SEARCH_ENDPOINT"
        value = "https://${azurerm_search_service.search.name}.search.windows.net"
      }
      env {
        name  = "COSMOS_ENDPOINT"
        value = azurerm_cosmosdb_account.audit.endpoint
      }
      env {
        name  = "COSMOS_DATABASE"
        value = local.cosmos_database
      }
      env {
        name  = "SERVICEBUS_NAMESPACE"
        value = "${azurerm_servicebus_namespace.sb.name}.servicebus.windows.net"
      }
      env {
        name  = "SERVICEBUS_HITL_QUEUE"
        value = azurerm_servicebus_queue.hitl_approvals.name
      }
      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.appi.connection_string
      }
    }

    http_scale_rule {
      name                = "http-concurrency"
      concurrent_requests = 20
    }
  }
}
