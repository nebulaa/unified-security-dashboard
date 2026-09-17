// Next.js route handler that proxies all browser API calls to FastAPI.
//
// Why a proxy?
//   - In dev, the browser must not see the identity payload. The Next.js
//     server reads dev identity from env vars and injects it on every
//     forwarded request.
//   - In prod, IAP authenticates the user at the LB and injects the
//     `X-Goog-Authenticated-User-Email` header into requests reaching this
//     proxy. We translate that into the `X-Dev-Identity` envelope and forward
//     it to the API at its *.run.app URL. The API runs with
//     IDENTITY_BACKEND=dev because Google's edge scrubs `X-Goog-*` headers
//     from non-IAP traffic, making direct JWT forwarding impossible. The API
//     ingress is `INTERNAL_LOAD_BALANCER` — only LB+VPC can reach it, and the
//     LB itself is IAP-protected, so this is safe in our network topology.
//
// No active-role plumbing — authorization on the API side is per-email
// (admin if listed in `config/rbac.yaml.admin_emails`, member otherwise).

import { NextRequest, NextResponse } from "next/server";
import { cloudRunAuthHeaders } from "../../../lib/api/cloud-run-auth";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

// Group list stamped onto IAP-authenticated requests for the dev-identity
// envelope. The backend doesn't consult groups today (admin is per-email);
// keeping the field populated lets a future tightening (require a group
// for read access) land as a one-liner in `config_store.py`.
const IAP_DEFAULT_GROUPS = (
  process.env.IAP_DEFAULT_GROUPS ?? "security@example.com"
)
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

function devIdentityFromIncoming(request: NextRequest): string {
  const iapEmail = request.headers.get("x-goog-authenticated-user-email");
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

type RouteCtx = { params: Promise<{ path: string[] }> };

async function forward(request: NextRequest, ctx: RouteCtx) {
  const { path } = await ctx.params;
  const upstreamPath = "/" + path.join("/");
  const search = request.nextUrl.search ?? "";
  const upstreamUrl = `${API_BASE}${upstreamPath}${search}`;

  const headers: Record<string, string> = {
    ...(await cloudRunAuthHeaders()),
    "X-Dev-Identity": devIdentityFromIncoming(request),
  };

  const ct = request.headers.get("content-type");
  if (ct) headers["Content-Type"] = ct;

  const upstream = await fetch(upstreamUrl, {
    method: request.method,
    headers,
    body:
      request.method === "GET" || request.method === "HEAD"
        ? undefined
        : await request.text(),
    cache: "no-store",
  });

  // 204/205 must have a null body in the Fetch Response API. NextResponse
  // rejects `new NextResponse(arrayBuffer, { status: 204 })` with
  // "Invalid response status code 204" — the API returns 204 for DELETE
  // /me/tokens/{id}, so the proxy must special-case these statuses.
  if (upstream.status === 204 || upstream.status === 205) {
    return new NextResponse(null, { status: upstream.status });
  }

  // Use arrayBuffer (not text) so binary responses like PDFs are forwarded
  // byte-for-byte; .text() decodes as UTF-8 and replaces invalid bytes with
  // U+FFFD, which silently corrupts PDF/XLSX downloads.
  const body = await upstream.arrayBuffer();
  const responseHeaders: Record<string, string> = {
    "Content-Type": upstream.headers.get("content-type") ?? "application/json",
  };
  const contentDisposition = upstream.headers.get("content-disposition");
  if (contentDisposition) responseHeaders["Content-Disposition"] = contentDisposition;
  const contentLength = upstream.headers.get("content-length");
  if (contentLength) responseHeaders["Content-Length"] = contentLength;

  return new NextResponse(body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export async function GET(request: NextRequest, ctx: RouteCtx) {
  return forward(request, ctx);
}
export async function POST(request: NextRequest, ctx: RouteCtx) {
  return forward(request, ctx);
}
export async function PUT(request: NextRequest, ctx: RouteCtx) {
  return forward(request, ctx);
}
export async function DELETE(request: NextRequest, ctx: RouteCtx) {
  return forward(request, ctx);
}
