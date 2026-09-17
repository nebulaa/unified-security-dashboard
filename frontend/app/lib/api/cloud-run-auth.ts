import "server-only";

import { GoogleAuth } from "google-auth-library";

const API_AUDIENCE = process.env.CLOUD_RUN_API_AUDIENCE;
const auth = new GoogleAuth();

export async function cloudRunAuthHeaders(): Promise<Record<string, string>> {
  if (!API_AUDIENCE) {
    return {};
  }

  const client = await auth.getIdTokenClient(API_AUDIENCE);
  const token = await client.idTokenProvider.fetchIdToken(API_AUDIENCE);
  return {
    "X-Serverless-Authorization": `Bearer ${token}`,
  };
}
