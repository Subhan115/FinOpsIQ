output "resource_group_name" {
  value = azurerm_resource_group.rg.name
}

output "storage_account_name" {
  value       = azurerm_storage_account.sa.name
  description = "The randomly generated unique storage account name."
}

output "app_insights_connection_string" {
  value       = azurerm_application_insights.app_insights.connection_string
  sensitive   = true
  description = "Connection string needed for Python Azure Function App config."
}
