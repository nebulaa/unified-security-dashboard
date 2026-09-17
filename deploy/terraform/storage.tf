resource "google_storage_bucket" "raw" {
  name                        = local.raw_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = var.storage_force_destroy

  lifecycle_rule {
    condition {
      age = 365 # 1 year retention D5
    }
    action { type = "Delete" }
  }

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket" "config" {
  name                        = local.config_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = var.storage_force_destroy

  depends_on = [google_project_service.apis]
}

# Upload the config YAMLs at apply time. Re-applies on file content change.
# Adding a new YAML here is the canonical way to ship config to prod — the
# backend reads these objects via `config_store.py` and a missing object
# returns 404 from GCS, which surfaces as a 500 on every request that
# touches the cache.
resource "google_storage_bucket_object" "ownership" {
  name         = "ownership.yaml"
  bucket       = google_storage_bucket.config.name
  source       = "${path.module}/../../config/ownership.yaml"
  content_type = "application/x-yaml"
}
resource "google_storage_bucket_object" "rbac" {
  name         = "rbac.yaml"
  bucket       = google_storage_bucket.config.name
  source       = "${path.module}/../../config/rbac.yaml"
  content_type = "application/x-yaml"
}
resource "google_storage_bucket_object" "auto_close" {
  name         = "auto_close.yaml"
  bucket       = google_storage_bucket.config.name
  source       = "${path.module}/../../config/auto_close.yaml"
  content_type = "application/x-yaml"
}
resource "google_storage_bucket_object" "sla" {
  name         = "sla.yaml"
  bucket       = google_storage_bucket.config.name
  source       = "${path.module}/../../config/sla.yaml"
  content_type = "application/x-yaml"
}
resource "google_storage_bucket_object" "component_scope" {
  name         = "component_scope.yaml"
  bucket       = google_storage_bucket.config.name
  source       = "${path.module}/../../config/component_scope.yaml"
  content_type = "application/x-yaml"
}
resource "google_storage_bucket_object" "component_registry" {
  name         = "component_registry.yaml"
  bucket       = google_storage_bucket.config.name
  source       = "${path.module}/../../config/component_registry.yaml"
  content_type = "application/x-yaml"
}
resource "google_storage_bucket_object" "wiz_subscription_pillar" {
  name         = "wiz_subscription_pillar.yaml"
  bucket       = google_storage_bucket.config.name
  source       = "${path.module}/../../config/wiz_subscription_pillar.yaml"
  content_type = "application/x-yaml"
}
resource "google_storage_bucket_object" "wiz_service_team_map" {
  name         = "wiz_service_team_map.yaml"
  bucket       = google_storage_bucket.config.name
  source       = "${path.module}/../../config/wiz_service_team_map.yaml"
  content_type = "application/x-yaml"
}
resource "google_storage_bucket_object" "jira_pentest" {
  name         = "jira_pentest.yaml"
  bucket       = google_storage_bucket.config.name
  source       = "${path.module}/../../config/jira_pentest.yaml"
  content_type = "application/x-yaml"
}

# Notify running services when any config object is updated.
resource "google_storage_notification" "config_changed" {
  bucket         = google_storage_bucket.config.name
  payload_format = "JSON_API_V1"
  topic          = google_pubsub_topic.config_changed.id
  event_types    = ["OBJECT_FINALIZE"]

  depends_on = [google_pubsub_topic_iam_member.gcs_config_publisher]
}
