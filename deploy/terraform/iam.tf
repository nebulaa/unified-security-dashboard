# Seven service accounts, one per workload. IAM is least-priv per resource;
# project-level grants are avoided where a per-resource grant would do.

resource "google_service_account" "api" {
  account_id   = "secdb-api"
  display_name = "secdb-api"
}
resource "google_service_account" "normalizer" {
  account_id   = "secdb-normalizer"
  display_name = "secdb-normalizer"
}
resource "google_service_account" "frontend" {
  account_id   = "secdb-frontend"
  display_name = "secdb-frontend"
}
resource "google_service_account" "poller_dep" {
  account_id   = "secdb-poller-dep"
  display_name = "secdb-poller-dep"
}
resource "google_service_account" "poller_sonar" {
  account_id   = "secdb-poller-sonar"
  display_name = "secdb-poller-sonar"
}
resource "google_service_account" "poller_wiz" {
  account_id   = "secdb-poller-wiz"
  display_name = "secdb-poller-wiz"
}
resource "google_service_account" "poller_jira_pentest" {
  account_id   = "secdb-poller-jira-pentest"
  display_name = "secdb-poller-jira-pentest"
}
resource "google_service_account" "pubsub_pusher" {
  account_id   = "secdb-pubsub-pusher"
  display_name = "secdb-pubsub-pusher"
}
resource "google_service_account" "scheduler" {
  account_id   = "secdb-scheduler"
  display_name = "secdb-scheduler"
}
resource "google_service_account" "mcp" {
  account_id   = "secdb-mcp"
  display_name = "secdb-mcp"
}

# Cloud SQL client — needed even with Private IP (the IAM grant authorises the
# Cloud SQL Auth library to mint connection tokens).
resource "google_project_iam_member" "sql_client_api" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.api.email}"
}
resource "google_project_iam_member" "sql_client_normalizer" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.normalizer.email}"
}

# Pub/Sub publisher — pollers publish snapshot envelopes.
resource "google_pubsub_topic_iam_member" "publisher_dep" {
  topic  = google_pubsub_topic.ingest.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.poller_dep.email}"
}
resource "google_pubsub_topic_iam_member" "publisher_sonar" {
  topic  = google_pubsub_topic.ingest.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.poller_sonar.email}"
}
resource "google_pubsub_topic_iam_member" "publisher_wiz" {
  topic  = google_pubsub_topic.ingest.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.poller_wiz.email}"
}
resource "google_pubsub_topic_iam_member" "publisher_jira_pentest" {
  topic  = google_pubsub_topic.ingest.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.poller_jira_pentest.email}"
}
# Pub/Sub system SA also needs publisher on the DLQ topic (delivery failures).
resource "google_pubsub_topic_iam_member" "pubsub_system_dlq" {
  topic  = google_pubsub_topic.dlq.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:service-${var.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
# Pub/Sub system SA needs subscriber on the main subscription (DLQ ack semantics).
resource "google_pubsub_subscription_iam_member" "pubsub_system_sub" {
  subscription = google_pubsub_subscription.ingest.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:service-${var.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
# Pub/Sub pusher: invoke the normalizer service.
resource "google_cloud_run_v2_service_iam_member" "pubsub_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.normalizer.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pubsub_pusher.email}"
}
resource "google_cloud_run_v2_service_iam_member" "pubsub_invoker_api" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.pubsub_pusher.email}"
}

# GCS publishes object-finalize events to secdb-config-changed.
resource "google_pubsub_topic_iam_member" "gcs_config_publisher" {
  topic  = google_pubsub_topic.config_changed.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:service-${var.project_number}@gs-project-accounts.iam.gserviceaccount.com"
}

# IAP service agent invokes Cloud Run on behalf of authenticated users. Without
# this, IAP can validate sign-in but cannot forward the request to the backend
# Cloud Run service — symptom is a 403 to the user despite their being on the
# IAP allowlist.
resource "google_cloud_run_v2_service_iam_member" "iap_invoker_api" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:service-${var.project_number}@gcp-sa-iap.iam.gserviceaccount.com"

  depends_on = [google_project_service_identity.iap]
}
resource "google_cloud_run_v2_service_iam_member" "iap_invoker_frontend" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:service-${var.project_number}@gcp-sa-iap.iam.gserviceaccount.com"

  depends_on = [google_project_service_identity.iap]
}

# The frontend and MCP services call the API over the VPC using workload ID
# tokens. Application-level identity remains separate: the frontend forwards
# the IAP-authenticated user envelope and MCP forwards the user's personal
# bearer token.
resource "google_cloud_run_v2_service_iam_member" "frontend_invoker_api" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.frontend.email}"
}
resource "google_cloud_run_v2_service_iam_member" "mcp_invoker_api" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.mcp.email}"
}

# MCP service is publicly reachable on purpose — auth is bearer-token only
#. Cloud Run IAM is intentionally allUsers; the application
# rejects calls without a valid `Authorization: Bearer secdb_live_...`.
resource "google_cloud_run_v2_service_iam_member" "mcp_allusers" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.mcp.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
# Pub/Sub system SA mints OIDC tokens as the pusher SA on push.
resource "google_service_account_iam_member" "pubsub_token_creator" {
  service_account_id = google_service_account.pubsub_pusher.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${var.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# Scheduler invokes Cloud Run Jobs.
resource "google_project_iam_member" "scheduler_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.scheduler.email}"
}

# GCS access — pollers write raw, normalizer reads raw, every workload reads config.
resource "google_storage_bucket_iam_member" "raw_creator_dep" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.poller_dep.email}"
}
resource "google_storage_bucket_iam_member" "raw_creator_sonar" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.poller_sonar.email}"
}
resource "google_storage_bucket_iam_member" "raw_creator_wiz" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.poller_wiz.email}"
}
resource "google_storage_bucket_iam_member" "raw_creator_jira_pentest" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.poller_jira_pentest.email}"
}
resource "google_storage_bucket_iam_member" "raw_viewer_normalizer" {
  bucket = google_storage_bucket.raw.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.normalizer.email}"
}
resource "google_storage_bucket_iam_member" "config_viewer" {
  for_each = {
    api                 = google_service_account.api.email
    normalizer          = google_service_account.normalizer.email
    poller_dep          = google_service_account.poller_dep.email
    poller_sonar        = google_service_account.poller_sonar.email
    poller_wiz          = google_service_account.poller_wiz.email
    poller_jira_pentest = google_service_account.poller_jira_pentest.email
  }
  bucket = google_storage_bucket.config.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${each.value}"
}

# Secret Manager bindings — per-secret, per-workload.
resource "google_secret_manager_secret_iam_member" "db_url_api" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}
resource "google_secret_manager_secret_iam_member" "db_url_normalizer" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.normalizer.email}"
}
resource "google_secret_manager_secret_iam_member" "dep_pat" {
  secret_id = google_secret_manager_secret.dependabot_pat.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.poller_dep.email}"
}
resource "google_secret_manager_secret_iam_member" "sonar_token" {
  secret_id = google_secret_manager_secret.sonar_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.poller_sonar.email}"
}
resource "google_secret_manager_secret_iam_member" "wiz_client_id" {
  secret_id = google_secret_manager_secret.wiz_client_id.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.poller_wiz.email}"
}
resource "google_secret_manager_secret_iam_member" "wiz_client_secret" {
  secret_id = google_secret_manager_secret.wiz_client_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.poller_wiz.email}"
}
resource "google_secret_manager_secret_iam_member" "db_url_poller_wiz" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.poller_wiz.email}"
}
resource "google_secret_manager_secret_iam_member" "jira_api_token" {
  secret_id = google_secret_manager_secret.jira_api_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.poller_jira_pentest.email}"
}
resource "google_secret_manager_secret_iam_member" "sonar_token_api" {
  secret_id = google_secret_manager_secret.sonar_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}
resource "google_secret_manager_secret_iam_member" "slack_api" {
  secret_id = google_secret_manager_secret.slack_webhook.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.api.email}"
}
resource "google_secret_manager_secret_iam_member" "slack_normalizer" {
  secret_id = google_secret_manager_secret.slack_webhook.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.normalizer.email}"
}

# Admin API triggers poller + ownership Cloud Run Jobs on demand.
resource "google_cloud_run_v2_job_iam_member" "api_run_poller_dependabot" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.poller_dependabot.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.api.email}"
}
resource "google_cloud_run_v2_job_iam_member" "api_run_poller_sonarcloud" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.poller_sonarcloud.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.api.email}"
}
resource "google_cloud_run_v2_job_iam_member" "api_run_poller_wiz" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.poller_wiz.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.api.email}"
}
resource "google_cloud_run_v2_job_iam_member" "api_run_poller_jira_pentest" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.poller_jira_pentest.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.api.email}"
}
resource "google_cloud_run_v2_job_iam_member" "api_run_ownership_reresolve" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.ownership_reresolve.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.api.email}"
}
