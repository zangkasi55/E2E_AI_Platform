# =============================================================================
# observability.tf
# Log Analytics workspace + workspace-based Application Insights.
# This is the runtime observability plane: traces, logs, and the custom
# token-usage metric (gen_ai.token.usage) all land here.
# =============================================================================

resource "azurerm_log_analytics_workspace" "law" {
  name                = local.names.log_analytics
  location            = azurerm_resource_group.platform.location
  resource_group_name = azurerm_resource_group.platform.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 5
  tags                = local.tags
}

resource "azurerm_application_insights" "appi" {
  name                = local.names.app_insights
  location            = azurerm_resource_group.platform.location
  resource_group_name = azurerm_resource_group.platform.name
  workspace_id        = azurerm_log_analytics_workspace.law.id
  application_type    = "web"
  tags                = local.tags
}

# Saved KQL search: token usage by agent (mirrors the Bicep saved search and
# infra/observability/kql/token_usage.kql).
resource "azurerm_log_analytics_saved_search" "token_usage" {
  name                       = "gen_ai-token-usage-by-agent"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
  category                   = "Agentic AI"
  display_name               = "GenAI token usage by agent"
  query                      = <<-KQL
    customMetrics
    | where name == "gen_ai.token.usage"
    | extend agent = tostring(customDimensions["agent"]),
             model = tostring(customDimensions["gen_ai.response.model"]),
             useCase = tostring(customDimensions["use_case"])
    | summarize total_tokens = sum(value) by agent, model, useCase, bin(timestamp, 1h)
    | order by timestamp desc
  KQL
}
