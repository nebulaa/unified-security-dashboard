#!/usr/bin/env bash
# Run local dev with admin or member (regular user) identity.
#
# Admin vs member is decided by whether DEV_IDENTITY_EMAIL appears in
# config/rbac.yaml admin_emails. This script
# only overrides the email the Next.js dev server stamps on X-Dev-Identity;
# the API reads rbac.yaml from CONFIG_STORE_FS_ROOT (./config locally).
#
# Usage:
#   ./scripts/dev-as.sh member              # Next.js on :3000 as member
#   ./scripts/dev-as.sh admin frontend      # same, explicit target
#   ./scripts/dev-as.sh member print-env    # print exports for another shell
#   ./scripts/dev-as.sh admin api             # uvicorn :8000 (identity unused)
#
# Env overrides (optional):
#   SECDB_DEV_ADMIN_EMAIL   admin identity (default: first admin_emails in rbac.yaml)
#   SECDB_DEV_MEMBER_EMAIL  member identity (default: developer@example.com)
#   SECDB_DEV_GROUPS        google.groups list (default: security@example.com)
#
# Typical loop — four terminals:
#   make postgres-up && make api-dev
#   make normalizer-dev
#   ./scripts/dev-as.sh member frontend
#   # compare: ./scripts/dev-as.sh admin frontend  (restart frontend between modes)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

RBAC="${ROOT}/config/rbac.yaml"
PY="${ROOT}/backend/.venv/bin/python"
DEFAULT_MEMBER_EMAIL="${SECDB_DEV_MEMBER_EMAIL:-developer@example.com}"
DEFAULT_GROUPS="${SECDB_DEV_GROUPS:-security@example.com}"

usage() {
  sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'
  echo ""
  echo "Targets: frontend (default) | api | normalizer | print-env"
}

die() {
  echo "dev-as.sh: $*" >&2
  exit 1
}

load_dotenv() {
  set -a
  [[ -f .env.local ]] && . ./.env.local
  [[ -f .env ]] && . ./.env
  set +a
}

email_is_admin() {
  local email="$1"
  [[ -f "${RBAC}" ]] || return 1
  "${PY}" - "${email}" "${RBAC}" <<'PY' 2>/dev/null || return 1
import sys
import yaml
email, path = sys.argv[1], sys.argv[2]
data = yaml.safe_load(open(path)) or {}
admins = {e.strip().lower() for e in (data.get("admin_emails") or [])}
sys.exit(0 if email.strip().lower() in admins else 1)
PY
}

first_admin_email() {
  [[ -f "${RBAC}" ]] || return 1
  "${PY}" - "${RBAC}" <<'PY'
import sys, yaml
data = yaml.safe_load(open(sys.argv[1])) or {}
admins = data.get("admin_emails") or []
print(admins[0] if admins else "", end="")
PY
}

resolve_admin_email() {
  if [[ -n "${SECDB_DEV_ADMIN_EMAIL:-}" ]]; then
    echo "${SECDB_DEV_ADMIN_EMAIL}"
    return
  fi
  if [[ -n "${DEV_IDENTITY_EMAIL:-}" ]] && email_is_admin "${DEV_IDENTITY_EMAIL}"; then
    echo "${DEV_IDENTITY_EMAIL}"
    return
  fi
  local from_rbac
  from_rbac="$(first_admin_email || true)"
  [[ -n "${from_rbac}" ]] && echo "${from_rbac}" && return
  echo "${DEV_IDENTITY_EMAIL:-dev1@your-org.com}"
}

resolve_member_email() {
  local email="${SECDB_DEV_MEMBER_EMAIL:-${DEFAULT_MEMBER_EMAIL}}"
  if email_is_admin "${email}"; then
    die "${email} is listed in config/rbac.yaml admin_emails — pick SECDB_DEV_MEMBER_EMAIL to an email not in that list"
  fi
  echo "${email}"
}

apply_identity() {
  local mode="$1"
  case "${mode}" in
    admin)
      DEV_IDENTITY_EMAIL="$(resolve_admin_email)"
      ;;
    member | user)
      DEV_IDENTITY_EMAIL="$(resolve_member_email)"
      ;;
    *)
      die "unknown mode '${mode}' (use admin or member)"
      ;;
  esac
  export DEV_IDENTITY_EMAIL
  export DEV_IDENTITY_GROUPS="${DEFAULT_GROUPS}"
}

print_banner() {
  local mode="$1" is_admin="no"
  email_is_admin "${DEV_IDENTITY_EMAIL}" && is_admin="yes"
  echo "==> secdb dev identity: ${mode}"
  echo "    DEV_IDENTITY_EMAIL=${DEV_IDENTITY_EMAIL}"
  echo "    DEV_IDENTITY_GROUPS=${DEV_IDENTITY_GROUPS}"
  echo "    rbac is_admin=${is_admin} (config/rbac.yaml)"
  echo ""
}

run_target() {
  local target="$1"
  case "${target}" in
    print-env)
      echo "export DEV_IDENTITY_EMAIL='${DEV_IDENTITY_EMAIL}'"
      echo "export DEV_IDENTITY_GROUPS='${DEV_IDENTITY_GROUPS}'"
      ;;
    frontend)
      cd frontend && npm run dev
      ;;
    api)
      cd backend && ../"${PY}" -m uvicorn app.api.main:app --reload --port 8000
      ;;
    normalizer)
      cd backend && ../"${PY}" -m uvicorn app.normalizer.main:app --reload --port 8001
      ;;
    *)
      die "unknown target '${target}' (frontend | api | normalizer | print-env)"
      ;;
  esac
}

main() {
  local mode="${1:-}"
  local target="${2:-frontend}"

  [[ -n "${mode}" ]] || { usage; exit 1; }
  [[ "${mode}" == "-h" || "${mode}" == "--help" ]] && { usage; exit 0; }

  [[ -x "${PY}" ]] || die "backend venv missing — run: make install"

  load_dotenv
  apply_identity "${mode}"
  print_banner "${mode}"
  run_target "${target}"
}

main "$@"
