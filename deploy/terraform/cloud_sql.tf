resource "google_sql_database_instance" "pg" {
  name             = local.sql_instance_name
  database_version = "POSTGRES_16"
  region           = var.region

  deletion_protection = var.sql_deletion_protection

  settings {
    tier            = var.sql_tier
    edition         = "ENTERPRISE"
    disk_size       = var.sql_storage_gb
    disk_type       = "PD_SSD"
    disk_autoresize = true

    ip_configuration {
      ipv4_enabled                                  = false # private IP only
      private_network                               = google_compute_network.vpc.id
      enable_private_path_for_google_cloud_services = true
      ssl_mode                                      = "ALLOW_UNENCRYPTED_AND_ENCRYPTED"
    }

    backup_configuration {
      enabled    = true
      start_time = "03:00"
    }

    insights_config {
      query_insights_enabled = true
    }
  }

  depends_on = [
    google_service_networking_connection.psa,
  ]
}

resource "google_sql_database" "secdb" {
  name     = local.sql_db_name
  instance = google_sql_database_instance.pg.name
}

resource "google_sql_user" "secdb" {
  name     = local.sql_user
  instance = google_sql_database_instance.pg.name
  password = random_password.sql.result
}
