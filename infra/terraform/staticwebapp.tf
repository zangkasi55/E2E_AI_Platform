# =============================================================================
# staticwebapp.tf
# Static Web App that hosts the React SPA (frontend/). Optional — toggle with
# deploy_static_web_app. The CI pipeline pushes the built `dist/` to this SWA.
# =============================================================================

resource "azurerm_static_web_app" "ui" {
  count               = var.deploy_static_web_app ? 1 : 0
  name                = "${local.prefix}-swa-${local.env}"
  resource_group_name = azurerm_resource_group.platform.name
  location            = var.static_web_app_location
  sku_tier            = "Free"
  sku_size            = "Free"
  tags                = merge(local.tags, { "azd-service-name" = "web" })
}
