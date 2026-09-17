variable "project_id" {
  description = "GCP project ID. Set via stage.tfvars / prod.tfvars (not committed)."
  type        = string
}

variable "project_number" {
  description = "GCP project number (numeric). Set via stage.tfvars / prod.tfvars."
  type        = string
}

variable "region" {
  description = "Primary region for all regional resources."
  type        = string
  default     = "europe-west1"
}

variable "hostname" {
  description = "FQDN served by the LB / IAP. The Google-managed cert is issued for this name; a DNS A record must point at the LB IP."
  type        = string
  default     = "security-dashboard.example.com"
}

variable "image_tag" {
  description = "Default tag for backend + frontend images in Artifact Registry when neither image_tag_backend nor image_tag_frontend is supplied. Falls back to 'latest' so a fresh apply works before the first build."
  type        = string
  default     = "latest"
}

variable "image_tag_backend" {
  description = "Tag for the backend image. Overrides image_tag for the backend; needed because the two images are built independently (e.g. cloudbuild.frontend.yaml builds frontend only). Empty string -> falls back to image_tag."
  type        = string
  default     = ""
}

variable "image_tag_frontend" {
  description = "Tag for the frontend image. Overrides image_tag for the frontend. Empty string -> falls back to image_tag."
  type        = string
  default     = ""
}

variable "iap_members" {
  description = "Principals granted roles/iap.httpsResourceAccessor on both backend services. Each entry is a fully-qualified IAM member (e.g. user:foo@example.com, group:bar@example.com)."
  type        = list(string)
  default     = []
}

variable "iap_default_groups" {
  description = "Comma-separated Google groups injected as the user's group membership for every IAP-authenticated request. IAP forwards the user email but not group membership; the LB IAP allowlist already gates who can reach us, so any caller is trusted to hold these groups. Must include a group that maps to the desired role(s) in config/rbac.yaml."
  type        = string
  default     = ""
}

variable "github_org" {
  description = "GitHub organisation polled by the Dependabot poller."
  type        = string
  default     = "ExampleOrg"
}

variable "sonar_orgs" {
  description = "Comma-separated SonarCloud organisation keys polled by the SonarCloud poller. Mirrors SONAR_ORG env var."
  type        = string
  default     = "exampleorg"
}

variable "wiz_api_url" {
  description = "Wiz tenant GraphQL endpoint (e.g. https://api.us17.app.wiz.io/graphql)."
  type        = string
  default     = ""
}

variable "jira_pentest_poller_schedule" {
  description = "Cron schedule for the Jira pentest poller."
  type        = string
  default     = "0 * * * *"
}

variable "jira_base_url" {
  description = "Jira Cloud site URL for the pentest poller."
  type        = string
  default     = ""
}

variable "jira_api_email" {
  description = "Jira API user email for the pentest poller."
  type        = string
  default     = ""
}

variable "poller_schedule" {
  description = "Cron schedule for Dependabot, SonarCloud, and Wiz pollers (Cloud Scheduler syntax)."
  type        = string
  default     = "*/30 * * * *"
}

variable "sql_tier" {
  description = "Cloud SQL machine tier. db-custom-1-3840 is the cheapest practical option for ENTERPRISE Postgres 16."
  type        = string
  default     = "db-custom-1-3840"
}

variable "sql_storage_gb" {
  description = "Cloud SQL storage allocation in GB."
  type        = number
  default     = 10
}

variable "sql_deletion_protection" {
  description = "Cloud SQL deletion protection. Leave true in durable environments. Set false in disposable tfvars if you need `terraform destroy` to remove the instance."
  type        = bool
  default     = true
}

variable "storage_force_destroy" {
  description = "Allow Terraform to delete GCS buckets that still contain objects. Leave false in durable environments. Set true in disposable tfvars only."
  type        = bool
  default     = false
}

variable "log_level" {
  description = "Application log level."
  type        = string
  default     = "INFO"
}

variable "github_repository" {
  description = "GitHub org/repo allowed to impersonate secdb-deployer (assertion.repository)."
  type        = string
  default     = "ExampleOrg/unified-security-dashboard"
}

variable "github_wif_ref_condition" {
  description = <<-EOT
    Optional extra predicate AND-ed into the WIF provider attribute_condition
    (e.g. attribute.ref == \"refs/heads/main\" for staging, or
    attribute.ref.startsWith(\"refs/tags/v\") for prod tag deploys).
    Empty string = any ref from the repository.
  EOT
  type        = string
  default     = ""
}
