# =============================================================================
# locals.tf
# Canonical resource names — identical to the Bicep `${namePrefix}-...-${env}`
# convention so Terraform and Bicep produce the same topology.
# =============================================================================

locals {
  prefix = var.name_prefix
  env    = var.environment

  # Storage account names: lowercase, no hyphens, <= 24 chars.
  storage_name         = "${local.prefix}storage${local.env}"
  functions_storage    = "${local.prefix}fxstor${local.env}"

  names = {
    log_analytics    = "${local.prefix}-law-${local.env}"
    app_insights     = "${local.prefix}-appi-${local.env}"
    key_vault        = "${local.prefix}-kv-${local.env}"
    cosmos           = "${local.prefix}-cosmos-${local.env}"
    openai           = "${local.prefix}-aoai-${local.env}"
    search           = "${local.prefix}-search-${local.env}"
    servicebus       = "${local.prefix}-sb-${local.env}"
    apim             = "${local.prefix}-apim-${local.env}"
    func_plan        = "${local.prefix}-func-plan-${local.env}"
    func_tools       = "${local.prefix}-func-tools-${local.env}"
    func_durable     = "${local.prefix}-func-durable-${local.env}"
    aca_env          = "${local.prefix}-aca-env-${local.env}"
    aca_orchestrator = "${local.prefix}-aca-orch-${local.env}"
    purview          = "${local.prefix}-purview-${local.env}"
    id_orchestrator  = "${local.prefix}-id-orchestrator-${local.env}"
    id_toolbridge    = "${local.prefix}-id-toolbridge-${local.env}"
    id_ui            = "${local.prefix}-id-ui-${local.env}"
  }

  cosmos_database   = "agentaudit"
  cosmos_containers = ["runs", "steps", "handoffs", "tokens"]

  tenant_id = var.entra_tenant_id != "" ? var.entra_tenant_id : data.azurerm_client_config.current.tenant_id

  # Built-in Azure role definition GUIDs (data-plane least privilege).
  roles = {
    key_vault_secrets_user      = "4633458b-17de-408a-b874-0445c86b69e6"
    cognitive_openai_user       = "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
    search_index_data_reader    = "1407120a-92aa-4202-b7e9-c0e197c71c8f"
    storage_blob_data_reader    = "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1"
    servicebus_data_owner       = "090c5cfd-751d-490a-894a-3ce6f1109419"
  }

  # Cosmos DB built-in data-plane role (NOT an Azure RBAC role).
  cosmos_data_contributor_role = "00000000-0000-0000-0000-000000000002"

  tags = merge(var.tags, { environment = var.environment })
}
