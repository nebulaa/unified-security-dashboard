# Three services + three jobs from one backend image + one frontend image.
# Service vs job is chosen by entrypoint override; the image itself is fungible.

# ---------- Migrate Job ----------
# Runs alembic upgrade head. Triggered manually (or by Cloud Build) on each
# deploy; not on a schedule.
resource "google_cloud_run_v2_job" "migrate" {
  name                = "secdb-migrate"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.api.email # reuses api SA (has cloudsql.client + db secret access)
      timeout         = "600s"

      vpc_access {
        network_interfaces {
          network    = google_compute_network.vpc.id
          subnetwork = google_compute_subnetwork.cloudrun.id
        }
        egress = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image   = local.backend_image
        command = ["python"]
        args    = ["-m", "app.migrate", "upgrade", "head"]

        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.key
            value = env.value
          }
        }

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }

      max_retries = 1
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.db_url_api,
    google_sql_user.secdb,
  ]
}

# ---------- API Service ----------
resource "google_cloud_run_v2_service" "api" {
  name     = "secdb-api"
  location = var.region
  # INTERNAL_LOAD_BALANCER is the right endpoint for browser traffic, but the
  # frontend Cloud Run service also needs to reach the API server-side (SSR
  # `serverFetch` + the Next.js `/api/proxy` route). Internal Cloud Run-to-
  # Cloud Run calls (egress=ALL_TRAFFIC) ARE classified as LB traffic, hence
  # opening to LOAD_BALANCER (LB) here is enough. Cloud Run IAM is also
  # enforced: internal callers mint workload identity tokens for this service.
  ingress             = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  deletion_protection = false

  template {
    service_account                  = google_service_account.api.email
    max_instance_request_concurrency = 80

    scaling {
      min_instance_count = 1
      max_instance_count = 3
    }

    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.cloudrun.id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image   = local.backend_image
      command = ["uvicorn"]
      args    = ["app.api.main:app", "--host", "0.0.0.0", "--port", "8080"]

      ports {
        container_port = 8080
      }

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }
      # IDENTITY_BACKEND=dev with ENV=local. Why not "iap":
      #   1. Google's edge scrubs `X-Goog-*` headers from non-IAP traffic, so
      #      the frontend SSR can't forward the IAP JWT to the API directly.
      #   2. The API's external LB IP isn't reachable from the same VPC
      #      (hairpin), so SSR can't route through the LB either.
      #   3. With ingress=INTERNAL_LOAD_BALANCER, only the LB (IAP-enforced)
      #      and same-project VPC traffic can reach this service. Cloud Run IAM
      #      further restricts direct calls to explicit workload identities.
      # The frontend lifts the user's identity from the IAP-injected
      # X-Goog-Authenticated-User-Email header on inbound requests.
      env {
        name  = "IDENTITY_BACKEND"
        value = "dev"
      }
      env {
        name  = "ENV"
        value = "local" # required by the IDENTITY_BACKEND=dev validator
      }
      # IAP_AUDIENCE is unused while IDENTITY_BACKEND=dev, but kept so a future
      # switch back to "iap" doesn't need a separate env-var revision. Bootstrap
      # placeholder; `terraform_data.api_iap_audience` patches the real value
      # via gcloud after the LB backend service exists.
      env {
        name  = "IAP_AUDIENCE"
        value = "PLACEHOLDER_PATCHED_BY_TF_AFTER_LB"
      }
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name  = "GITHUB_ORG"
        value = var.github_org
      }
      env {
        name = "SLACK_WEBHOOK_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.slack_webhook.secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      startup_probe {
        http_get {
          path = "/health"
        }
        initial_delay_seconds = 5
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 30 # tolerate slow first DB connect on Direct VPC
      }
    }
  }

  lifecycle {
    # Once `null_resource.api_iap_audience` patches the real IAP_AUDIENCE value,
    # we don't want TF to revert it. Trade-off: env-var changes to the API
    # service after first apply must be done via gcloud or by temporarily
    # removing this block. For prototype scope this is acceptable.
    ignore_changes = [template[0].containers[0].env]
  }

  depends_on = [
    google_secret_manager_secret_iam_member.db_url_api,
    google_secret_manager_secret_iam_member.sonar_token_api,
    google_secret_manager_secret_iam_member.slack_api,
    google_cloud_run_v2_job_iam_member.api_run_poller_dependabot,
    google_cloud_run_v2_job_iam_member.api_run_poller_sonarcloud,
    google_cloud_run_v2_job_iam_member.api_run_ownership_reresolve,
    google_cloud_run_v2_job.migrate, # ensure schema is applied before API serves
  ]
}

# Patch API runtime env vars that Terraform intentionally ignores after service
# creation (see lifecycle.ignore_changes above). Env vars stamped here:
#   - IAP_AUDIENCE:    real backend service ID (only known after the LB exists).
#   - SONAR_ORG:       SonarCloud organizations available to the API.
#   - MCP_SERVER_URL:  surfaced via /me/mcp-config so setup snippets point at
#                      the LB-served MCP URL (stable across MCP redeploys).
#   - INGEST_TRANSPORT, GCP_REGION, PUBSUB_PROJECT: required for the API to
#                      detect it is running in GCP mode (admin ownership panel
#                      trigger_mode=cloud_run, poller admin routes, etc.). They
#                      exist in common_env but ignore_changes blocks them from
#                      reaching the service after the first apply.
resource "terraform_data" "api_iap_audience" {
  triggers_replace = [
    google_compute_backend_service.api.generated_id,
    google_cloud_run_v2_service.api.name,
    var.sonar_orgs,
    var.hostname,
    var.region,
    var.project_id,
  ]

  provisioner "local-exec" {
    command = <<-EOT
      gcloud run services update ${google_cloud_run_v2_service.api.name} \
        --region=${var.region} --project=${var.project_id} \
        --update-env-vars="^|^IAP_AUDIENCE=/projects/${var.project_number}/global/backendServices/${google_compute_backend_service.api.generated_id}|SONAR_ORG=${var.sonar_orgs}|MCP_SERVER_URL=https://${var.hostname}/mcp|INGEST_TRANSPORT=pubsub|GCP_REGION=${var.region}|PUBSUB_PROJECT=${var.project_id}"
    EOT
  }

  depends_on = [
    google_cloud_run_v2_service.mcp,
    google_compute_url_map.secdb,
  ]
}

# ---------- Normalizer Service ----------
resource "google_cloud_run_v2_service" "normalizer" {
  name                = "secdb-normalizer"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY" # only Pub/Sub push reaches it
  deletion_protection = false

  template {
    service_account = google_service_account.normalizer.email

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.cloudrun.id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image   = local.backend_image
      command = ["uvicorn"]
      args    = ["app.normalizer.main:app", "--host", "0.0.0.0", "--port", "8080"]

      ports {
        container_port = 8080
      }

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SLACK_WEBHOOK_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.slack_webhook.secret_id
            version = "latest"
          }
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.db_url_normalizer,
    google_secret_manager_secret_iam_member.slack_normalizer,
  ]
}

# ---------- Frontend Service ----------
resource "google_cloud_run_v2_service" "frontend" {
  name                = "secdb-frontend"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  deletion_protection = false

  template {
    service_account = google_service_account.frontend.email

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    # ALL_TRAFFIC (not PRIVATE_RANGES_ONLY): the frontend calls the API at its
    # *.run.app URL, which resolves to a public IP. With ALL_TRAFFIC the
    # outbound call traverses the VPC and Cloud Run treats it as internal —
    # the API's ingress accepts it, then IAM validates the frontend ID token.
    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.cloudrun.id
      }
      egress = "ALL_TRAFFIC"
    }

    containers {
      image = local.frontend_image
      ports {
        container_port = 8080
      }

      env {
        name  = "ENV"
        value = "prod"
      }
      # SSR fetches go straight to the API's *.run.app URL via the VPC. The
      # external LB IP isn't reachable from the same VPC (hairpin), so we
      # cannot route SSR through the LB. The API trusts X-Dev-Identity for
      # internal callers; see the API service block above for why.
      env {
        name  = "API_BASE_URL"
        value = google_cloud_run_v2_service.api.uri
      }
      env {
        name  = "CLOUD_RUN_API_AUDIENCE"
        value = google_cloud_run_v2_service.api.uri
      }
      # Groups injected as the user's group membership in the X-Dev-Identity
      # envelope when an IAP-authenticated request arrives. IAP forwards the
      # email but not Google group membership; the LB IAP allowlist already
      # gates who can reach us, so any caller is trusted to carry these.
      # Configure this only for groups admitted by the deployment's IAP policy.
      env {
        name  = "IAP_DEFAULT_GROUPS"
        value = var.iap_default_groups
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }
    }
  }
}

# ---------- MCP Service (hosted streamable-http) ----------
# Reachable only via the LB at `https://${var.hostname}/mcp` (no IAP on that
# backend service — auth is `Authorization: Bearer secdb_live_...` at the
# application layer). Direct *.run.app calls are blocked by
# `INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER` so there is exactly one trusted
# entry path (the LB's serverless-NEG invocation is classified as internal).
# The MCP process sends its workload ID token plus the user's bearer token to
# the API at its *.run.app URL via the VPC, so Cloud Run IAM and API RBAC are
# both enforced. No DB access, no secrets — the MCP server is pure passthrough.
resource "google_cloud_run_v2_service" "mcp" {
  name                = "secdb-mcp"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  deletion_protection = false

  template {
    service_account = google_service_account.mcp.email

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    # ALL_TRAFFIC so outbound calls to the API at *.run.app traverse the VPC
    # and are accepted by the API's ingress; the MCP workload ID token then
    # satisfies the API's Cloud Run IAM check.
    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.cloudrun.id
      }
      egress = "ALL_TRAFFIC"
    }

    containers {
      image   = local.backend_image
      command = ["secdb-mcp"]

      ports {
        container_port = 8080
      }

      env {
        name  = "ENV"
        value = "prod"
      }
      env {
        name  = "MCP_TRANSPORT"
        value = "streamable-http"
      }
      env {
        name  = "MCP_HOST"
        value = "0.0.0.0"
      }
      env {
        name  = "MCP_PORT"
        value = "8080"
      }
      env {
        name  = "MCP_API_BASE_URL"
        value = google_cloud_run_v2_service.api.uri
      }
      env {
        name  = "CLOUD_RUN_API_AUDIENCE"
        value = google_cloud_run_v2_service.api.uri
      }
      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }
    }
  }
}

# ---------- Poller Jobs ----------
resource "google_cloud_run_v2_job" "poller_dependabot" {
  name                = "secdb-poller-dependabot"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.poller_dep.email
      timeout         = "900s"

      containers {
        image   = local.backend_image
        command = ["python"]
        args    = ["-m", "app.pollers.dependabot"]

        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.key
            value = env.value
          }
        }
        env {
          name  = "GITHUB_ORG"
          value = var.github_org
        }
        env {
          name = "DEPENDABOT_PAT"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.dependabot_pat.secret_id
              version = "latest"
            }
          }
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }

      max_retries = 1
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.dep_pat,
  ]
}

resource "google_cloud_run_v2_job" "poller_sonarcloud" {
  name                = "secdb-poller-sonarcloud"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.poller_sonar.email
      timeout         = "900s"

      containers {
        image   = local.backend_image
        command = ["python"]
        args    = ["-m", "app.pollers.sonarcloud"]

        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.key
            value = env.value
          }
        }
        env {
          name = "SONAR_TOKEN"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.sonar_token.secret_id
              version = "latest"
            }
          }
        }

        # 2Gi: Sonar issue `flows` (taint graphs) + GSM/grpc baseline previously
        # OOM'd at 512Mi/1Gi. Poller now prunes flows and prefers env SONAR_TOKEN
        # (skips GSM client); keep headroom for Pub/Sub/GCS clients at publish.
        resources {
          limits = {
            cpu    = "1"
            memory = "2Gi"
          }
        }
      }

      max_retries = 1
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.sonar_token,
  ]
}

resource "google_cloud_run_v2_job" "poller_wiz" {
  name                = "secdb-poller-wiz"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.poller_wiz.email
      timeout         = "900s"

      containers {
        image   = local.backend_image
        command = ["python"]
        args    = ["-m", "app.pollers.wiz"]

        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.key
            value = env.value
          }
        }
        env {
          name  = "WIZ_API_URL"
          value = var.wiz_api_url
        }
        env {
          name = "WIZ_CLIENT_ID"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.wiz_client_id.secret_id
              version = "latest"
            }
          }
        }
        env {
          name = "WIZ_CLIENT_SECRET"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.wiz_client_secret.secret_id
              version = "latest"
            }
          }
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }

      max_retries = 1
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.wiz_client_id,
    google_secret_manager_secret_iam_member.wiz_client_secret,
  ]
}

resource "google_cloud_run_v2_job" "poller_jira_pentest" {
  name                = "secdb-poller-jira-pentest"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.poller_jira_pentest.email
      timeout         = "900s"

      containers {
        image   = local.backend_image
        command = ["python"]
        args    = ["-m", "app.pollers.jira_pentest"]

        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.key
            value = env.value
          }
        }
        env {
          name  = "JIRA_BASE_URL"
          value = var.jira_base_url
        }
        env {
          name  = "JIRA_API_EMAIL"
          value = var.jira_api_email
        }
        env {
          name = "JIRA_API_TOKEN"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.jira_api_token.secret_id
              version = "latest"
            }
          }
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }

      max_retries = 1
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.jira_api_token,
  ]
}

# ---------- Nightly Rollup Job ----------
resource "google_cloud_run_v2_job" "rollup" {
  name                = "secdb-rollup"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.api.email
      timeout         = "1800s"

      vpc_access {
        network_interfaces {
          network    = google_compute_network.vpc.id
          subnetwork = google_compute_subnetwork.cloudrun.id
        }
        egress = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image   = local.backend_image
        command = ["python"]
        args    = ["-m", "app.jobs.rollup"]

        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.key
            value = env.value
          }
        }

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }

      max_retries = 1
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.db_url_api,
  ]
}

# ---------- Ownership re-resolve Job ----------
resource "google_cloud_run_v2_job" "ownership_reresolve" {
  name                = "secdb-ownership-reresolve"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.api.email
      timeout         = "1800s"

      vpc_access {
        network_interfaces {
          network    = google_compute_network.vpc.id
          subnetwork = google_compute_subnetwork.cloudrun.id
        }
        egress = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image   = local.backend_image
        command = ["python"]
        args    = ["-m", "app.jobs.ownership_reresolve"]

        dynamic "env" {
          for_each = local.common_env
          content {
            name  = env.key
            value = env.value
          }
        }

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }
      }

      max_retries = 1
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.db_url_api,
  ]
}

# Patch OIDC audiences for Pub/Sub push endpoints (normalizer + API service URLs).
resource "terraform_data" "pubsub_oidc_audiences" {
  triggers_replace = [
    google_cloud_run_v2_service.normalizer.uri,
    google_cloud_run_v2_service.api.uri,
    google_cloud_run_v2_service.normalizer.name,
    google_cloud_run_v2_service.api.name,
  ]

  provisioner "local-exec" {
    command = <<-EOT
      gcloud run services update ${google_cloud_run_v2_service.normalizer.name} \
        --region=${var.region} --project=${var.project_id} \
        --update-env-vars="OIDC_AUDIENCE=${google_cloud_run_v2_service.normalizer.uri}"
      gcloud run services update ${google_cloud_run_v2_service.api.name} \
        --region=${var.region} --project=${var.project_id} \
        --update-env-vars="OIDC_AUDIENCE=${google_cloud_run_v2_service.api.uri}"
    EOT
  }

  depends_on = [
    google_cloud_run_v2_service.normalizer,
    google_cloud_run_v2_service.api,
  ]
}
