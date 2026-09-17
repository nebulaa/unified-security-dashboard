// Server-only API helper. Used by server components for first-paint data
// fetches (per design D26).
//
// 2026-05-19: prod calls the API at its *.run.app URL (direct, via VPC) and
// uses the `X-Dev-Identity` envelope. Reasons:
//   1. Google's edge scrubs `X-Goog-*` headers from non-IAP traffic, so we
//      cannot forward the user's IAP JWT directly.
//   2. The API's external LB IP isn't reachable from the same VPC (hairpin
//      restriction), so we can't route SSR through the LB either.
//   3. The API's Cloud Run ingress is `INTERNAL_LOAD_BALANCER` — only the LB
//      and same-project VPC traffic can reach it. The LB enforces IAP for the
//      browser path; the frontend SA is the only VPC caller. So we lift the
//      identity from the IAP-injected `X-Goog-Authenticated-User-Email` header
//      we received and forward it as the dev envelope.
//
// No `X-Active-Role` header — authorization on the API side is per-email
// (admin if listed in `config/rbac.yaml.admin_emails`, member otherwise).
import { headers } from "next/headers";
import { cloudRunAuthHeaders } from "./cloud-run-auth";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

// Group list stamped onto IAP-authenticated requests for the dev-identity
// envelope. The backend does not consult groups today; keeping the field
// populated lets a future tightening (require a specific group as an extra
// check) land as a one-liner. Override via the `IAP_DEFAULT_GROUPS` env var.
const IAP_DEFAULT_GROUPS = (
  process.env.IAP_DEFAULT_GROUPS ?? "security@example.com"
)
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

function devIdentityFromIncoming(incoming: Headers): string {
  const iapEmail = incoming.get("x-goog-authenticated-user-email");
  if (iapEmail) {
    const email = iapEmail.includes(":") ? iapEmail.split(":", 2)[1] : iapEmail;
    return JSON.stringify({ email, "google.groups": IAP_DEFAULT_GROUPS });
  }
  return JSON.stringify({
    email: process.env.DEV_IDENTITY_EMAIL ?? "developer@example.com",
    "google.groups": (process.env.DEV_IDENTITY_GROUPS ?? "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  });
}

export async function serverFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const incoming = await headers();

  const requestHeaders: Record<string, string> = {
    ...(await cloudRunAuthHeaders()),
    "X-Dev-Identity": devIdentityFromIncoming(incoming),
    ...((init.headers as Record<string, string>) ?? {}),
  };

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: requestHeaders,
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(
      `serverFetch ${path} -> ${response.status}: ${await response.text()}`,
    );
  }
  return (await response.json()) as T;
}
