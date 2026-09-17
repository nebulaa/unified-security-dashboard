# `secdb` deployment — Terraform

End-to-end deployment of the Unified Security Dashboard on GCP.

**Day-to-day rolls (images + apply):** use `./scripts/deploy-cloud.sh` (or `make cloud-deploy`). This README covers Terraform
resources, first-time bootstrap, and manual apply.

## What it deploys

- **Networking**: custom-mode VPC `secdb-vpc` + a `/26` subnet for Cloud Run + service-networking peering for Cloud SQL Private IP.
- **Data**: Cloud SQL Postgres 16 (Private IP only), GCS raw + config buckets, Pub/Sub topic + DLQ + push subscription.
- **Compute**: 4 Cloud Run services (api, normalizer, frontend, mcp) + Cloud Run jobs (migrate, dependabot/sonarcloud pollers, nightly `secdb-rollup`).
- **Schedule**: Cloud Scheduler triggers for both pollers (every 30 min).
- **Auth**: External HTTPS LB with IAP enabled on the dashboard backends + Google-managed cert for `var.hostname`. The IAP allowlist comes from `var.iap_members`. Only the IAP service agent can invoke the frontend. The frontend lifts the IAP-authenticated email into a `X-Dev-Identity` envelope and calls the API over the VPC using its Cloud Run workload identity. The MCP endpoint is publicly reachable through the LB because its client auth is `Authorization: Bearer secdb_live_...` from `/settings/mcp`; MCP separately authenticates to the private API using its workload identity while preserving the user's bearer token for application RBAC.
- **RBAC**: two roles — `admin` and `member`. Driven by `config/rbac.yaml.admin_emails` (admin grants by email) and the LB-level IAP allowlist (member access).
- **IAM**: 7 service accounts, least-privilege, per-resource bindings.

State backend: GCS bucket per project (`<project_id>-tfstate`, prefix `secdb`). The backend
block is partial — pass bucket at init (see below).

## Prerequisites

1. `gcloud auth application-default login` (TF reads ADC).
2. Backend image + frontend image already pushed to Artifact Registry. The `image_tag` variable selects which tag Cloud Run pulls. The first apply uses `latest`, which assumes you've run Cloud Build at least once. The bootstrap path is:
   ```bash
   gcloud builds submit --config ../../cloudbuild.yaml \
     --project "$GCP_PROJECT" ../..
   ```
3. The config YAMLs (`config/ownership.yaml`, `component_registry.yaml`, `component_scope.yaml`, `rbac.yaml`, `auto_close.yaml`, `sla.yaml`) exist at the repo root — TF uploads them to the config bucket.

## Apply

```bash
cd deploy/terraform
terraform init \
  -backend-config="bucket=${GCP_PROJECT}-tfstate" \
  -backend-config="prefix=secdb"
terraform plan -var-file=stage.tfvars -out=secdb.tfplan
terraform apply secdb.tfplan
```

**GitHub Actions / CI:** same init flags; `deploy-cloud.sh` sets `TF_BACKEND_BUCKET` and
`TF_VAR_FILE` automatically. WIF outputs: `terraform output github_workload_identity_provider`
and `github_deployer_service_account`.

Expect ~15 minutes for the first apply. Cloud SQL is the slowest item (~6 min); the managed cert lands in `PROVISIONING` state and stays there until DNS is in place.

## After apply — manual steps

`terraform output manual_steps` prints the operator checklist (secrets, DNS, cert,
smoke test, optional pollers, **`secdb-rollup` 30-day backfill**).

In short, after first apply you still need to:

1. Populate the two operator secrets (Dependabot PAT, Sonar token).
2. Add a DNS A record `<hostname> → <lb_ip>` at your registrar / Cloud DNS.
3. Wait for the Google-managed cert to issue (10–30 min after DNS).
4. Smoke-test in a browser at `https://<hostname>/`.

## Image updates

Cloud Build pushes `:latest` and `:<build-id>`. Re-run apply with the new tag to roll Cloud Run.

Use `./scripts/deploy-cloud.sh` for the full deploy script
reference (change detection, flags, migrate, troubleshooting). Quick examples:

```bash
./scripts/deploy-cloud.sh              # or: make cloud-deploy
./scripts/deploy-cloud.sh --all
./scripts/deploy-cloud.sh --backend --migrate
```

Manual pin (when not using the script):

```bash
# Roll only the API + normalizer:
terraform apply -var=image_tag_backend=<build-id>

# Roll only the frontend:
terraform apply -var=image_tag_frontend=<build-id>

# Roll both at once (legacy single-tag knob, applied to whichever side has its
# per-service variable empty):
terraform apply -var=image_tag=<build-id>
```

`latest` works for ad-hoc deploys; pinning to a build ID is strongly recommended for any deploy you plan to roll back.

## Auth knobs

| Variable | What it gates |
|---|---|
| `var.iap_members` | Who can reach the system at all. Anything not on this list gets a Google "you don't have permission" page. |
| `var.iap_default_groups` | The group list the frontend stamps onto the `X-Dev-Identity` envelope after IAP authenticates a browser request. Empty by default; set it for your identity policy. |
| `config/rbac.yaml.admin_emails` | Who is admin. Uploaded to GCS by `terraform apply`; the API picks the change up on its next config-cache refresh (~10 minutes) or after a service roll. |
| `var.hostname` | The Google-managed cert SAN. Must match the DNS record. |

To grant or revoke admin: edit `config/rbac.yaml`, run `terraform apply`, optionally `gcloud run services update secdb-api --region=... --revision-suffix=cfg-$(date +%s)` to force-pull. To onboard a new IAP user: edit `var.iap_members` (or its underlying tfvars file) and `terraform apply`.

## Tearing down

```bash
terraform destroy
```

By default Cloud SQL has `deletion_protection` enabled and GCS buckets do not
allow `force_destroy`. Disposable environments can set `sql_deletion_protection = false`
and `storage_force_destroy = true` in the env tfvars (not committed) so `terraform destroy`
can tear the stack down including non-empty buckets.
