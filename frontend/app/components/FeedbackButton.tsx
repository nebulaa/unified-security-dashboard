"use client";

import { useEffect, useRef, useState } from "react";

type FeedbackKind = "feedback" | "inaccuracy";

type Props = {
  email: string;
  name: string;
};

export default function FeedbackButton({ email, name }: Props) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<FeedbackKind>("feedback");
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  async function submit() {
    const trimmed = message.trim();
    if (!trimmed) return;
    setStatus("sending");
    setErrorMsg(null);
    const pageUrl =
      typeof window !== "undefined"
        ? `${window.location.pathname}${window.location.search}`
        : null;
    try {
      const res = await fetch("/api/proxy/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind,
          message: trimmed,
          page_url: pageUrl,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { detail?: string }).detail ?? `Request failed (${res.status})`,
        );
      }
      setStatus("sent");
      setMessage("");
      setTimeout(() => {
        setOpen(false);
        setStatus("idle");
      }, 1800);
    } catch (error) {
      setStatus("error");
      setErrorMsg(error instanceof Error ? error.message : "Failed to send feedback");
    }
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((value) => !value);
          setStatus("idle");
          setErrorMsg(null);
        }}
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Send feedback or report an inaccuracy"
        className="inline-flex h-7 items-center gap-1.5 rounded-md border border-neutral-700 bg-neutral-900 px-2.5 text-xs font-medium text-neutral-300 transition-colors hover:border-neutral-500 hover:text-neutral-100"
      >
        <span aria-hidden="true" className="text-sm leading-none">
          ✉
        </span>
        Feedback
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label="Send feedback"
          className="absolute right-0 top-full z-20 mt-2 w-80 rounded-lg border border-neutral-700 bg-neutral-950 p-4 shadow-xl"
        >
          <p className="text-sm font-medium text-neutral-100">Send feedback</p>
          <p className="mt-1 text-xs text-neutral-500">
            Routed to the team Slack channel as {name} ({email}).
          </p>

          <div className="mt-3 flex gap-2">
            {(
              [
                ["feedback", "General feedback"],
                ["inaccuracy", "Report inaccuracy"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setKind(value)}
                className={`rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                  kind === value
                    ? "border-sky-500/50 bg-sky-500/10 text-sky-300"
                    : "border-neutral-700 text-neutral-400 hover:border-neutral-500 hover:text-neutral-200"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            rows={4}
            maxLength={4000}
            placeholder={
              kind === "inaccuracy"
                ? "What looks wrong on this page?"
                : "Share feedback or suggestions…"
            }
            className="mt-3 w-full resize-y rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 placeholder:text-neutral-500 focus:border-neutral-500 focus:outline-none"
          />

          {errorMsg ? (
            <p className="mt-2 text-xs text-red-400">{errorMsg}</p>
          ) : null}
          {status === "sent" ? (
            <p className="mt-2 text-xs text-emerald-400">Thanks — your message was sent.</p>
          ) : null}

          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="rounded border border-neutral-700 px-3 py-1.5 text-xs text-neutral-400 hover:text-neutral-200"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!message.trim() || status === "sending"}
              onClick={submit}
              className="rounded border border-sky-600/50 bg-sky-600/20 px-3 py-1.5 text-xs font-medium text-sky-200 hover:bg-sky-600/30 disabled:opacity-50"
            >
              {status === "sending" ? "Sending…" : "Send"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
