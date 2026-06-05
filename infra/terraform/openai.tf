# =============================================================================
# openai.tf
# Azure OpenAI (Cognitive Services) account with a custom subdomain and two
# serial model deployments. Deployments are chained (depends_on) because the
# control plane rejects parallel deployment writes on one account.
# =============================================================================

resource "azurerm_cognitive_account" "openai" {
  name                          = local.names.openai
  location                      = azurerm_resource_group.platform.location
  resource_group_name           = azurerm_resource_group.platform.name
  kind                          = "OpenAI"
  sku_name                      = "S0"
  custom_subdomain_name         = local.names.openai
  public_network_access_enabled = true
  tags                          = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_cognitive_deployment" "gpt4o" {
  name                 = "gpt-4o"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = "gpt-4o"
    version = var.gpt4o_model_version
  }

  sku {
    name     = "Standard"
    capacity = var.gpt4o_capacity
  }

  rai_policy_name = "Microsoft.DefaultV2"
}

resource "azurerm_cognitive_deployment" "gpt4o_mini" {
  name                 = "gpt-4o-mini"
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.gpt4o_mini_model_name
    version = var.gpt4o_mini_model_version
  }

  sku {
    name     = "Standard"
    capacity = var.gpt4o_mini_capacity
  }

  rai_policy_name = "Microsoft.DefaultV2"

  # Serialize against the first deployment (single-writer control plane).
  depends_on = [azurerm_cognitive_deployment.gpt4o]
}

resource "azurerm_monitor_diagnostic_setting" "openai" {
  name                       = "to-law"
  target_resource_id         = azurerm_cognitive_account.openai.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id

  enabled_log {
    category = "RequestResponse"
  }
  enabled_log {
    category = "Audit"
  }
  enabled_metric {
    category = "AllMetrics"
  }
}
