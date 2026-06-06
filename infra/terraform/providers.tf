# =============================================================================
# providers.tf
# Terraform + provider configuration for the Agentic AI Platform PoC.
#
# This configuration is the Terraform PARITY of the Bicep IaC in `infra/`.
# It provisions the full Microsoft-native agentic platform: observability,
# data + secrets, identity + RBAC, the APIM tool bridge, Functions, the
# Container Apps orchestrator, Purview governance, and Defender for Cloud.
#
# Auth: uses the Azure CLI / environment credentials of whoever runs Terraform
# (az login, or ARM_* env vars / OIDC in CI). The subscription is taken from
# that context, mirroring `az deployment sub create`.
# =============================================================================

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # ---------------------------------------------------------------------------
  # Remote state (recommended). The Terraform workflow bootstraps the backend
  # storage account and passes backend settings at init time.
  # ---------------------------------------------------------------------------
  backend "azurerm" {}
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
    }
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}

provider "azapi" {}

# Current signed-in principal — used to grant the deployer Key Vault rights so
# the placeholder secrets can be written during apply.
data "azurerm_client_config" "current" {}
