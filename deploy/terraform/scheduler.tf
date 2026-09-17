# Cloud Scheduler triggers for pollers (every 30 min).
resource "google_cloud_scheduler_job" "poll_dependabot" {
  name             = "secdb-poll-dependabot"
  region           = var.region
  schedule         = var.poller_schedule
  time_zone        = "Etc/UTC"
  attempt_deadline = "320s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.poller_dependabot.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_project_iam_member.scheduler_run_invoker]
}

resource "google_cloud_scheduler_job" "poll_sonarcloud" {
  name             = "secdb-poll-sonarcloud"
  region           = var.region
  schedule         = var.poller_schedule
  time_zone        = "Etc/UTC"
  attempt_deadline = "320s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.poller_sonarcloud.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_project_iam_member.scheduler_run_invoker]
}

resource "google_cloud_scheduler_job" "poll_wiz" {
  name             = "secdb-poll-wiz"
  region           = var.region
  schedule         = var.poller_schedule
  time_zone        = "Etc/UTC"
  attempt_deadline = "320s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.poller_wiz.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_project_iam_member.scheduler_run_invoker]
}

resource "google_cloud_scheduler_job" "poll_jira_pentest" {
  name             = "secdb-poll-jira-pentest"
  region           = var.region
  schedule         = var.jira_pentest_poller_schedule
  time_zone        = "Etc/UTC"
  attempt_deadline = "320s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.poller_jira_pentest.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_project_iam_member.scheduler_run_invoker]
}

resource "google_cloud_scheduler_job" "rollup" {
  name             = "secdb-rollup"
  region           = var.region
  schedule         = "0 1 * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "1800s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.rollup.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [google_project_iam_member.scheduler_run_invoker]
}
