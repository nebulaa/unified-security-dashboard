// Client-side fetch — always goes through the Next.js proxy at /api/proxy/<path>
// so the browser never holds an identity token. The proxy injects X-Dev-Identity
// (and in prod, IAP injects X-Goog-IAP-JWT-Assertion at the load balancer).

export async function clientFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/proxy${path}`, {
    ...init,
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(
      `clientFetch ${path} -> ${response.status}: ${await response.text()}`,
    );
  }
  // 204 No Content (e.g. DELETE /me/tokens/{id}) has an empty body, and
  // response.json() on an empty body throws SyntaxError. Callers that don't
  // expect a response body (T = void) cast away the undefined.
  if (response.status === 204 || response.headers.get("Content-Length") === "0") {
    return undefined as T;
  }
  return (await response.json()) as T;
}
