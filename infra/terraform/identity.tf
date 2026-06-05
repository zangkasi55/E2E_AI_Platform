# =============================================================================
# identity.tf
# Three user-assigned managed identities (one per workload) and their
# least-privilege role assignments. This is the "every agent has its own
# identity, no shared service accounts" principle expressed as RBAC.
#
#   orchestrator -> KV secrets, AOAI, Search, Storage, Cosmos data-plane
#   toolbridge   -> KV secrets, AOAI, Search, Storage, Cosmos data-plane,
#                   Service Bus Data Owner (drives the HITL queue)
#   ui           -> no data-plane roles (presentation only)
# =============================================================================

resource "azurerm_user_assigned_identity" "orchestrator" {
  name                = local.names.id_orchestrator
  location            = azurerm_resource_group.platform.location
  resource_group_name = azurerm_resource_group.platform.name
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "toolbridge" {
  name                = local.names.id_toolbridge
  location            = azurerm_resource_group.platform.location
  resource_group_name = azurerm_resource_group.platform.name
  tags                = local.tags
}

resource "azurerm_user_assigned_identity" "ui" {
  name                = local.names.id_ui
  location            = azurerm_resource_group.platform.location
  resource_group_name = azurerm_resource_group.platform.name
  tags                = local.tags
}

# ---------------------------------------------------------------------------
# Shared Azure-RBAC roles for orchestrator + toolbridge.
# Keyed by "<workload>:<role>" so each assignment GUID is stable.
# ---------------------------------------------------------------------------
locals {
  workload_principals = {
    orchestrator = azurerm_user_assigned_identity.orchestrator.principal_id
    toolbridge   = azurerm_user_assigned_identity.toolbridge.principal_id
  }

  data_role_scopes = {
    key_vault_secrets_user   = azurerm_key_vault.kv.id
    cognitive_openai_user    = azurerm_cognitive_account.openai.id
    search_index_data_reader = azurerm_search_service.search.id
    storage_blob_data_reader = azurerm_storage_account.data.id
  }

  # Cartesian product of {orchestrator, toolbridge} x {4 data roles}.
  workload_role_assignments = merge([
    for wl, principal in local.workload_principals : {
      for role_key, scope in local.data_role_scopes :
      "${wl}:${role_key}" => {
        principal_id       = principal
        role_definition_id = "/providers/Microsoft.Authorization/roleDefinitions/${local.roles[role_key]}"
        scope              = scope
      }
    }
  ]...)
}

resource "azurerm_role_assignment" "workload_data_roles" {
  for_each           = local.workload_role_assignments
  scope              = each.value.scope
  role_definition_id = each.value.role_definition_id
  principal_id       = each.value.principal_id
}

# ---------------------------------------------------------------------------
# Service Bus Data Owner — toolbridge only (it pumps the HITL queue).
# ---------------------------------------------------------------------------
resource "azurerm_role_assignment" "toolbridge_servicebus" {
  scope              = azurerm_servicebus_namespace.sb.id
  role_definition_id = "/providers/Microsoft.Authorization/roleDefinitions/${local.roles.servicebus_data_owner}"
  principal_id       = azurerm_user_assigned_identity.toolbridge.principal_id
}

# ---------------------------------------------------------------------------
# Cosmos DB data-plane role (Built-in Data Contributor). This is a Cosmos
# SQL role assignment, NOT Azure RBAC — it grants document read/write.
# ---------------------------------------------------------------------------
resource "azurerm_cosmosdb_sql_role_assignment" "orchestrator_data" {
  resource_group_name = azurerm_resource_group.platform.name
  account_name        = azurerm_cosmosdb_account.audit.name
  role_definition_id  = "${azurerm_cosmosdb_account.audit.id}/sqlRoleDefinitions/${local.cosmos_data_contributor_role}"
  principal_id        = azurerm_user_assigned_identity.orchestrator.principal_id
  scope               = azurerm_cosmosdb_account.audit.id
}

resource "azurerm_cosmosdb_sql_role_assignment" "toolbridge_data" {
  resource_group_name = azurerm_resource_group.platform.name
  account_name        = azurerm_cosmosdb_account.audit.name
  role_definition_id  = "${azurerm_cosmosdb_account.audit.id}/sqlRoleDefinitions/${local.cosmos_data_contributor_role}"
  principal_id        = azurerm_user_assigned_identity.toolbridge.principal_id
  scope               = azurerm_cosmosdb_account.audit.id
}
