# External HTTPS LB → Cloud Run via Serverless NEGs, with IAP enforced on each
# backend service. The Cloud Run services are reachable only via this LB
# (`INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER`).

resource "google_compute_global_address" "lb_ip" {
  name       = "secdb-lb-ip"
  ip_version = "IPV4"
  depends_on = [google_project_service.apis]
}

resource "google_compute_region_network_endpoint_group" "api" {
  name                  = "secdb-api-neg"
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = google_cloud_run_v2_service.api.name
  }
}

resource "google_compute_region_network_endpoint_group" "frontend" {
  name                  = "secdb-frontend-neg"
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = google_cloud_run_v2_service.frontend.name
  }
}

resource "google_compute_region_network_endpoint_group" "mcp" {
  name                  = "secdb-mcp-neg"
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = google_cloud_run_v2_service.mcp.name
  }
}

# Backend service for the API. IAP enabled. Modern IAP uses a Google-managed
# OAuth client provisioned automatically when `iap` is set with
# `enabled = true` (no client_id/secret needed).
resource "google_compute_backend_service" "api" {
  name                  = "secdb-api-bs"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTP"
  log_config {
    enable      = true
    sample_rate = 1.0
  }

  iap {
    enabled = true
  }

  backend {
    group = google_compute_region_network_endpoint_group.api.id
  }
}

resource "google_compute_backend_service" "frontend" {
  name                  = "secdb-frontend-bs"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTP"
  log_config {
    enable      = true
    sample_rate = 1.0
  }

  iap {
    enabled = true
  }

  backend {
    group = google_compute_region_network_endpoint_group.frontend.id
  }
}

# MCP backend service is intentionally NOT IAP-gated. MCP clients (Claude
# Code, Claude Desktop, Cursor) cannot complete an IAP browser flow; auth is
# enforced one layer down by the application via
# `Authorization: Bearer secdb_live_...`. Public reachability is
# acceptable because the bearer guard rejects unauthenticated calls
# (`app/mcp/client.py._headers`).
resource "google_compute_backend_service" "mcp" {
  name                  = "secdb-mcp-bs"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTP"
  log_config {
    enable      = true
    sample_rate = 1.0
  }

  backend {
    group = google_compute_region_network_endpoint_group.mcp.id
  }
}

# IAP user/group access for both backend services.
resource "google_iap_web_backend_service_iam_member" "api_users" {
  for_each            = toset(var.iap_members)
  web_backend_service = google_compute_backend_service.api.name
  role                = "roles/iap.httpsResourceAccessor"
  member              = each.key
}
resource "google_iap_web_backend_service_iam_member" "frontend_users" {
  for_each            = toset(var.iap_members)
  web_backend_service = google_compute_backend_service.frontend.name
  role                = "roles/iap.httpsResourceAccessor"
  member              = each.key
}

# URL map.
#
# `/mcp` and `/mcp/*` -> MCP backend service (no IAP, bearer-only auth).
#   FastMCP's streamable-http transport already serves at `/mcp`, so no
#   `path_prefix_rewrite` is needed — the LB forwards the path verbatim and
#   FastMCP's session manager handles it.
#
# Everything else -> frontend backend service (IAP-gated).
#   The Next.js frontend serves both the UI and the `/api/proxy/[...path]`
#   route handler. That handler is the only browser-side bridge to the API:
#   it lifts the IAP-injected `X-Goog-Authenticated-User-Email` into a
#   `X-Dev-Identity` envelope and forwards the request to the API at its
# `*.run.app` URL via the VPC.
#
# We deliberately do NOT add a `/api/*` path rule here. Previously the URL
# map had one (with `path_prefix_rewrite = "/"`) intended for direct
# browser-to-API IAP-JWT-validated calls; that bypassed the frontend proxy
# and the X-Dev-Identity envelope, breaking every API call the moment we
# switched the API to `IDENTITY_BACKEND=dev`. The rule also rewrote
# `/api/proxy/me/tokens` to `/proxy/me/tokens`, which 404'd at FastAPI.
resource "google_compute_url_map" "secdb" {
  name            = "secdb-urlmap"
  default_service = google_compute_backend_service.frontend.id

  host_rule {
    hosts        = [var.hostname]
    path_matcher = "main"
  }

  path_matcher {
    name            = "main"
    default_service = google_compute_backend_service.frontend.id

    path_rule {
      paths   = ["/mcp", "/mcp/*"]
      service = google_compute_backend_service.mcp.id
    }
  }
}

# Google-managed cert. Issuance is async — typically 10–30 min after the LB
# starts receiving traffic on the hostname (i.e. after DNS A record is added).
resource "google_compute_managed_ssl_certificate" "secdb" {
  name = "secdb-cert-v2"

  managed {
    domains = [var.hostname]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_target_https_proxy" "secdb" {
  name             = "secdb-https-proxy"
  url_map          = google_compute_url_map.secdb.id
  ssl_certificates = [google_compute_managed_ssl_certificate.secdb.id]
}

resource "google_compute_global_forwarding_rule" "secdb" {
  name                  = "secdb-https-fr"
  ip_address            = google_compute_global_address.lb_ip.id
  ip_protocol           = "TCP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  port_range            = "443"
  target                = google_compute_target_https_proxy.secdb.id
}
