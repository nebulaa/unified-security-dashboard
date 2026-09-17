# Custom-mode VPC dedicated to the dashboard. Auto-mode `default` VPC was the
# source of yesterday's Cloud Run Direct VPC ↔ Cloud SQL Private IP timeout —
# auto subnets sometimes fail to propagate routes through service-networking
# peerings on the first connect. A custom VPC with one explicit /26 subnet for
# Cloud Run + a /20 PSA range avoids that.

resource "google_compute_network" "vpc" {
  name                    = local.vpc_name
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

  depends_on = [google_project_service.apis]
}

resource "google_compute_subnetwork" "cloudrun" {
  name                     = local.cr_subnet_name
  network                  = google_compute_network.vpc.id
  region                   = var.region
  ip_cidr_range            = "10.10.0.0/26" # 64 IPs — minimum for Cloud Run Direct VPC.
  private_ip_google_access = true
}

# Allocated range for service-networking (Cloud SQL Private IP).
resource "google_compute_global_address" "psa_range" {
  name          = local.psa_range_name
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.vpc.id
  address       = "10.20.0.0" # explicit so private SQL IP is predictable
}

resource "google_service_networking_connection" "psa" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa_range.name]
}

# Import/export custom routes on the peering — required for some Direct VPC
# egress paths to reach Cloud SQL through the peering.
resource "google_compute_network_peering_routes_config" "psa_routes" {
  peering              = "servicenetworking-googleapis-com"
  network              = google_compute_network.vpc.name
  import_custom_routes = true
  export_custom_routes = true

  depends_on = [google_service_networking_connection.psa]
}

# Allow internal traffic within the VPC + from PSA peer range. Cloud SQL on the
# producer side has its own firewall, but explicit allow on this side keeps
# behaviour predictable.
resource "google_compute_firewall" "allow_internal" {
  name    = "secdb-allow-internal"
  network = google_compute_network.vpc.name

  source_ranges = [
    google_compute_subnetwork.cloudrun.ip_cidr_range,
    "${google_compute_global_address.psa_range.address}/${google_compute_global_address.psa_range.prefix_length}",
  ]

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }
  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }
  allow {
    protocol = "icmp"
  }
}
