"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

type FeedEvent = {
  ts: number;
  kind: string;
  data?: any;
};

type Props = {
  heroId: string;
  events: FeedEvent[];
  status: string;
  parseFailureCount: number;
};

export default function ActivityFeed({ heroId, events, status, parseFailureCount }: Props) {
  const feedRef = useRef<HTMLOListElement | null>(null);

  useEffect(() => {
    const el = feedRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [events.length]);

  return (
    <section className="border-l border-border pl-6 min-h-[60vh]">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm uppercase tracking-wider text-fg-muted">recent activity</h2>
        <div className="flex items-center gap-3">
          {parseFailureCount > 0 && (
            <span
              className="text-xs text-rose-400 font-mono"
              title="LLM output that didn't parse cleanly. Click an entry below for the raw output."
            >
              ⚠ {parseFailureCount} parse {parseFailureCount === 1 ? "failure" : "failures"}
            </span>
          )}
          <span
            className={`text-xs ${
              status === "open"
                ? "text-emerald-400"
                : status === "connecting"
                  ? "text-amber"
                  : "text-rose-400"
            }`}
          >
            ● {status}
          </span>
        </div>
      </div>
      {events.length === 0 ? (
        <p className="text-sm text-fg-muted italic">
          Idle. Activity will appear here as the hero acts.
        </p>
      ) : (
        <ol ref={feedRef} className="space-y-2 max-h-[75vh] overflow-y-auto pr-2">
          {events.map((e, i) => {
            const debug = e.data?.payload?.debug;
            const isParseFailure = e.kind === "tick" && e.data?.kind === "parse_failure";
            return (
              <li
                key={`${e.ts}-${i}`}
                className={`text-sm leading-relaxed ${
                  isParseFailure ? "border-l-2 border-rose-500 pl-2 -ml-2" : ""
                }`}
              >
                <span className="text-xs text-amber-dim mr-2 font-mono">
                  t{e.data?.tick_id}
                </span>
                {e.kind === "narrator" ? (
                  <span>{e.data?.text}</span>
                ) : isParseFailure ? (
                  <span>
                    <span className="text-rose-400 font-medium">parse failure</span>
                    <span className="text-fg-muted"> · {e.data?.payload?.reason ?? "unknown"}</span>
                    {e.data?.payload?.error && (
                      <span className="text-fg-muted"> · {String(e.data.payload.error)}</span>
                    )}
                    {e.data?.payload?.raw_output && (
                      <details className="mt-1 ml-6 text-xs font-mono text-rose-300/70">
                        <summary className="cursor-pointer text-rose-400/80 hover:text-rose-300">
                          raw output
                        </summary>
                        <pre className="mt-1 whitespace-pre-wrap break-all">
                          {String(e.data.payload.raw_output).slice(0, 500)}
                        </pre>
                      </details>
                    )}
                  </span>
                ) : (
                  <span className="text-fg-muted">
                    {e.data?.kind} ·{" "}
                    {JSON.stringify(e.data?.payload?.outcome ?? e.data?.payload).slice(0, 100)}
                  </span>
                )}
                {debug && !isParseFailure && (
                  <div className="mt-1 ml-6 text-xs font-mono text-amber-dim">
                    ↪ reflex #{debug.reflex_index}
                    {debug.when && (
                      <span className="text-fg-muted"> · when {String(debug.when)}</span>
                    )}
                    {debug.via === "invoke_llm" && (
                      <span className="text-amber"> · invoke_llm</span>
                    )}
                    {debug.via === "invoke_llm" && e.data?.tick_id && (
                      <Link
                        href={`/heroes/${heroId}/ticks/${e.data.tick_id}`}
                        className="ml-2 text-emerald-400 hover:text-emerald-300 underline decoration-dotted"
                      >
                        debug this choice →
                      </Link>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
