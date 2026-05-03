"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type LeaderboardEntry = {
  tool_id: string;
  name: string;
  kind: "composite" | "override";
  author: string;
  metric: number;
  metric_label: string;
  description: string;
};

type Board =
  | "most_copied"
  | "best_success"
  | "most_called"
  | "highest_lift"
  | "david"
  | "best_named";

const BOARDS: { id: Board; title: string; subtitle: string }[] = [
  {
    id: "most_copied",
    title: "Most copied",
    subtitle: "What the meta is reusing",
  },
  {
    id: "best_success",
    title: "Best success rate",
    subtitle: "Tools that actually fire when picked (≥ 5 calls)",
  },
  {
    id: "most_called",
    title: "Most called",
    subtitle: "Total LLM expansions across the recent event window",
  },
  {
    id: "highest_lift",
    title: "Highest survival lift",
    subtitle: "Median lifespan delta vs heroes without the tool — suggestive, not causal",
  },
  {
    id: "david",
    title: "David tools",
    subtitle: "Featherweight-authored tools punching above their weight",
  },
  {
    id: "best_named",
    title: "Best named",
    subtitle: "Pick rate when offered — tools whose description does the work",
  },
];

export default function ToolsPage() {
  const [board, setBoard] = useState<Board>("most_copied");
  const [entries, setEntries] = useState<LeaderboardEntry[] | null>(null);
  const [honesty, setHonesty] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setEntries(null);
    setHonesty(null);
    api.toolLeaderboard(board)
      .then((body) => {
        if (live) {
          setEntries(body.entries ?? []);
          setHonesty(body.honesty ?? null);
        }
      })
      .catch((e) => {
        if (live) setError(e?.message ?? "load failed");
      });
    return () => {
      live = false;
    };
  }, [board]);

  return (
    <main className="max-w-3xl mx-auto p-6 text-zinc-200">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Tool leaderboards</h1>
        <p className="text-sm text-zinc-400 mt-1">
          User-defined composite tools and overrides, ranked. Tools are
          content-addressed: two heroes' "shoot_and_flee" are the same tool
          iff their bodies match byte-for-byte after canonicalization.
        </p>
      </header>

      <nav className="flex gap-2 flex-wrap mb-6">
        {BOARDS.map((b) => (
          <button
            key={b.id}
            type="button"
            onClick={() => setBoard(b.id)}
            className={`px-3 py-1 rounded text-sm border ${
              board === b.id
                ? "border-emerald-700 bg-emerald-950/40 text-emerald-200"
                : "border-zinc-800 hover:border-zinc-700 text-zinc-300"
            }`}
          >
            {b.title}
          </button>
        ))}
      </nav>

      <p className="text-xs text-zinc-500 mb-4">
        {BOARDS.find((b) => b.id === board)?.subtitle}
      </p>

      {honesty && (
        <div className="mb-4 px-3 py-2 border border-amber-800 bg-amber-950/30 text-xs text-amber-200">
          ⚠ {honesty}
        </div>
      )}

      {error && <p className="text-rose-400">Error: {error}</p>}
      {!error && entries === null && (
        <p className="text-zinc-500">loading...</p>
      )}
      {!error && entries !== null && entries.length === 0 && (
        <p className="text-zinc-500 text-sm">No entries yet for this board.</p>
      )}
      {entries && entries.length > 0 && (
        <ol className="space-y-2">
          {entries.map((e, i) => (
            <li
              key={e.tool_id}
              className="border border-zinc-800 rounded p-3 hover:border-zinc-700"
            >
              <div className="flex items-baseline gap-3">
                <span className="text-zinc-500 tabular-nums w-6 text-right">
                  {i + 1}.
                </span>
                <Link
                  href={`/tools/${e.tool_id}`}
                  className="font-mono text-emerald-300 hover:text-emerald-200"
                >
                  {e.name}
                </Link>
                <span className="text-xs text-zinc-500">
                  {e.kind} · by {e.author}
                </span>
                <span className="ml-auto tabular-nums text-zinc-300">
                  {e.metric}
                </span>
                <span className="text-xs text-zinc-500">{e.metric_label}</span>
              </div>
              {e.description && (
                <p className="text-xs text-zinc-400 mt-2 ml-9">
                  {e.description}
                </p>
              )}
            </li>
          ))}
        </ol>
      )}
    </main>
  );
}
