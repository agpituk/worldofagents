"use client";

import { useEffect, useState } from "react";
import { api, ToolSummary, ToolDetail } from "@/lib/api";

type Props = {
  heroId: string;
};

export default function ToolListPanel({ heroId }: Props) {
  const [tools, setTools] = useState<ToolSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openTool, setOpenTool] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.toolsSummary(heroId)
      .then((r) => {
        if (live) setTools(r.tools);
      })
      .catch((e) => {
        if (live) setError(e?.message ?? "load failed");
      });
    return () => {
      live = false;
    };
  }, [heroId]);

  if (error) {
    return (
      <section className="border border-zinc-800 rounded p-3 text-sm text-zinc-400">
        Tools — error: {error}
      </section>
    );
  }
  if (tools === null) {
    return (
      <section className="border border-zinc-800 rounded p-3 text-sm text-zinc-500">
        Tools — loading...
      </section>
    );
  }
  if (tools.length === 0) {
    return (
      <section className="border border-zinc-800 rounded p-3 text-sm text-zinc-500">
        Tools — this hero has no custom tools defined.
      </section>
    );
  }

  return (
    <section className="border border-zinc-800 rounded">
      <header className="px-3 py-2 border-b border-zinc-800 text-xs uppercase tracking-wide text-zinc-400">
        Tools ({tools.length})
      </header>
      <ol className="divide-y divide-zinc-800">
        {tools.map((t) => (
          <ToolRow
            key={t.name}
            tool={t}
            heroId={heroId}
            isOpen={openTool === t.name}
            onToggle={() =>
              setOpenTool((cur) => (cur === t.name ? null : t.name))
            }
          />
        ))}
      </ol>
    </section>
  );
}

function ToolRow({
  tool,
  heroId,
  isOpen,
  onToggle,
}: {
  tool: ToolSummary;
  heroId: string;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const successPct =
    tool.calls > 0 ? Math.round((tool.success / tool.calls) * 100) : null;
  const dot =
    tool.calls === 0
      ? "text-zinc-600"
      : successPct !== null && successPct >= 80
      ? "text-emerald-400"
      : successPct !== null && successPct >= 40
      ? "text-amber-400"
      : "text-rose-400";
  const kindLabel = tool.kind === "override" ? " (override)" : "";

  return (
    <li>
      <button
        type="button"
        onClick={onToggle}
        className="w-full text-left px-3 py-2 hover:bg-zinc-900 flex items-center gap-2 text-sm"
      >
        <span className={dot}>●</span>
        <span className={tool.kind === "override" ? "italic" : "font-medium"}>
          {tool.name}
          {kindLabel}
        </span>
        <span className="ml-auto text-xs text-zinc-500 tabular-nums">
          {tool.calls}
          {successPct !== null ? ` · ${successPct}%` : " · –"}
        </span>
      </button>
      {isOpen && <ToolDetailInline heroId={heroId} toolName={tool.name} />}
    </li>
  );
}

function ToolDetailInline({
  heroId,
  toolName,
}: {
  heroId: string;
  toolName: string;
}) {
  const [data, setData] = useState<ToolDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.toolDetail(heroId, toolName)
      .then((d) => {
        if (live) setData(d);
      })
      .catch((e) => {
        if (live) setError(e?.message ?? "load failed");
      });
    return () => {
      live = false;
    };
  }, [heroId, toolName]);

  if (error) return <div className="px-3 pb-3 text-xs text-rose-400">{error}</div>;
  if (data === null)
    return <div className="px-3 pb-3 text-xs text-zinc-500">loading...</div>;

  return (
    <div className="px-3 pb-3 space-y-3 text-xs text-zinc-300 bg-zinc-950">
      <pre className="whitespace-pre-wrap font-mono text-[11px] text-zinc-400 border border-zinc-800 rounded p-2 max-h-48 overflow-auto">
        {JSON.stringify(data.definition, null, 2)}
      </pre>
      <div>
        <div className="text-zinc-500 mb-1">
          Lifetime stats: {data.stats.calls} calls · {data.stats.success} ok ·{" "}
          {data.stats.blocked_by_override} gated · {data.stats.clamps_applied}{" "}
          clamps · {data.stats.budget_exceeded} budget
        </div>
      </div>
      {data.recent_calls.length > 0 && (
        <ol className="space-y-1">
          {data.recent_calls.slice(0, 8).map((c, i) => (
            <li key={i} className="border-l-2 border-zinc-800 pl-2">
              <a
                href={`/heroes/${heroId}/ticks/${c.tick}`}
                className="text-zinc-300 hover:text-white"
              >
                tick {c.tick}
              </a>
              <span
                className={
                  c.result === "ok"
                    ? " text-emerald-400"
                    : c.result === "blocked"
                    ? " text-amber-400"
                    : " text-rose-400"
                }
              >
                {" "}
                {c.result}
              </span>
              <span className="text-zinc-500"> args: </span>
              <span className="font-mono">{JSON.stringify(c.args)}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
