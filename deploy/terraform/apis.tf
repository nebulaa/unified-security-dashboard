locals {
  required_apis = [
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudscheduler.googleapis.com",
    "pubsub.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "sqladmin.googleapis.com",
    "servicenetworking.googleapis.com",
    "vpcaccess.googleapis.com",
    "iap.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "certificatemanager.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.required_apis)
  service  = each.key

  disable_on_destroy = false
}

# IAP's Google-managed agent is not created by enabling the API alone.
# Cloud Run invoker bindings fail with 400 until this identity exists.
resource "google_project_service_identity" "iap" {
  provider = google-beta
  project  = var.project_id
  service  = "iap.googleapis.com"

  depends_on = [google_project_service.apis]
}
