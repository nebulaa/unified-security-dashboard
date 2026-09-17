locals {
  # Naming
  ar_repo                 = "secdb"
  vpc_name                = "secdb-vpc"
  cr_subnet_name          = "secdb-cloudrun-${var.region}"
  psa_range_name          = "secdb-psa-range"
  raw_bucket              = "${var.project_id}-secdb-raw"
  config_bucket           = "${var.project_id}-secdb-config"
  ingest_topic            = "secdb-ingest-raw"
  dlq_topic               = "secdb-ingest-raw-dlq"
  ingest_subscription     = "secdb-ingest-raw-normalizer"
  dlq_subscription        = "secdb-ingest-raw-dlq-handler"
  config_changed_topic    = "secdb-config-changed"
  config_changed_api_sub  = "secdb-config-changed-api"
  config_changed_norm_sub = "secdb-config-changed-normalizer"
  sql_instance_name       = "secdb-pg"
  sql_db_name             = "secdb"
  sql_user                = "secdb"

  # Image references — Cloud Build pushes here; Cloud Run reads. Each component
  # can be pinned independently via image_tag_{backend,frontend}; otherwise we
  # fall back to the single image_tag default.
  ar_host            = "${var.region}-docker.pkg.dev"
  backend_image_tag  = var.image_tag_backend != "" ? var.image_tag_backend : var.image_tag
  frontend_image_tag = var.image_tag_frontend != "" ? var.image_tag_frontend : var.image_tag
  backend_image      = "${local.ar_host}/${var.project_id}/${local.ar_repo}/backend:${local.backend_image_tag}"
  frontend_image     = "${local.ar_host}/${var.project_id}/${local.ar_repo}/frontend:${local.frontend_image_tag}"

  # Service account emails (created in iam.tf)
  sa = {
    api          = google_service_account.api.email
    normalizer   = google_service_account.normalizer.email
    frontend     = google_service_account.frontend.email
    poller_dep   = google_service_account.poller_dep.email
    poller_sonar = google_service_account.poller_sonar.email
    pubsub       = google_service_account.pubsub_pusher.email
    scheduler    = google_service_account.scheduler.email
  }

  # Common env vars for backend services + jobs.
  common_env = {
    ENV                 = "prod"
    RAW_STORE           = "gcs"
    CONFIG_STORE        = "gcs"
    SECRET_BACKEND      = "gsm"
    INGEST_TRANSPORT    = "pubsub"
    GCS_RAW_BUCKET      = local.raw_bucket
    GCS_CONFIG_BUCKET   = local.config_bucket
    SONAR_ORG           = var.sonar_orgs
    GITHUB_ORG          = var.github_org
    PUBSUB_PROJECT      = var.project_id
    PUBSUB_INGEST_TOPIC = local.ingest_topic
    GCP_REGION          = var.region
    LOG_LEVEL           = var.log_level
  }
}
