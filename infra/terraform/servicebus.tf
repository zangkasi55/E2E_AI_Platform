# =============================================================================
# servicebus.tf
# Service Bus (Standard) with a session-enabled `hitl-approvals` queue. This is
# the human-in-the-loop channel for UC1: the orchestrator enqueues a pending
# approval; a Durable Functions orchestration waits for the reviewer decision.
# =============================================================================

resource "azurerm_servicebus_namespace" "sb" {
  name                = local.names.servicebus
  location            = azurerm_resource_group.platform.location
  resource_group_name = azurerm_resource_group.platform.name
  sku                 = "Standard"
  tags                = local.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_servicebus_queue" "hitl_approvals" {
  name         = "hitl-approvals"
  namespace_id = azurerm_servicebus_namespace.sb.id

  requires_session                        = true
  lock_duration                           = "PT5M"
  max_delivery_count                      = 10
  default_message_ttl                     = "PT24H"
  dead_lettering_on_message_expiration    = true
}
