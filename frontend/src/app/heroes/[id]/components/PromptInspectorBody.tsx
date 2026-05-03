"use client";

// Render-only body of the prompt inspector. Owns the copy-to-clipboard
// state but no fetching — its parent (PromptInspector) handles polling
// and the owner-only gate.

import Link from "next/link";
import { useState } from "react";
import type { LatestLlmCall } from "@/lib/api";
import BudgetBar from "./BudgetBar";

type Props = {
  heroId: string;
  data: LatestLlmCall;
};

export default function PromptInspectorBody({ heroId, data }: Props) {
  const [copied, setCopied] = useState(false);
  const used = (data.tokens_in ?? 0) + (data.tokens_out ?? 0);

  function copyPrompt() {
    if (!data.prompt_text) return;
    navigator.clipboard.writeText(data.prompt_text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div className="text-xs text-fg-muted">
          tick{" "}
          <Link
            href={`/heroes/${heroId}/ticks/${data.tick_id}`}
            className="text-amber-dim hover:text-amber font-mono"
          >
            t{data.tick_id}
          </Link>
        </div>
        {data.latency_ms !== null && (
          <div className="text-[10px] text-fg-muted font-mono">
            {data.latency_ms}ms
          </div>
        )}
      </div>

      <BudgetBar used={used} budget={data.tokens_budget} />

      <div>
        <div className="flex items-baseline justify-between mb-1">
          <h4 className="text-[10px] uppercase tracking-wider text-fg-muted">
            prompt
          </h4>
          {data.prompt_text && (
            <button
              onClick={copyPrompt}
              className="text-[10px] text-fg-muted hover:text-amber-dim border border-border px-2"
            >
              {copied ? "copied!" : "copy"}
            </button>
          )}
        </div>
        <pre className="bg-bg border border-border p-2 text-[11px] font-mono whitespace-pre-wrap max-h-64 overflow-y-auto">
          {data.prompt_text || "(empty)"}
        </pre>
      </div>

      <div>
        <h4 className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">
          tools offered ({data.tools_offered.length})
        </h4>
        <div className="flex flex-wrap gap-1">
          {data.tools_offered.map((t) => {
            const chosen = t.name === data.chosen_tool;
            return (
              <span
                key={t.name}
                title={t.description}
                className={`text-[10px] font-mono px-1.5 py-0.5 border ${
                  chosen
                    ? "border-emerald-700 text-emerald-300 bg-emerald-950/30"
                    : "border-border text-fg-muted"
                }`}
              >
                {t.name}
                {chosen && " ★"}
              </span>
            );
          })}
        </div>
      </div>

      <div>
        <h4 className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">
          model picked
        </h4>
        {data.chosen_tool ? (
          <div className="text-xs">
            <code className="text-emerald-300">{data.chosen_tool}</code>
            {data.chosen_args &&
              Object.keys(data.chosen_args).length > 0 && (
                <span className="text-fg-muted font-mono ml-2">
                  {JSON.stringify(data.chosen_args)}
                </span>
              )}
          </div>
        ) : (
          <div className="text-xs text-fg-muted">
            no tool — plain text response
          </div>
        )}
      </div>
    </div>
  );
}
