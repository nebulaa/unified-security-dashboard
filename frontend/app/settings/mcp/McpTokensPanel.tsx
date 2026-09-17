"use client";

import { useCallback, useEffect, useState } from "react";
import McpSetupInstructions from "../../components/McpSetupInstructions";
import { clientFetch } from "../../lib/api/client";
import type {
  ApiTokenCreatedResponse,
  ApiTokenListResponse,
  Me,
  McpConfigResponse,
} from "../../lib/types";

type ExpiryChoice = "never" | "30" | "90" | "365" | "custom";

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  return new Date(iso).toLocaleString();
}

export default function McpTokensPanel({ me: _me }: { me: Me }) {
  const [tokens, setTokens] = useState<ApiTokenListResponse | null>(null);
  const [mcpUrl, setMcpUrl] = useState("http://localhost:3001/mcp");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [showForm, setShowForm] = useState(false);
  const [label, setLabel] = useState("");
  const [expiry, setExpiry] = useState<ExpiryChoice>("90");
  const [customDate, setCustomDate] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const [created, setCreated] = useState<ApiTokenCreatedResponse | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [list, config] = await Promise.all([
        clientFetch<ApiTokenListResponse>("/me/tokens"),
        clientFetch<McpConfigResponse>("/me/mcp-config"),
      ]);
      setTokens(list);
      setMcpUrl(config.mcp_server_url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load tokens");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Initial remote state is intentionally loaded after this client panel mounts.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const atMax = (tokens?.items.length ?? 0) >= (tokens?.max_active ?? 5);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        label: label.trim() || null,
      };
      if (expiry === "custom") {
        if (!customDate) {
          setError("Choose a custom expiry date");
          setSubmitting(false);
          return;
        }
        body.expires_at = new Date(customDate).toISOString();
      } else {
        body.expires_in_days = Number(expiry);
      }

      const res = await clientFetch<ApiTokenCreatedResponse>("/me/tokens", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setCreated(res);
      setShowForm(false);
      setLabel("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create token");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRevoke(id: string) {
    if (!confirm("Revoke this token? Connected agents will stop working immediately.")) {
      return;
    }
    setError(null);
    try {
      await clientFetch(`/me/tokens/${id}`, { method: "DELETE" });
      if (created?.id === id) setCreated(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to revoke token");
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-8 px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold text-neutral-100">Connect via MCP</h1>
        <p className="mt-2 text-sm text-neutral-400">
          Generate a personal token to query your security findings from Claude Code,
          Claude Desktop, Claude Cowork, or Cursor. The token inherits your
          dashboard access — same data you see in the browser.
        </p>
      </header>

      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-300">
          {error}
        </div>
      )}

      {created && (
        <section className="space-y-4 rounded-lg border border-amber-700/50 bg-amber-950/20 p-6">
          <p className="text-sm font-medium text-amber-200">
            Save this token now — you won&apos;t see it again.
          </p>
          <div className="flex items-center gap-3">
            <code className="flex-1 break-all rounded bg-neutral-950 px-3 py-2 font-mono text-sm text-emerald-300">
              {created.token}
            </code>
            <button
              type="button"
              onClick={() => navigator.clipboard.writeText(created.token)}
              className="shrink-0 rounded bg-neutral-700 px-3 py-2 text-sm text-neutral-100 hover:bg-neutral-600"
            >
              Copy
            </button>
          </div>
          <p className="text-xs text-amber-200/80">
            The setup instructions below are pre-filled with this token.
          </p>
        </section>
      )}

      <section className="rounded-lg border border-neutral-800 bg-neutral-900/30 p-6">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-lg font-medium text-neutral-100">Your tokens</h2>
          <button
            type="button"
            disabled={atMax || showForm}
            title={atMax ? "Max 5 active tokens — revoke one first" : undefined}
            onClick={() => setShowForm(true)}
            className="rounded bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Generate new token
          </button>
        </div>

        {showForm && (
          <form onSubmit={handleCreate} className="mt-6 space-y-4 border-t border-neutral-800 pt-6">
            <div>
              <label className="block text-xs text-neutral-400">Label (optional)</label>
              <input
                type="text"
                maxLength={64}
                placeholder="MacBook Claude Code"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                className="mt-1 w-full rounded border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100"
              />
            </div>
            <div>
              <label className="block text-xs text-neutral-400">Expiry</label>
              <select
                value={expiry}
                onChange={(e) => setExpiry(e.target.value as ExpiryChoice)}
                className="mt-1 w-full rounded border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100"
              >
                <option value="never">Never</option>
                <option value="30">30 days</option>
                <option value="90">90 days</option>
                <option value="365">1 year</option>
                <option value="custom">Custom date…</option>
              </select>
              {expiry === "custom" && (
                <input
                  type="datetime-local"
                  value={customDate}
                  onChange={(e) => setCustomDate(e.target.value)}
                  className="mt-2 w-full rounded border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-100"
                />
              )}
            </div>
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={submitting}
                className="rounded bg-emerald-700 px-4 py-2 text-sm text-white hover:bg-emerald-600 disabled:opacity-50"
              >
                {submitting ? "Generating…" : "Generate"}
              </button>
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="rounded border border-neutral-600 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-800"
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {loading ? (
          <p className="mt-6 text-sm text-neutral-500">Loading…</p>
        ) : tokens && tokens.items.length === 0 && !showForm ? (
          <p className="mt-6 text-sm text-neutral-500">
            No active tokens. Generate one to connect your AI assistant.
          </p>
        ) : (
          <div className="mt-6 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-neutral-800 text-xs uppercase text-neutral-500">
                  <th className="pb-2 pr-4">Label</th>
                  <th className="pb-2 pr-4">Prefix</th>
                  <th className="pb-2 pr-4">Created</th>
                  <th className="pb-2 pr-4">Expires</th>
                  <th className="pb-2 pr-4">Last used</th>
                  <th className="pb-2" />
                </tr>
              </thead>
              <tbody>
                {tokens?.items.map((t) => (
                  <tr key={t.id} className="border-b border-neutral-800/60 text-neutral-300">
                    <td className="py-3 pr-4">{t.label ?? "—"}</td>
                    <td className="py-3 pr-4 font-mono text-xs">{t.prefix}…</td>
                    <td className="py-3 pr-4">{formatDate(t.created_at)}</td>
                    <td className="py-3 pr-4">{formatDate(t.expires_at)}</td>
                    <td className="py-3 pr-4">{formatDate(t.last_used_at)}</td>
                    <td className="py-3">
                      <button
                        type="button"
                        onClick={() => void handleRevoke(t.id)}
                        className="text-red-400 hover:text-red-300"
                      >
                        Revoke
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {atMax && (
          <p className="mt-4 text-xs text-neutral-500">
            Maximum of {tokens?.max_active ?? 5} active tokens. Revoke an unused token to
            create a new one.
          </p>
        )}
      </section>

      <details
        key={created?.id ?? "no-token"}
        open={!!created}
        className="rounded-lg border border-neutral-800 bg-neutral-900/20 p-4"
      >
        <summary className="cursor-pointer text-sm font-medium text-neutral-200">
          Setup instructions for Claude Code, Desktop, and Cursor
        </summary>
        <div className="mt-4">
          <McpSetupInstructions token={created?.token ?? null} mcpUrl={mcpUrl} />
        </div>
      </details>
    </div>
  );
}
