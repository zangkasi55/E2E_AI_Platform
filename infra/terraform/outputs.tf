# =============================================================================
# outputs.tf
# Values needed to wire the application to the deployed platform (env vars,
# CI variables, post-deploy checks).
# =============================================================================

output "resource_group_name" {
  description = "Resource group holding the platform."
  value       = azurerm_resource_group.platform.name
}

output "openai_endpoint" {
  description = "Azure OpenAI endpoint (AZURE_OPENAI_ENDPOINT)."
  value       = azurerm_cognitive_account.openai.endpoint
}

output "search_endpoint" {
  description = "Azure AI Search endpoint."
  value       = "https://${azurerm_search_service.search.name}.search.windows.net"
}

output "cosmos_endpoint" {
  description = "Cosmos DB endpoint (audit store)."
  value       = azurerm_cosmosdb_account.audit.endpoint
}

output "key_vault_uri" {
  description = "Key Vault URI."
  value       = azurerm_key_vault.kv.vault_uri
}

output "servicebus_namespace" {
  description = "Service Bus namespace FQDN."
  value       = "${azurerm_servicebus_namespace.sb.name}.servicebus.windows.net"
}

output "apim_gateway_url" {
  description = "APIM gateway URL for the tool bridge."
  value       = azurerm_api_management.apim.gateway_url
}

output "tool_bridge_url" {
  description = "Full tool-bridge base URL (APIM_BASE_URL)."
  value       = "https://${azurerm_api_management.apim.name}.azure-api.net/tools"
}

output "orchestrator_fqdn" {
  description = "Container Apps orchestrator FQDN (UI calls this)."
  value       = azurerm_container_app.orchestrator.ingress[0].fqdn
}

output "tools_function_hostname" {
  description = "Tools Function App default hostname."
  value       = azurerm_linux_function_app.tools.default_hostname
}

output "durable_function_hostname" {
  description = "Durable Function App default hostname."
  value       = azurerm_linux_function_app.durable.default_hostname
}

output "application_insights_connection_string" {
  description = "App Insights connection string (sensitive)."
  value       = azurerm_application_insights.appi.connection_string
  sensitive   = true
}

output "orchestrator_identity_client_id" {
  description = "Client ID of the orchestrator user-assigned identity."
  value       = azurerm_user_assigned_identity.orchestrator.client_id
}

output "toolbridge_identity_client_id" {
  description = "Client ID of the tool-bridge user-assigned identity."
  value       = azurerm_user_assigned_identity.toolbridge.client_id
}

output "tool_bridge_app_client_id" {
  description = "Client (application) ID of the Entra tool-bridge API app (audience for APIM validate-jwt)."
  value       = var.enable_entra_identities ? azuread_application.tool_bridge[0].client_id : null
}

output "agent_identity_client_ids" {
  description = "Map of logical agent name -> Entra client ID (Agent ID)."
  value       = var.enable_entra_identities ? { for k, app in azuread_application.agent : k => app.client_id } : {}
}

output "purview_account_name" {
  description = "Purview account governing the platform (new or existing)."
  value       = local.purview_account_name
}

output "dspm_for_ai_enabled" {
  description = "Whether DSPM for AI (Defender CSPM Sensitive Data Discovery) is enabled."
  value       = var.enable_standard_cspm && var.enable_dspm_for_ai
}

output "ai_governance_policy_assignment_id" {
  description = "Resource ID of the AI & data governance policy assignment (null if disabled)."
  value       = var.enable_policy_assignments ? azurerm_resource_group_policy_assignment.ai_governance[0].id : null
}

output "static_web_app_default_hostname" {
  description = "Static Web App default hostname (if deployed)."
  value       = var.deploy_static_web_app ? azurerm_static_web_app.ui[0].default_host_name : null
}

output "foundry_project_endpoint" {
  description = "Foundry project endpoint for the live agent provisioning script."
  value       = "https://${azurerm_cognitive_account.foundry.name}.services.ai.azure.com/api/projects/${var.foundry_project_name}"
}

output "foundry_openai_endpoint" {
  description = "Foundry Azure OpenAI endpoint."
  value       = "https://${azurerm_cognitive_account.foundry.name}.openai.azure.com/"
}

output "foundry_resource_group_name" {
  description = "Resource group that holds the Foundry stack."
  value       = azurerm_resource_group.foundry.name
}
