# =============================================================================
# entra.tf
# Microsoft Entra ID — the application identities behind the platform.
#
#   * Tool-bridge API app — the Entra resource the APIM validate-jwt policy
#     validates tokens against (audience = api://agpoc-tool-bridge). It exposes
#     the tools.* app roles + delegated scope the policy's scope-check enforces
#     (scp OR roles claim must carry tools.execute / tools.read / tools.handoff).
#     The orchestrator + tool-bridge managed identities are granted the
#     tools.execute app role, so their managed-identity tokens for the API carry
#     roles:["tools.execute"] and pass the gate — no client secrets.
#
#   * Agent IDs — one Entra application + service principal PER logical agent,
#     so every agent runs under its OWN Microsoft Entra identity (the "no shared
#     service accounts" principle, expressed as IaC). Each agent identity is
#     granted the tools.execute app role on the tool-bridge API. In production
#     these map to Microsoft Entra Agent ID blueprints; for IaC parity each is a
#     dedicated app registration whose client ID is emitted as an output.
#
# Everything here is gated by var.enable_entra_identities. The deployer needs
# rights to register applications (e.g. the Application Developer role); the
# one-command deploy scripts run as the signed-in user, who normally can.
# =============================================================================

data "azuread_client_config" "current" {}

# Stable GUIDs for the exposed app roles / delegated scope. random_uuid persists
# in Terraform state, so the IDs are constant across applies.
resource "random_uuid" "role_tools_execute" {}
resource "random_uuid" "role_tools_read" {}
resource "random_uuid" "role_tools_handoff" {}
resource "random_uuid" "scope_tools_execute" {}

locals {
  # App-role value -> stable GUID. Values match the APIM scope-check claims and
  # the per-tool scopes documented in policies/inbound-tool-call.xml.
  tool_app_roles = {
    "tools.execute" = random_uuid.role_tools_execute.result
    "tools.read"    = random_uuid.role_tools_read.result
    "tools.handoff" = random_uuid.role_tools_handoff.result
  }
}

# ---------------------------------------------------------------------------
# Tool-bridge API app registration (the validated audience).
# ---------------------------------------------------------------------------
resource "azuread_application" "tool_bridge" {
  count            = var.enable_entra_identities ? 1 : 0
  display_name     = "${local.prefix}-tool-bridge-${local.env}"
  identifier_uris  = [var.tool_bridge_audience]
  owners           = [data.azuread_client_config.current.object_id]
  sign_in_audience = "AzureADMyOrg"

  api {
    requested_access_token_version = 2

    oauth2_permission_scope {
      id                         = random_uuid.scope_tools_execute.result
      admin_consent_description  = "Allow the caller to invoke agent tools through the tool bridge."
      admin_consent_display_name = "Invoke agent tools"
      enabled                    = true
      type                       = "Admin"
      value                      = var.required_scope
    }
  }

  dynamic "app_role" {
    for_each = local.tool_app_roles
    content {
      id                   = app_role.value
      allowed_member_types = ["Application"]
      description          = "Workloads granted the ${app_role.key} permission on the tool bridge."
      display_name         = app_role.key
      enabled              = true
      value                = app_role.key
    }
  }
}

resource "azuread_service_principal" "tool_bridge" {
  count     = var.enable_entra_identities ? 1 : 0
  client_id = azuread_application.tool_bridge[0].client_id
  owners    = [data.azuread_client_config.current.object_id]
}

# Orchestrator + tool-bridge managed identities -> tools.execute app role.
resource "azuread_app_role_assignment" "workload_tools_execute" {
  for_each = var.enable_entra_identities ? local.workload_principals : {}

  app_role_id         = random_uuid.role_tools_execute.result
  principal_object_id = each.value
  resource_object_id  = azuread_service_principal.tool_bridge[0].object_id
}

# ---------------------------------------------------------------------------
# Agent IDs — one Entra application + service principal per logical agent.
# ---------------------------------------------------------------------------
resource "azuread_application" "agent" {
  for_each = var.enable_entra_identities ? toset(var.agent_identity_names) : toset([])

  display_name     = "${local.prefix}-agent-${each.value}-${local.env}"
  owners           = [data.azuread_client_config.current.object_id]
  sign_in_audience = "AzureADMyOrg"
}

resource "azuread_service_principal" "agent" {
  for_each = azuread_application.agent

  client_id = each.value.client_id
  owners    = [data.azuread_client_config.current.object_id]
  tags      = ["agent-id", "agentic-ai-poc"]
}

# Each agent identity may call the tool bridge (tools.execute).
resource "azuread_app_role_assignment" "agent_tools_execute" {
  for_each = azuread_service_principal.agent

  app_role_id         = random_uuid.role_tools_execute.result
  principal_object_id = each.value.object_id
  resource_object_id  = azuread_service_principal.tool_bridge[0].object_id
}
