# =============================================================================
# variables.tf
# All input variables. Defaults mirror infra/main.bicepparam so a bare
# `terraform apply` reproduces the same `dev` environment as the Bicep deploy.
# =============================================================================

variable "name_prefix" {
  description = "Short prefix for all resource names (Bicep: namePrefix)."
  type        = string
  default     = "agpoc"
}

variable "environment" {
  description = "Environment moniker appended to resource names (dev/test/prod)."
  type        = string
  default     = "dev"
}

variable "location" {
  description = "Primary Azure region. Southeast Asia = Singapore (Thailand-nearest)."
  type        = string
  default     = "southeastasia"
}

variable "resource_group_name" {
  description = "Resource group that holds the platform (Bicep target RG)."
  type        = string
  default     = "rg-agentic-poc-sea"
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default = {
    project     = "agentic-ai-poc"
    environment = "dev"
    owner       = "datax-techx"
    workload    = "agentic-ai-platform"
    managed-by  = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Azure OpenAI model deployments
# ---------------------------------------------------------------------------
variable "gpt4o_capacity" {
  description = "TPM capacity (thousands) for the gpt-4o Standard deployment."
  type        = number
  default     = 20
}

variable "gpt4o_mini_capacity" {
  description = "TPM capacity (thousands) for the gpt-4o-mini Standard deployment."
  type        = number
  default     = 50
}

variable "gpt4o_model_version" {
  description = "Model version for gpt-4o."
  type        = string
  default     = "2024-11-20"
}

variable "gpt4o_mini_model_name" {
  description = "Underlying model behind the gpt-4o-mini deployment alias."
  type        = string
  default     = "gpt-4.1-mini"
}

variable "gpt4o_mini_model_version" {
  description = "Model version for the gpt-4o-mini alias."
  type        = string
  default     = "2025-04-14"
}

# ---------------------------------------------------------------------------
# APIM
# ---------------------------------------------------------------------------
variable "apim_publisher_email" {
  description = "Publisher email for the API Management instance."
  type        = string
  default     = "datax-techx@example.com"
}

variable "apim_publisher_name" {
  description = "Publisher (organization) name for API Management."
  type        = string
  default     = "DataX TechX Agentic PoC"
}

variable "entra_tenant_id" {
  description = "Entra tenant GUID for the APIM validate-jwt policy. Defaults to the deployer's tenant."
  type        = string
  default     = ""
}

variable "tool_bridge_audience" {
  description = "App ID URI / audience the tool-bridge tokens must target."
  type        = string
  default     = "api://agpoc-tool-bridge"
}

variable "required_scope" {
  description = "Default scope the orchestrator token must carry to call tools."
  type        = string
  default     = "tools.execute"
}

# ---------------------------------------------------------------------------
# Container Apps orchestrator image
# ---------------------------------------------------------------------------
variable "orchestrator_image" {
  description = "Container image for the orchestrator. Replace with ACR image after first backend CI build."
  type        = string
  default     = "mcr.microsoft.com/k8se/quickstart:latest"
}

# ---------------------------------------------------------------------------
# Microsoft Purview
# ---------------------------------------------------------------------------
variable "use_existing_purview" {
  description = "Reuse an existing Purview account (Azure allows one per tenant) instead of creating a new one."
  type        = bool
  default     = true
}

variable "existing_purview_resource_group_name" {
  description = "Resource group of the existing Purview account (when use_existing_purview = true)."
  type        = string
  default     = "rg-isaru66-purview"
}

variable "existing_purview_account_name" {
  description = "Name of the existing Purview account (when use_existing_purview = true)."
  type        = string
  default     = "pview-isaru66-default-001"
}

# ---------------------------------------------------------------------------
# Microsoft Defender for Cloud
# ---------------------------------------------------------------------------
variable "enable_standard_cspm" {
  description = "Upgrade CSPM from Free to Standard (attack paths + agentless scanning)."
  type        = bool
  default     = true
}

variable "enable_defender_paid_plans" {
  description = "Enable the paid Defender plans (Key Vault, Storage V2, AI)."
  type        = bool
  default     = true
}

variable "enable_dspm_for_ai" {
  description = "Enable Data Security Posture Management (DSPM) for AI via the Defender CSPM Sensitive Data Discovery extension. Requires enable_standard_cspm = true."
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Azure Policy (governance guardrails)
# ---------------------------------------------------------------------------
variable "enable_policy_assignments" {
  description = "Deploy the AI + data governance Azure Policy initiative and assign it to the platform resource group."
  type        = bool
  default     = true
}

variable "policy_effect" {
  description = "Effect for every member policy in the governance initiative. Audit reports non-compliance without blocking; Deny enforces."
  type        = string
  default     = "Audit"

  validation {
    condition     = contains(["Audit", "Deny", "Disabled"], var.policy_effect)
    error_message = "policy_effect must be one of: Audit, Deny, Disabled."
  }
}

# ---------------------------------------------------------------------------
# Static Web App (frontend host)
# ---------------------------------------------------------------------------
variable "deploy_static_web_app" {
  description = "Provision a Static Web App to host the React SPA."
  type        = bool
  default     = true
}

variable "static_web_app_location" {
  description = "Static Web Apps supported region (eastasia, westeurope, eastus2, westus2, centralus)."
  type        = string
  default     = "eastasia"
}

# ---------------------------------------------------------------------------
# Foundry live stack (separate RG in swedencentral)
# ---------------------------------------------------------------------------
variable "foundry_resource_group_name" {
  description = "Resource group for the live Foundry stack."
  type        = string
  default     = "rg-agentic-poc-swc"
}

variable "foundry_location" {
  description = "Region for the Foundry stack and gpt-4o quota."
  type        = string
  default     = "swedencentral"
}

variable "foundry_project_name" {
  description = "Data-plane Foundry project name."
  type        = string
  default     = "SCBXAIplatformPOC"
}
