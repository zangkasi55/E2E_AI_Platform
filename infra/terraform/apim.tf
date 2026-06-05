# =============================================================================
# apim.tf
# API Management — the deterministic control point (tool bridge) between the
# probabilistic agents and the real tools. Hosts the `agent-tools` API whose
# inbound policy enforces JWT validation, per-tool scope, rate limits, PII
# redaction, routing, and correlation. Named values feed the policy.
# =============================================================================

resource "azurerm_api_management" "apim" {
  name                = local.names.apim
  location            = azurerm_resource_group.platform.location
  resource_group_name = azurerm_resource_group.platform.name
  publisher_name      = var.apim_publisher_name
  publisher_email     = var.apim_publisher_email
  sku_name            = "Developer_1"
  tags                = local.tags

  identity {
    type = "SystemAssigned"
  }
}

# ---------------------------------------------------------------------------
# Named values consumed by the inbound policy.
# ---------------------------------------------------------------------------
resource "azurerm_api_management_named_value" "tenant_id" {
  name                = "tenant-id"
  resource_group_name = azurerm_resource_group.platform.name
  api_management_name = azurerm_api_management.apim.name
  display_name        = "tenant-id"
  value               = local.tenant_id
}

resource "azurerm_api_management_named_value" "tool_bridge_audience" {
  name                = "tool-bridge-audience"
  resource_group_name = azurerm_resource_group.platform.name
  api_management_name = azurerm_api_management.apim.name
  display_name        = "tool-bridge-audience"
  value               = var.tool_bridge_audience
}

resource "azurerm_api_management_named_value" "required_scope" {
  name                = "required-scope"
  resource_group_name = azurerm_resource_group.platform.name
  api_management_name = azurerm_api_management.apim.name
  display_name        = "required-scope"
  value               = var.required_scope
}

resource "azurerm_api_management_named_value" "tools_backend_url" {
  name                = "tools-backend-url"
  resource_group_name = azurerm_resource_group.platform.name
  api_management_name = azurerm_api_management.apim.name
  display_name        = "tools-backend-url"
  value               = "https://${local.names.func_tools}.azurewebsites.net/api"
}

# ---------------------------------------------------------------------------
# App Insights logger (every tool call is traced).
# ---------------------------------------------------------------------------
resource "azurerm_api_management_logger" "appi" {
  name                = "appinsights-logger"
  api_management_name = azurerm_api_management.apim.name
  resource_group_name = azurerm_resource_group.platform.name
  resource_id         = azurerm_application_insights.appi.id

  application_insights {
    connection_string = azurerm_application_insights.appi.connection_string
  }
}

# ---------------------------------------------------------------------------
# The agent-tools API + raw inbound policy + product + subscription.
# ---------------------------------------------------------------------------
resource "azurerm_api_management_api" "agent_tools" {
  name                  = "agent-tools"
  resource_group_name   = azurerm_resource_group.platform.name
  api_management_name   = azurerm_api_management.apim.name
  revision              = "1"
  display_name          = "Agent Tools"
  path                  = "tools"
  protocols             = ["https"]
  subscription_required = true
}

resource "azurerm_api_management_api_policy" "agent_tools" {
  api_name            = azurerm_api_management_api.agent_tools.name
  api_management_name = azurerm_api_management.apim.name
  resource_group_name = azurerm_resource_group.platform.name
  xml_content         = file("${path.module}/policies/inbound-tool-call.xml")

  depends_on = [
    azurerm_api_management_named_value.tenant_id,
    azurerm_api_management_named_value.tool_bridge_audience,
    azurerm_api_management_named_value.required_scope,
    azurerm_api_management_named_value.tools_backend_url,
  ]
}

resource "azurerm_api_management_api_diagnostic" "agent_tools" {
  identifier               = "applicationinsights"
  resource_group_name      = azurerm_resource_group.platform.name
  api_management_name      = azurerm_api_management.apim.name
  api_name                 = azurerm_api_management_api.agent_tools.name
  api_management_logger_id = azurerm_api_management_logger.appi.id
  sampling_percentage      = 100
  always_log_errors        = true
  log_client_ip            = true
  verbosity                = "information"
}

resource "azurerm_api_management_product" "agent_tools" {
  product_id            = "agent-tools-product"
  resource_group_name   = azurerm_resource_group.platform.name
  api_management_name   = azurerm_api_management.apim.name
  display_name          = "Agent Tools Product"
  subscription_required = true
  approval_required     = false
  published             = true
}

resource "azurerm_api_management_product_api" "agent_tools" {
  product_id          = azurerm_api_management_product.agent_tools.product_id
  api_name            = azurerm_api_management_api.agent_tools.name
  api_management_name = azurerm_api_management.apim.name
  resource_group_name = azurerm_resource_group.platform.name
}

resource "azurerm_api_management_subscription" "orchestrator" {
  display_name        = "orchestrator-sub"
  api_management_name = azurerm_api_management.apim.name
  resource_group_name = azurerm_resource_group.platform.name
  product_id          = azurerm_api_management_product.agent_tools.id
  state               = "active"
}
