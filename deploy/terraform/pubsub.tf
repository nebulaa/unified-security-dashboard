resource "google_pubsub_topic" "ingest" {
  name       = local.ingest_topic
  depends_on = [google_project_service.apis]
}

resource "google_pubsub_topic" "dlq" {
  name       = local.dlq_topic
  depends_on = [google_project_service.apis]
}

resource "google_pubsub_topic" "config_changed" {
  name       = local.config_changed_topic
  depends_on = [google_project_service.apis]
}

# Push subscription → normalizer. The endpoint URL depends on the normalizer
# service URL which TF only learns after Cloud Run is created (cloud_run.tf).
resource "google_pubsub_subscription" "ingest" {
  name  = local.ingest_subscription
  topic = google_pubsub_topic.ingest.id

  ack_deadline_seconds = 600

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.normalizer.uri}/internal/normalize"
    oidc_token {
      service_account_email = google_service_account.pubsub_pusher.email
      audience              = google_cloud_run_v2_service.normalizer.uri
    }
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dlq.id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

# DLQ handler — persists permanently-failed ingest envelopes.
resource "google_pubsub_subscription" "dlq_handler" {
  name  = local.dlq_subscription
  topic = google_pubsub_topic.dlq.id

  ack_deadline_seconds = 60

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.normalizer.uri}/internal/dlq"
    oidc_token {
      service_account_email = google_service_account.pubsub_pusher.email
      audience              = google_cloud_run_v2_service.normalizer.uri
    }
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dlq.id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

resource "google_pubsub_subscription" "config_changed_api" {
  name  = local.config_changed_api_sub
  topic = google_pubsub_topic.config_changed.id

  ack_deadline_seconds = 60

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.api.uri}/internal/config-reload"
    oidc_token {
      service_account_email = google_service_account.pubsub_pusher.email
      audience              = google_cloud_run_v2_service.api.uri
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

resource "google_pubsub_subscription" "config_changed_normalizer" {
  name  = local.config_changed_norm_sub
  topic = google_pubsub_topic.config_changed.id

  ack_deadline_seconds = 60

  push_config {
    push_endpoint = "${google_cloud_run_v2_service.normalizer.uri}/internal/config-reload"
    oidc_token {
      service_account_email = google_service_account.pubsub_pusher.email
      audience              = google_cloud_run_v2_service.normalizer.uri
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}
