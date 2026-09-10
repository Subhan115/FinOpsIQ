variable "resource_group_name" {
  type        = string
  description = "Name of the resource group."
  default     = "FinOpsIQ"
}

variable "location" {
  type        = string
  description = "Azure region for resource deployment."
  default     = "centralindia"
}

variable "storage_account_base_name" {
  type        = string
  description = "Base prefix for storage account (must be lowercase alphanumeric, max 18 chars to accommodate suffix)."
  default     = "finopsiqstore"
}

variable "storage_account_tier" {
  type        = string
  description = "Defines the Tier to use for this storage account."
  default     = "Standard"
}

variable "storage_account_replication_type" {
  type        = string
  description = "Defines the type of replication to use for this storage account."
  default     = "LRS"
}

variable "raw_cost_input_container_name" {
  type        = string
  description = "Name of the storage container for raw cost input data."
  default     = "raw-cost-input"
}

variable "finopsiq_results_container_name" {
  type        = string
  description = "Name of the storage container for FinOpsIQ results."
  default     = "finopsiq-results"
}

variable "app_insights_name" {
  type        = string
  description = "Name of the Application Insights resource."
  default     = "finopsiq-appinsights"
}

variable "app_insights_type" {
  type        = string
  description = "Specifies the application type for Application Insights."
  default     = "other" # Optimized for Python background workers & Azure Functions
}

variable "log_analytics_workspace_name" {
  type        = string
  description = "Name of the Log Analytics Workspace for modern App Insights."
  default     = "finopsiq-law"
}
