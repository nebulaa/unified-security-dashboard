# Generate the Cloud SQL password as TF state. This is the only secret value TF
# manages itself; PAT + Sonar token are populated out-of-band (lifecycle ignore
# below so re-applies don't clobber operator-supplied values).

resource "random_password" "sql" {
  length  = 32
  special = false # avoid URL-encoding hassles
}

# DATABASE_URL: TCP connection to private IP, secdb DB, secdb user.
locals {
  database_url = "postgresql+psycopg://${local.sql_user}:${random_password.sql.result}@${google_sql_database_instance.pg.private_ip_address}:5432/${local.sql_db_name}"
}

resource "google_secret_manager_secret" "database_url" {
  secret_id = "secdb-database-url"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = local.database_url
}

# Placeholder secrets for credentials supplied out-of-band. The container is
# created here; the operator runs `gcloud secrets versions add ...` for the
# real value after `terraform apply` (see outputs.tf).
resource "google_secret_manager_secret" "dependabot_pat" {
  secret_id = "secdb-dependabot-pat"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}
resource "google_secret_manager_secret_version" "dependabot_pat_placeholder" {
  secret      = google_secret_manager_secret.dependabot_pat.id
  secret_data = "REPLACE_ME_dependabot_pat"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret" "sonar_token" {
  secret_id = "secdb-sonar-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}
resource "google_secret_manager_secret_version" "sonar_token_placeholder" {
  secret      = google_secret_manager_secret.sonar_token.id
  secret_data = "REPLACE_ME_sonar_token"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret" "jira_api_token" {
  secret_id = "secdb-jira-api-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}
resource "google_secret_manager_secret_version" "jira_api_token_placeholder" {
  secret      = google_secret_manager_secret.jira_api_token.id
  secret_data = "REPLACE_ME_jira_api_token"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret" "wiz_client_id" {
  secret_id = "secdb-wiz-client-id"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}
resource "google_secret_manager_secret_version" "wiz_client_id_placeholder" {
  secret      = google_secret_manager_secret.wiz_client_id.id
  secret_data = "REPLACE_ME_wiz_client_id"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

resource "google_secret_manager_secret" "wiz_client_secret" {
  secret_id = "secdb-wiz-client-secret"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}
resource "google_secret_manager_secret_version" "wiz_client_secret_placeholder" {
  secret      = google_secret_manager_secret.wiz_client_secret.id
  secret_data = "REPLACE_ME_wiz_client_secret"

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Slack incoming webhook for DLQ / ingest failure alerts (admin channel).
# Create the webhook in Slack for the target channel, then:
#   printf '%s' 'https://hooks.slack.com/services/...' | gcloud secrets versions add secdb-slack-webhook --data-file=-
resource "google_secret_manager_secret" "slack_webhook" {
  secret_id = "secdb-slack-webhook"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}
resource "google_secret_manager_secret_version" "slack_webhook_placeholder" {
  secret      = google_secret_manager_secret.slack_webhook.id
  secret_data = "REPLACE_ME_slack_webhook"

  lifecycle {
    ignore_changes = [secret_data]
  }
}
