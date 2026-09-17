output "lb_ip" {
  description = "Static IP for the LB. Add a DNS A record (hostname is in `hostname` output) pointing at this IP."
  value       = google_compute_global_address.lb_ip.address
}

output "hostname" {
  description = "Hostname the LB is configured for."
  value       = var.hostname
}

output "api_url_internal" {
  description = "Cloud Run direct URL for the API. Reachable only via LB (ingress=INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER) once the LB is wired."
  value       = google_cloud_run_v2_service.api.uri
}

output "frontend_url_internal" {
  description = "Cloud Run direct URL for the frontend. Reachable only via LB."
  value       = google_cloud_run_v2_service.frontend.uri
}

output "normalizer_url_internal" {
  description = "Cloud Run direct URL for the normalizer. Reachable only by Pub/Sub push."
  value       = google_cloud_run_v2_service.normalizer.uri
}

output "mcp_url" {
  description = "Public URL for the hosted MCP server (streamable-http), served via the LB on the same hostname as the dashboard. Auth is bearer-only — tokens minted at /settings/mcp. The Cloud Run service has internal-LB-only ingress, so the *.run.app URL is unreachable from the public internet."
  value       = "https://${var.hostname}/mcp"
}

output "sql_private_ip" {
  description = "Cloud SQL Private IP. Cloud Run reaches this via Direct VPC egress + the PSA peering."
  value       = google_sql_database_instance.pg.private_ip_address
}

output "sql_connection_name" {
  description = "Cloud SQL instance connection name (project:region:instance)."
  value       = google_sql_database_instance.pg.connection_name
}

output "api_backend_service_id" {
  description = "Backend service ID. Used as IAP_AUDIENCE on the API."
  value       = google_compute_backend_service.api.generated_id
}

output "manual_steps" {
  description = "Things you must do by hand after `terraform apply` succeeds."
  value       = <<-EOT

    ============================================================
    Manual steps to complete bring-up
    ============================================================

    1. Populate the two operator secrets:

       printf '%s' "<your GitHub PAT>" | gcloud secrets versions add secdb-dependabot-pat \
         --data-file=- --project=${var.project_id}

       printf '%s' "<your SonarCloud token>" | gcloud secrets versions add secdb-sonar-token \
         --data-file=- --project=${var.project_id}

       printf '%s' "<optional Slack Workflow trigger URL>" | gcloud secrets versions add secdb-slack-webhook \
         --data-file=- --project=${var.project_id}

    2. Create a DNS A record at your registrar (or in the relevant
       Cloud DNS zone):

           ${var.hostname}.  IN  A  ${google_compute_global_address.lb_ip.address}

    3. Wait 10–30 minutes for the Google-managed cert to issue. Track:

           gcloud compute ssl-certificates describe secdb-cert \
             --global --project=${var.project_id} \
             --format='value(managed.status,managed.domainStatus)'

    4. Verify in a browser:

           https://${var.hostname}/

       You should be redirected through Google sign-in (IAP), then land
       on the dashboard.

    5. (Optional) Run a poller once to seed findings:

           gcloud run jobs execute secdb-poller-dependabot --region=${var.region} \
             --project=${var.project_id} --wait
           gcloud run jobs execute secdb-poller-sonarcloud --region=${var.region} \
             --project=${var.project_id} --wait

    6. REQUIRED on new deployments — backfill daily_metrics (trend charts):

       /metrics/trend reads pre-aggregated rows; the 01:00 UTC scheduler only
       rolls up yesterday. After ingest, run once:

           gcloud run jobs execute secdb-rollup --region=${var.region} \
             --project=${var.project_id} --wait \
             --args="-m,app.jobs.rollup,--backfill-days,30"

       Do NOT use `make rollup-backfill` for prod — that targets local Postgres
       via .env.local DATABASE_URL.

    ============================================================
  EOT
}
