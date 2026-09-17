import { serverFetch } from "../../lib/api/server";
import type { Me } from "../../lib/types";
import McpTokensPanel from "./McpTokensPanel";

export default async function McpSettingsPage() {
  const me = await serverFetch<Me>("/me");
  return <McpTokensPanel me={me} />;
}
