variable "aws_region" {
  description = "AWS region where the platform resources will be created."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "aws_region must be a valid AWS region name."
  }
}

variable "environment" {
  description = "Deployment environment name used for resource naming and tags."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.environment)) && length(var.environment) > 0
    error_message = "environment must contain only lowercase letters, numbers, and hyphens."
  }
}

variable "project_name" {
  description = "Project name used for resource naming and tags."
  type        = string
  default     = "serverless-image-processing"

  validation {
    condition     = can(regex("^[a-z0-9-]+$", var.project_name)) && length(var.project_name) > 0
    error_message = "project_name must contain only lowercase letters, numbers, and hyphens."
  }
}

variable "budget_alert_email" {
  description = "Email address that receives account-wide budget threshold alerts."
  type        = string
}

variable "frontend_allowed_origins" {
  description = "Browser origins allowed to call the upload and status API and upload directly to S3."
  type        = list(string)
  default = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
  ]

  validation {
    condition     = length(var.frontend_allowed_origins) > 0 && !contains(var.frontend_allowed_origins, "*")
    error_message = "frontend_allowed_origins must contain at least one explicit origin and must not contain '*'."
  }
}
