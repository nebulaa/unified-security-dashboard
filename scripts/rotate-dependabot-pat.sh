#!/usr/bin/env bash
# Validate a GitHub Dependabot PAT and store it in Secret Manager +.env.local.
#
# GitHub does not allow API-based PAT creation — create the token in the UI first, then run
# this script. Required scopes (classic PAT): read:org, security_events.
#
# Usage:
#   ./scripts/rotate-dependabot-pat.sh
#   DEPENDABOT_PAT=ghp_... ./scripts/rotate-dependabot-pat.sh
#   DEPENDABOT_PAT=ghp_... ./scripts/rotate-dependabot-pat.sh --gsm-only
#   DEPENDABOT_PAT=ghp_... ./scripts/rotate-dependabot-pat.sh --local-only
#   ./scripts/rotate-dependabot-pat.sh --dry-run
#   ./scripts/rotate-dependabot-pat.sh --check-only   # print scopes + org access, no writes
#
# Environment:
#   DEPENDABOT_PAT   Token value (prompted securely if unset)
#   GITHUB_ORG       Org slug (default: from .env.local, else ExampleOrg)
#   GCP_PROJECT      GCP project for GSM (required)
#
# Requires: curl, gcloud (for GSM upload), python3 (for .env.local edit)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SECRET_ID="secdb-dependabot-pat"
GCP_PROJECT="${GCP_PROJECT:?Set GCP_PROJECT to the GCP project that holds secdb-dependabot-pat}"
GITHUB_API="https://api.github.com"

DO_GSM=true
DO_LOCAL=true
DRY_RUN=false
CHECK_ONLY=false

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help) usage 0 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --check-only) CHECK_ONLY=true; DO_GSM=false; DO_LOCAL=false; shift ;;
    --gsm-only) DO_LOCAL=false; shift ;;
    --local-only) DO_GSM=false; shift ;;
    *) echo "Unknown option: $1" >&2; usage 1 ;;
  esac
done

_load_github_org() {
  if [[ -n "${GITHUB_ORG:-}" ]]; then
    return
  fi
  local env_file="${ROOT}/.env.local"
  if [[ -f "$env_file" ]]; then
    GITHUB_ORG="$(
      grep -E '^GITHUB_ORG=' "$env_file" | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'"
    )"
  fi
  GITHUB_ORG="${GITHUB_ORG:-ExampleOrg}"
}

_print_scope_requirements() {
  cat <<'EOF'
Required for GET /orgs/{org}/dependabot/alerts (this poller):

  Classic PAT scopes:
    - security_events     REQUIRED (read/write security events / Dependabot alerts)
    - read:org optional (; not listed in GitHub docs for this endpoint)
    - repo / public_repo  NOT sufficient for org-wide private-repo alerts

  Fine-grained PAT:
    - Resource owner: target organization (e.g. ExampleOrg)
    - Repository access: All repositories (or every repo you need alerts from)
    - Organization permissions → Dependabot alerts: Read

  Account role (not a token scope):
    - Organization Owner OR Security manager on the org

  Other common 403 causes:
    - SAML SSO: authorize the PAT for the org (GitHub → org → SSO → Authorize)
    - Dependabot alerts disabled for the org
EOF
}

_check_classic_scopes() {
  local headers
  headers="$(mktemp)"
  trap 'rm -f "$headers"' RETURN

  curl -sS -D "$headers" -o /dev/null \
    -H "Authorization: token ${DEPENDABOT_PAT}" \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "https://api.github.com/user" || true

  local status scopes
  status="$(grep -i '^HTTP/' "$headers" | tail -1 | awk '{print $2}')"
  scopes="$(grep -i '^x-oauth-scopes:' "$headers" | tail -1 | cut -d: -f2- | sed 's/^ //' || true)"

  echo "==> Token type: classic (ghp_*)"
  echo "    GET /user → HTTP ${status:-unknown}"
  if [[ -n "$scopes" ]]; then
    echo "    X-OAuth-Scopes: ${scopes}"
    if [[ "$scopes" != *security_events* ]]; then
      echo "    MISSING required scope: security_events" >&2
    else
      echo "    security_events: present"
    fi
  elif [[ "$status" == "200" ]]; then
    echo "    (no X-OAuth-Scopes header — token may be fine-grained; use github_pat_* checklist above)"
  fi
}

_validate_pat() {
  local url="${GITHUB_API}/orgs/${GITHUB_ORG}/dependabot/alerts?state=open&per_page=1"
  local body http_code headers

  if [[ "$DEPENDABOT_PAT" == github_pat_* ]]; then
    echo "==> Token type: fine-grained (github_pat_*)"
    echo "    Verify org permissions: Dependabot alerts = Read, resource owner = ${GITHUB_ORG}"
  else
    _check_classic_scopes
  fi

  body="$(mktemp)"
  headers="$(mktemp)"
  trap 'rm -f "$body" "$headers"' RETURN

  http_code="$(
    curl -sS -D "$headers" -o "$body" -w '%{http_code}' \
      -H "Authorization: token ${DEPENDABOT_PAT}" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      -H "User-Agent: secdb-rotate-dependabot-pat/1.0" \
      "$url"
  )"

  local sso
  sso="$(grep -i '^x-github-sso:' "$headers" | tail -1 | cut -d: -f2- | sed 's/^ //' || true)"

  case "$http_code" in
    200)
      echo "==> GitHub OK: GET /orgs/${GITHUB_ORG}/dependabot/alerts (HTTP 200)"
      ;;
    401)
      echo "ERROR: GitHub returned 401 — PAT is invalid, expired, or revoked" >&2
      _print_scope_requirements >&2
      exit 1
      ;;
    403)
      echo "ERROR: GitHub returned 403 for org ${GITHUB_ORG}" >&2
      if [[ -n "$sso" ]]; then
        echo "    X-GitHub-SSO: ${sso}" >&2
        echo "    → Authorize this token for the org (SAML SSO)" >&2
      fi
      if grep -q '"message"' "$body" 2>/dev/null; then
        echo "    Response:" >&2
        sed -n '1,5p' "$body" >&2
      fi
      _print_scope_requirements >&2
      exit 1
      ;;
    *)
      echo "ERROR: GitHub returned HTTP ${http_code} for org ${GITHUB_ORG}" >&2
      sed -n '1,5p' "$body" >&2 || true
      exit 1
      ;;
  esac
}

_update_gsm() {
  echo "==> Secret Manager: ${SECRET_ID} (project ${GCP_PROJECT})"
  if $DRY_RUN; then
    echo "    (dry-run) would run: gcloud secrets versions add ${SECRET_ID} --data-file=-"
    return
  fi
  printf '%s' "$DEPENDABOT_PAT" | gcloud secrets versions add "$SECRET_ID" \
    --data-file=- \
    --project="$GCP_PROJECT"
  echo "    New version added."
}

_update_env_local() {
  local env_file="${ROOT}/.env.local"
  echo "==> Local: ${env_file}"
  if [[ ! -f "$env_file" ]]; then
    echo "    Skip — file missing (copy from .env.local.example)"
    return
  fi
  if $DRY_RUN; then
    echo "    (dry-run) would set DEPENDABOT_PAT=***"
    return
  fi
  python3 - "$env_file" "$DEPENDABOT_PAT" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
pat = sys.argv[2]
text = path.read_text()
lines = text.splitlines(keepends=True)
found = False
out: list[str] = []
for line in lines:
    if line.startswith("DEPENDABOT_PAT="):
        out.append(f"DEPENDABOT_PAT={pat}\n")
        found = True
    else:
        out.append(line if line.endswith("\n") else line + "\n")
if not found:
    if out and not out[-1].endswith("\n"):
        out[-1] = out[-1].rstrip("\n") + "\n"
    out.append(f"DEPENDABOT_PAT={pat}\n")
path.write_text("".join(out))
PY
  echo "    DEPENDABOT_PAT updated."
}

# --- main ---

if [[ -z "${DEPENDABOT_PAT:-}" ]]; then
  read -r -s -p "Paste GitHub PAT (ghp_...): " DEPENDABOT_PAT
  echo
fi
if [[ -z "${DEPENDABOT_PAT}" ]]; then
  echo "ERROR: DEPENDABOT_PAT is empty" >&2
  exit 1
fi
if [[ "$DEPENDABOT_PAT" != ghp_* && "$DEPENDABOT_PAT" != github_pat_* ]]; then
  echo "WARN: token does not look like a classic (ghp_) or fine-grained (github_pat_) PAT" >&2
fi

_load_github_org
echo "==> Org: ${GITHUB_ORG}"

_validate_pat

if $CHECK_ONLY; then
  echo "==> Check passed."
  exit 0
fi

if $DO_GSM; then
  _update_gsm
else
  echo "==> Skip Secret Manager (--local-only)"
fi

if $DO_LOCAL; then
  _update_env_local
else
  echo "==> Skip .env.local (--gsm-only)"
fi

if $DRY_RUN; then
  echo "==> Dry run complete (no secrets written)."
else
  echo "==> Done. Test locally: make poller-dependabot"
  if $DO_GSM; then
    echo "    Cloud: gcloud run jobs execute secdb-poller-dependabot --region=europe-west1 --project=${GCP_PROJECT} --wait"
  fi
fi
