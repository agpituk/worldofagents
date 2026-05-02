"use client";

import dynamic from "next/dynamic";
import yaml from "js-yaml";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ToolDetail } from "@/lib/api";
import TraceTree from "./TraceTree";
import ToolStatsChart from "./ToolStatsChart";

const HeroBlocksRO = dynamic(() => import("@/components/HeroBlocksRO"), { ssr: false });

type Props = {
  heroId: string;
  toolName: string;
  onClose: () => void;
};

type Tab = "definition" | "recent" | "stats";

export default function ToolDetailDrawer({ heroId, toolName, onClose }: Props) {
  const [data, setData] = useState<ToolDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("definition");
  const [openCall, setOpenCall] = useState<number | null>(null);

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

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/50"
      onClick={onClose}
    >
      <aside
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-xl h-full bg-zinc-950 border-l border-zinc-800 overflow-y-auto"
      >
        <header className="sticky top-0 bg-zinc-950 border-b border-zinc-800 px-4 py-3 flex items-baseline gap-3">
          <h2 className="font-mono text-emerald-300">{toolName}</h2>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto text-zinc-400 hover:text-white text-sm"
          >
            close ×
          </button>
        </header>

        <nav className="flex gap-2 border-b border-zinc-800 px-4 text-xs">
          {(["definition", "recent", "stats"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`px-3 py-2 ${
                tab === t
                  ? "text-emerald-300 border-b-2 border-emerald-500"
                  : "text-zinc-400 hover:text-white"
              }`}
            >
              {t}
            </button>
          ))}
        </nav>

        <div className="p-4">
          {error && <p className="text-rose-400 text-sm">Error: {error}</p>}
          {data === null && !error && (
            <p className="text-zinc-500 text-sm">loading...</p>
          )}

          {data && tab === "definition" && (
            <div className="space-y-3">
              <p className="text-xs text-zinc-400">
                {data.definition.description?.toString().slice(0, 600) ??
                  "no description"}
              </p>
              <HeroBlocksRO
                yaml={yaml.dump({
                  hero: { tools: [data.definition] },
                })}
                height={320}
              />
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard.writeText(yaml.dump(data.definition));
                }}
                className="text-xs px-2 py-1 border border-zinc-700 rounded hover:border-zinc-600"
              >
                Copy YAML
              </button>
            </div>
          )}

          {data && tab === "recent" && (
            <div className="space-y-2">
              {data.recent_calls.length === 0 && (
                <p className="text-xs text-zinc-500">No calls yet.</p>
              )}
              {data.recent_calls.map((c, i) => {
                const isOpen = openCall === i;
                return (
                  <div
                    key={i}
                    className="border border-zinc-800 rounded text-xs"
                  >
                    <button
                      type="button"
                      onClick={() => setOpenCall(isOpen ? null : i)}
                      className="w-full text-left px-3 py-2 flex items-baseline gap-3 hover:bg-zinc-900"
                    >
                      <Link
                        href={`/heroes/${heroId}/ticks/${c.tick}`}
                        onClick={(e) => e.stopPropagation()}
                        className="text-emerald-300 hover:text-emerald-200"
                      >
                        tick {c.tick}
                      </Link>
                      <span
                        className={
                          c.result === "ok"
                            ? "text-emerald-400"
                            : c.result === "blocked"
                            ? "text-amber-400"
                            : "text-rose-400"
                        }
                      >
                        {c.result === "ok"
                          ? "✓"
                          : c.result === "blocked"
                          ? "⊘"
                          : "✗"}{" "}
                        {c.result}
                      </span>
                      <span className="text-zinc-500 truncate">
                        {JSON.stringify(c.args)}
                      </span>
                      <span className="ml-auto text-zinc-500">
                        {isOpen ? "▼" : "▸"}
                      </span>
                    </button>
                    {isOpen && (
                      <div className="border-t border-zinc-800 px-3 py-2 bg-zinc-950/50">
                        <TraceTree trace={c.trace} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {data && tab === "stats" && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 text-xs">
                <Stat label="calls" value={data.stats.calls} />
                <Stat label="success" value={data.stats.success} />
                <Stat
                  label="blocked by override"
                  value={data.stats.blocked_by_override}
                />
                <Stat
                  label="clamps applied"
                  value={data.stats.clamps_applied}
                />
                <Stat
                  label="budget exceeded"
                  value={data.stats.budget_exceeded}
                />
              </div>
              <ToolStatsChart
                calls={data.recent_calls.map((c) => ({
                  tick: c.tick,
                  result: c.result,
                }))}
              />
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="border border-zinc-800 rounded px-3 py-2">
      <div className="text-zinc-500 uppercase tracking-wide text-[10px]">
        {label}
      </div>
      <div className="text-zinc-100 text-base tabular-nums">{value}</div>
    </div>
  );
}
