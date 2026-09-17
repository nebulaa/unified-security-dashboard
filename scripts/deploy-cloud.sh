#!/usr/bin/env bash
# Build Cloud Run images when relevant paths changed, apply Terraform, optionally run migrate.
#
# Make shortcut:   make cloud-deploy [ARGS="--all"]
#
# Usage:
#   ./scripts/deploy-cloud.sh              # detect changes vs origin/main, deploy what changed
#   ./scripts/deploy-cloud.sh --all        # rebuild backend + frontend + full terraform apply + migrate
#   ./scripts/deploy-cloud.sh --backend    # backend image + terraform (backend tag only)
#   ./scripts/deploy-cloud.sh --frontend   # frontend image + terraform (frontend tag only)
#   ./scripts/deploy-cloud.sh --terraform  # terraform apply only (infra/config, no Cloud Build)
#   ./scripts/deploy-cloud.sh --migrate    # also run secdb-migrate after apply
#   ./scripts/deploy-cloud.sh --ci         # non-interactive (GitHub Actions; requires CI=true)
#
# Environment overrides:
#   GCP_PROJECT, GCP_REGION, SINCE_REF (git ref for change detection, default origin/main)
#   TF_BACKEND_BUCKET (default: ${GCP_PROJECT}-tfstate)
#   TF_VAR_FILE — optional override (e.g. stage.tfvars); otherwise auto-selected from
#                 deploy/terraform/*.tfvars by matching project_id to GCP_PROJECT

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${REPO_ROOT}/deploy/terraform"
STATE_FILE="${REPO_ROOT}/.deploy-state.json"

GCP_PROJECT="${GCP_PROJECT:?Set GCP_PROJECT to your target GCP project ID}"
GCP_REGION="${GCP_REGION:-europe-west1}"
SINCE_REF="${SINCE_REF:-origin/main}"
TF_BACKEND_BUCKET="${TF_BACKEND_BUCKET:-${GCP_PROJECT}-tfstate}"
TF_VAR_FILE="${TF_VAR_FILE:-}"

DO_BACKEND=false
DO_FRONTEND=false
DO_TERRAFORM=false
DO_MIGRATE=false
FORCE_ALL=false
SKIP_BUILD=false
SKIP_TERRAFORM=false
PLAN_ONLY=false
AUTO_APPROVE=true
CI_MODE=false

# Progress goes to stderr so command substitutions (e.g. $(submit_build …))
# capture only the build id on stdout.
log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m!!>\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

validate_build_id() {
  local id="$1"
  local label="$2"
  # Cloud Build ids are UUIDs (8-4-4-4-12 hex).
  if [[ ! "$id" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
    die "invalid Cloud Build id for ${label} (log output may have leaked into capture): ${id@Q}"
  fi
}

# Resolve the Terraform var-file before any apply. Tenant-specific values (e.g.
# wiz_api_url) live in *.tfvars — applying without one resets them to defaults.
resolve_tf_var_file() {
  local candidate path project_id tfvars

  if [[ -n "$TF_VAR_FILE" ]]; then
    for candidate in "$TF_VAR_FILE" "${TF_DIR}/${TF_VAR_FILE}" "${REPO_ROOT}/${TF_VAR_FILE}"; do
      if [[ -f "$candidate" ]]; then
        TF_VAR_FILE="$(cd "$(dirname "$candidate")" && pwd)/$(basename "$candidate")"
        return 0
      fi
    done
    die "TF_VAR_FILE not found: ${TF_VAR_FILE@Q} (tried cwd, ${TF_DIR}/, repo root)"
  fi

  for tfvars in "${TF_DIR}"/*.tfvars; do
    [[ -f "$tfvars" ]] || continue
    project_id="$(
      grep -E '^[[:space:]]*project_id[[:space:]]*=' "$tfvars" 2>/dev/null \
        | head -1 \
        | sed -E 's/.*=[[:space:]]*"([^"]+)".*/\1/'
    )"
    if [[ "$project_id" == "$GCP_PROJECT" ]]; then
      TF_VAR_FILE="$(cd "$(dirname "$tfvars")" && pwd)/$(basename "$tfvars")"
      return 0
    fi
  done

  die "No Terraform var-file for GCP_PROJECT=${GCP_PROJECT@Q}. Add deploy/terraform/*.tfvars with matching project_id, or set TF_VAR_FILE."
}

require_tf_var_file() {
  resolve_tf_var_file
  log "Terraform var-file: ${TF_VAR_FILE} (GCP_PROJECT=${GCP_PROJECT})"
}

usage() {
  sed -n '2,14p' "$0" | sed 's/^# \?//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --all) FORCE_ALL=true; DO_BACKEND=true; DO_FRONTEND=true; DO_TERRAFORM=true; DO_MIGRATE=true ;;
    --backend) DO_BACKEND=true; DO_TERRAFORM=true ;;
    --frontend) DO_FRONTEND=true; DO_TERRAFORM=true ;;
    --terraform) DO_TERRAFORM=true ;;
    --migrate) DO_MIGRATE=true ;;
    --build-only) SKIP_TERRAFORM=true ;;
    --skip-build) SKIP_BUILD=true ;;
    --plan-only) PLAN_ONLY=true ;;
    --no-auto-approve) AUTO_APPROVE=false ;;
    --ci)
      CI_MODE=true
      AUTO_APPROVE=true
      ;;
    --since)
      shift
      SINCE_REF="${1:?--since requires a git ref}"
      ;;
    *)
      die "unknown argument: $1 (try --help)"
      ;;
  esac
  shift
done

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"
}

require_cmd git
require_cmd gcloud
require_cmd terraform

if $CI_MODE; then
  [[ "${CI:-}" == "true" ]] || die "--ci requires CI=true in the environment"
  case "$STATE_FILE" in
    "$REPO_ROOT"/*) ;;
    *) die "--ci refuses to write deploy state outside repo: ${STATE_FILE@Q}" ;;
  esac
fi

cd "$REPO_ROOT"

# --- config consistency check -----------------------------------------------
# Runs before any Cloud Build or Terraform work so a stale mapping can't reach
# prod. Uses the backend venv (always present after `make install`) so pyyaml
# is guaranteed; falls back to system Python with a clear error if the venv is
# absent (e.g. a fresh CI runner without backend setup).

_validate_config() {
  local py=""
  if [[ -x "backend/.venv/bin/python" ]]; then
    py="backend/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1 && python3 -c "import yaml" 2>/dev/null; then
    py="python3"
  else
    warn "Skipping config validation — backend/.venv not found and pyyaml not in system Python."
    warn "Run 'make install' then retry, or 'pip install pyyaml' to enable this check."
    return 0
  fi
  log "Validating config consistency (ownership.yaml ↔ exec-pillars.ts ↔ component-map.ts)"
  "$py" scripts/validate_config.py || die "Config validation failed — fix mismatches before deploying"
}

_validate_config

# --- change detection ---------------------------------------------------------

resolve_since_ref() {
  if git rev-parse --verify "$SINCE_REF" >/dev/null 2>&1; then
    echo "$SINCE_REF"
    return
  fi
  warn "ref ${SINCE_REF} not found; falling back to HEAD~1"
  git rev-parse HEAD~1
}

changed_files_since() {
  local ref="$1"
  git diff --name-only "$ref" 2>/dev/null || true
}

any_path_changed() {
  local ref="$1"
  shift
  local patterns=("$@")
  local f
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    for pat in "${patterns[@]}"; do
      case "$f" in
        $pat) return 0 ;;
      esac
    done
  done < <(changed_files_since "$ref")
  return 1
}

REF="$(resolve_since_ref)"

BACKEND_PATTERNS=(
  'backend/*'
  'backend/Dockerfile'
  'cloudbuild.backend.yaml'
  'cloudbuild.yaml'
  'scripts/deploy-cloud.sh'
)
FRONTEND_PATTERNS=(
  'frontend/*'
  'frontend/Dockerfile'
  'cloudbuild.frontend.yaml'
  'cloudbuild.yaml'
)
TERRAFORM_PATTERNS=(
  'deploy/terraform/*'
  'config/*'
)
MIGRATION_PATTERNS=(
  'backend/migrations/*'
  'backend/alembic.ini'
)

if $FORCE_ALL; then
  DO_BACKEND=true
  DO_FRONTEND=true
  DO_TERRAFORM=true
elif ! $DO_BACKEND && ! $DO_FRONTEND && ! $DO_TERRAFORM; then
  any_path_changed "$REF" "${BACKEND_PATTERNS[@]}" && DO_BACKEND=true
  any_path_changed "$REF" "${FRONTEND_PATTERNS[@]}" && DO_FRONTEND=true
  any_path_changed "$REF" "${TERRAFORM_PATTERNS[@]}" && DO_TERRAFORM=true
  any_path_changed "$REF" "${MIGRATION_PATTERNS[@]}" && DO_MIGRATE=true
  # Image roll requires terraform even if only Docker context changed.
  $DO_BACKEND && DO_TERRAFORM=true
  $DO_FRONTEND && DO_TERRAFORM=true
fi

if ! $DO_BACKEND && ! $DO_FRONTEND && ! $DO_TERRAFORM && ! $DO_MIGRATE; then
  log "No changes detected since ${REF} — nothing to deploy."
  log "Use --all, --backend, --frontend, or --terraform to force."
  exit 0
fi

log "Deploy plan (since ${REF}):"
$DO_BACKEND && log "  • Cloud Build: backend"
$DO_FRONTEND && log "  • Cloud Build: frontend"
$DO_TERRAFORM && log "  • Terraform apply"
$DO_MIGRATE && log "  • Cloud Run job: secdb-migrate"
$SKIP_BUILD && warn "  • --skip-build: skipping Cloud Build"
$SKIP_TERRAFORM && warn "  • --skip-build/--build-only: skipping Terraform"

# --- Cloud Build --------------------------------------------------------------

BACKEND_BUILD_ID=""
FRONTEND_BUILD_ID=""

submit_build() {
  local config="$1"
  local label="$2"
  log "Cloud Build (${label}): ${config} [submitting async]"
  local id
  # --async returns the build id immediately; logs are streamed separately so
  # backend and frontend builds can run in parallel on Cloud Build servers.
  id="$(
    gcloud builds submit \
      --async \
      --config "$config" \
      --project "$GCP_PROJECT" \
      --format='value(id)' \
      "$REPO_ROOT"
  )"
  id="${id//$'\n'/}"
  id="${id//$'\r'/}"
  [[ -n "$id" ]] || die "Cloud Build did not return a build id for ${label}"
  validate_build_id "$id" "$label"
  log "  build id: ${id}"
  log "  logs: https://console.cloud.google.com/cloud-build/builds/${id}?project=$(gcloud config get-value project 2>/dev/null || echo "$GCP_PROJECT")"
  REPLY="$id"
}

wait_for_build() {
  local id="$1"
  local label="$2"
  local status=""
  local last_logged=""
  log "Cloud Build (${label}): waiting for ${id}"
  while true; do
    status="$(gcloud builds describe "$id" --project "$GCP_PROJECT" --format='value(status)' 2>/dev/null || true)"
    case "$status" in
      SUCCESS)
        log "Cloud Build (${label}): SUCCESS"
        return 0
        ;;
      FAILURE|INTERNAL_ERROR|TIMEOUT|CANCELLED|EXPIRED)
        die "Cloud Build ${label} (${id}) ended with ${status} — see Cloud Console logs"
        ;;
      QUEUED|PENDING|WORKING|"")
        if [[ "$status" != "$last_logged" ]]; then
          log "Cloud Build (${label}): ${status:-unknown}"
          last_logged="$status"
        fi
        sleep 5
        ;;
      *)
        warn "Cloud Build (${label}): unexpected status ${status@Q}; polling again"
        sleep 5
        ;;
    esac
  done
}

if ! $SKIP_BUILD; then
  if $DO_BACKEND; then
    submit_build cloudbuild.backend.yaml backend
    BACKEND_BUILD_ID="$REPLY"
  fi
  if $DO_FRONTEND; then
    submit_build cloudbuild.frontend.yaml frontend
    FRONTEND_BUILD_ID="$REPLY"
  fi

  # Stream logs for both builds in parallel so total wait = max(backend, frontend)
  # rather than backend + frontend.
  _WAIT_PIDS=()
  if [[ -n "$BACKEND_BUILD_ID" ]]; then
    wait_for_build "$BACKEND_BUILD_ID" backend &
    _WAIT_PIDS+=($!)
  fi
  if [[ -n "$FRONTEND_BUILD_ID" ]]; then
    wait_for_build "$FRONTEND_BUILD_ID" frontend &
    _WAIT_PIDS+=($!)
  fi
  _FAIL=0
  for _pid in ${_WAIT_PIDS[@]+"${_WAIT_PIDS[@]}"}; do
    wait "$_pid" || _FAIL=1
  done
  [[ $_FAIL -eq 0 ]] || die "One or more Cloud Build jobs failed"
else
  warn "Skipping Cloud Build (--skip-build)"
fi

# --- Terraform ------------------------------------------------------------------

TF_VARS=()

if [[ -n "$BACKEND_BUILD_ID" ]]; then
  TF_VARS+=(-var="image_tag_backend=${BACKEND_BUILD_ID}")
fi
if [[ -n "$FRONTEND_BUILD_ID" ]]; then
  TF_VARS+=(-var="image_tag_frontend=${FRONTEND_BUILD_ID}")
fi

apply_terraform() {
  require_tf_var_file

  cd "$TF_DIR"
  log "Terraform init (${TF_DIR}, bucket=${TF_BACKEND_BUCKET})"
  terraform init -input=false \
    -backend-config="bucket=${TF_BACKEND_BUCKET}" \
    -backend-config="prefix=secdb"

  local plan_file="secdb.tfplan"
  local plan_args=(-var-file="$TF_VAR_FILE")
  if [[ ${#TF_VARS[@]} -gt 0 ]]; then
    plan_args+=("${TF_VARS[@]}")
  fi

  log "Terraform plan"
  terraform plan -out="$plan_file" ${plan_args[@]+"${plan_args[@]}"}

  if $PLAN_ONLY; then
    log "Plan saved to ${TF_DIR}/${plan_file} (--plan-only, not applying)"
    return 0
  fi

  if $AUTO_APPROVE; then
    log "Terraform apply (auto-approve)"
    terraform apply -auto-approve "$plan_file"
  else
    log "Terraform apply (interactive)"
    terraform apply "$plan_file"
  fi
}

if $DO_TERRAFORM && ! $SKIP_TERRAFORM; then
  if [[ ${#TF_VARS[@]} -eq 0 ]]; then
    log "Terraform: infra/config only (no new image tags)"
  fi
  apply_terraform
elif $SKIP_TERRAFORM; then
  warn "Skipping Terraform"
elif ! $DO_TERRAFORM; then
  :
else
  die "internal: unreachable terraform branch"
fi

# --- Migrate --------------------------------------------------------------------

if $DO_MIGRATE; then
  log "Running secdb-migrate (schema upgrade)"
  gcloud run jobs execute secdb-migrate \
    --region "$GCP_REGION" \
    --project "$GCP_PROJECT" \
    --wait
fi

# --- Record state -------------------------------------------------------------

GIT_SHA="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
DEPLOYED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

if [[ -n "$BACKEND_BUILD_ID" || -n "$FRONTEND_BUILD_ID" ]]; then
  # Merge with previous tags so we keep the last known pin for sides we did not rebuild.
  prev_backend=""
  prev_frontend=""
  if [[ -f "$STATE_FILE" ]]; then
    prev_backend="$(python3 -c "import json; print(json.load(open('${STATE_FILE}')).get('backend_tag',''))" 2>/dev/null || true)"
    prev_frontend="$(python3 -c "import json; print(json.load(open('${STATE_FILE}')).get('frontend_tag',''))" 2>/dev/null || true)"
  fi
  cat >"$STATE_FILE" <<EOF
{
  "deployed_at": "${DEPLOYED_AT}",
  "git_sha": "${GIT_SHA}",
  "since_ref": "${REF}",
  "backend_tag": "${BACKEND_BUILD_ID:-$prev_backend}",
  "frontend_tag": "${FRONTEND_BUILD_ID:-$prev_frontend}",
  "gcp_project": "${GCP_PROJECT}",
  "gcp_region": "${GCP_REGION}",
  "tf_var_file": "${TF_VAR_FILE:-}"
}
EOF
  log "Wrote ${STATE_FILE}"
fi

log "Done."
[[ -n "$BACKEND_BUILD_ID" ]] && log "  backend image:  ${BACKEND_BUILD_ID}" || true
[[ -n "$FRONTEND_BUILD_ID" ]] && log "  frontend image: ${FRONTEND_BUILD_ID}" || true
