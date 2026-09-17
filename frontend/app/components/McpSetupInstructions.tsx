"use client";

import { useCallback, useState } from "react";

type Tab = "claude-code" | "claude-desktop" | "cursor";

const EXAMPLE_PROMPTS = [
  "List my open critical findings",
  "Show open critical and high findings for team orders",
  "What scanners are dark or stale right now?",
  "Show SLA breaches for my teams, grouped by owner team",
  "Give me a metrics summary with a 14-day trend for team data-engineering",
  "List open Dependabot findings on repo orders-api",
  "How many open criticals do we have org-wide?",
];

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [text]);

  return (
    <button
      type="button"
      onClick={copy}
      className="rounded border border-neutral-600 bg-neutral-800 px-2 py-1 text-xs text-neutral-200 hover:bg-neutral-700"
    >
      {copied ? "Copied" : label ?? "Copy"}
    </button>
  );
}

function SnippetBlock({ snippet }: { snippet: string }) {
  return (
    <div className="relative">
      <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg border border-neutral-700 bg-neutral-950 p-4 pr-20 text-xs text-neutral-200">
        {snippet}
      </pre>
      <div className="absolute right-2 top-2">
        <CopyButton text={snippet} />
      </div>
    </div>
  );
}

const TOKEN_PLACEHOLDER = "<YOUR_TOKEN>";

function claudeCodeSnippet(mcpUrl: string, token: string): string {
  return `claude mcp add unified-security-dashboard \\
  --transport http ${mcpUrl} \\
  -H "Authorization: Bearer ${token}"`;
}

function claudeDesktopConfig(mcpUrl: string, token: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        "unified-security-dashboard": {
          url: mcpUrl,
          headers: {
            Authorization: `Bearer ${token}`,
          },
        },
      },
    },
    null,
    2,
  );
}

function cursorConfig(mcpUrl: string, token: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        "unified-security-dashboard": {
          url: mcpUrl,
          headers: {
            Authorization: `Bearer ${token}`,
          },
        },
      },
    },
    null,
    2,
  );
}

export default function McpSetupInstructions({
  token,
  mcpUrl,
}: {
  token?: string | null;
  mcpUrl: string;
}) {
  const [tab, setTab] = useState<Tab>("claude-code");

  const tabs: { id: Tab; label: string }[] = [
    { id: "claude-code", label: "Claude Code" },
    { id: "claude-desktop", label: "Claude Desktop" },
    { id: "cursor", label: "Cursor" },
  ];

  const effectiveToken = token ?? TOKEN_PLACEHOLDER;
  const isPlaceholder = !token;

  const snippet =
    tab === "claude-code"
      ? claudeCodeSnippet(mcpUrl, effectiveToken)
      : tab === "claude-desktop"
        ? claudeDesktopConfig(mcpUrl, effectiveToken)
        : cursorConfig(mcpUrl, effectiveToken);

  return (
    <div className="space-y-6">
      {isPlaceholder && (
        <p className="rounded-lg border border-neutral-700 bg-neutral-900/60 px-3 py-2 text-xs text-neutral-400">
          Snippets show <code className="text-neutral-200">{TOKEN_PLACEHOLDER}</code> as a
          placeholder. Generate a token above and replace it in your config.
        </p>
      )}
      <div>
        <div className="flex gap-2 border-b border-neutral-800 pb-2">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`rounded px-3 py-1 text-sm ${
                tab === t.id
                  ? "bg-neutral-700 text-neutral-100"
                  : "text-neutral-400 hover:text-neutral-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="mt-4">
          {tab === "claude-code" && (
            <p className="mb-3 text-sm text-neutral-400">
              Run from your project directory. Verify with{" "}
              <code className="text-neutral-300">claude mcp list</code> — expect{" "}
              <code className="text-neutral-300">
                unified-security-dashboard: ✓ Connected
              </code>.
            </p>
          )}
          {tab === "claude-desktop" && (
            <p className="mb-3 text-sm text-neutral-400">
              Edit{" "}
              <code className="text-neutral-300">
                ~/Library/Application Support/Claude/claude_desktop_config.json
              </code>{" "}
              and restart Claude Desktop or Cowork.
            </p>
          )}
          {tab === "cursor" && (
            <p className="mb-3 text-sm text-neutral-400">
              Create <code className="text-neutral-300">.cursor/mcp.json</code> in
              your repo, then reload the window.
            </p>
          )}
          <SnippetBlock snippet={snippet} />
        </div>
      </div>

      <details className="rounded-lg border border-neutral-800 bg-neutral-900/40 p-4">
        <summary className="cursor-pointer text-sm font-medium text-neutral-200">
          Example prompts
        </summary>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm text-neutral-400">
          {EXAMPLE_PROMPTS.map((p) => (
            <li key={p}>
              <span className="text-neutral-300">&quot;{p}&quot;</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
