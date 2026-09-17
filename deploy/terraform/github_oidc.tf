# GitHub Actions → GCP via Workload Identity Federation.
# Apply once per GCP project; paste outputs into GitHub repo Variables.

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
  description               = "OIDC pool for unified-security-dashboard CI/CD"
  disabled                  = false

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github_oidc" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"
  description                        = "https://token.actions.githubusercontent.com"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Ref gating belongs on the provider (assertion.* / attribute.*); SA IAM conditions
  # do not accept those keywords and fail apply with "undeclared reference".
  attribute_condition = var.github_wif_ref_condition != "" ? (
    "assertion.repository == \"${var.github_repository}\" && (${var.github_wif_ref_condition})"
  ) : "assertion.repository == \"${var.github_repository}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deployer" {
  account_id   = "secdb-deployer"
  display_name = "secdb-deployer"
  description  = "GitHub Actions deployer (Cloud Build + Terraform)"
}

locals {
  github_wif_principal = "principalSet://iam.googleapis.com/projects/${var.project_number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}/attribute.repository/${var.github_repository}"
}

resource "google_service_account_iam_member" "github_deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.github_wif_principal
}

# Broad project roles — Terraform touches most resource types in this stack.
# Tighten over time (custom role, resource-scoped grants)..
locals {
  deployer_project_roles = [
    "roles/cloudbuild.builds.editor",
    "roles/artifactregistry.writer",
    "roles/storage.admin",
    "roles/run.admin",
    "roles/iam.serviceAccountUser",
    "roles/cloudsql.admin",
    "roles/secretmanager.admin",
    "roles/iap.admin",
    "roles/compute.networkAdmin",
    "roles/cloudscheduler.admin",
    "roles/pubsub.admin",
  ]
}

resource "google_project_iam_member" "deployer" {
  for_each = toset(local.deployer_project_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

output "github_workload_identity_provider" {
  description = "Full WIF provider resource name for google-github-actions/auth (GitHub repo variable)."
  value       = google_iam_workload_identity_pool_provider.github_oidc.name
}

output "github_deployer_service_account" {
  description = "Deployer SA email for google-github-actions/auth service_account input."
  value       = google_service_account.deployer.email
}
