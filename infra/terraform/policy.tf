# =============================================================================
# policy.tf
# Azure Policy — the AI + data governance guardrails for the platform.
#
# A custom initiative (policy set) bundles built-in Microsoft policies that
# harden the agentic workload, assigned to the platform resource group. This is
# the *preventive/auditing* governance layer that complements Purview (data
# classification) and Defender DSPM for AI (data + threat posture):
#
#   * Azure AI Services / Azure OpenAI — restrict network access, disable local
#     (key) authentication, and encrypt data at rest with a customer-managed key.
#   * Storage — require secure transport (HTTPS) and network restrictions.
#   * Key Vault — require deletion (purge) protection.
#
# Effect is controlled by var.policy_effect (default "Audit" so the PoC reports
# non-compliance without blocking deploys; switch to "Deny" to enforce).
# Built-in definitions are referenced by their stable GUID name, so display-name
# changes upstream never break the deployment.
# =============================================================================

locals {
  # Built-in policy definition GUIDs (stable). Each member exposes an "effect"
  # parameter accepting Audit / Deny / Disabled.
  governance_policy_definitions = {
    ai_services_restrict_network   = "037eea7a-bd0a-46c5-9a66-03aea78705d3"
    ai_services_disable_local_auth = "71ef260a-8f18-47b7-abcb-62d0673d94dc"
    ai_services_cmk_encryption     = "67121cc7-ff39-4ab8-b7e3-95b84dab487d"
    storage_secure_transfer        = "404c3081-a854-4457-ae30-26a93ef643f9"
    storage_restrict_network       = "34c877ad-507e-4c82-993e-3452a6e0ad3c"
    keyvault_purge_protection      = "0b60c0b2-2dc2-4e1c-b5c9-abbed971de53"
  }
}

data "azurerm_policy_definition" "governance" {
  for_each = var.enable_policy_assignments ? local.governance_policy_definitions : {}
  name     = each.value
}

resource "azurerm_policy_set_definition" "ai_governance" {
  count        = var.enable_policy_assignments ? 1 : 0
  name         = "${local.prefix}-ai-governance-${local.env}"
  policy_type  = "Custom"
  display_name = "Agentic AI Platform - AI & Data Governance (${local.env})"
  description  = "Azure AI Services / Azure OpenAI network + auth + CMK hardening, storage transport security, and Key Vault deletion protection for the agentic platform."

  parameters = jsonencode({
    effect = {
      type = "String"
      metadata = {
        displayName = "Effect"
        description = "Effect applied to every member policy in the initiative."
      }
      allowedValues = ["Audit", "Deny", "Disabled"]
      defaultValue  = "Audit"
    }
  })

  dynamic "policy_definition_reference" {
    for_each = data.azurerm_policy_definition.governance
    content {
      policy_definition_id = policy_definition_reference.value.id
      reference_id         = policy_definition_reference.key
      parameter_values = jsonencode({
        effect = { value = "[parameters('effect')]" }
      })
    }
  }
}

resource "azurerm_resource_group_policy_assignment" "ai_governance" {
  count                = var.enable_policy_assignments ? 1 : 0
  name                 = "${local.prefix}-ai-gov-${local.env}"
  display_name         = "Agentic AI Platform - AI & Data Governance"
  description          = "Audits/enforces the AI + data governance baseline for the agentic platform resource group."
  resource_group_id    = azurerm_resource_group.platform.id
  policy_definition_id = azurerm_policy_set_definition.ai_governance[0].id

  parameters = jsonencode({
    effect = { value = var.policy_effect }
  })

  non_compliance_message {
    content = "Resource violates the Agentic AI Platform governance baseline (network isolation, local-auth disablement, CMK encryption, secure transport, or Key Vault deletion protection)."
  }
}
