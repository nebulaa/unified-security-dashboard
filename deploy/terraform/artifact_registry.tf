resource "google_artifact_registry_repository" "secdb" {
  location      = var.region
  repository_id = local.ar_repo
  format        = "DOCKER"
  description   = "Unified Security Dashboard images (backend + frontend)"

  depends_on = [google_project_service.apis]
}
