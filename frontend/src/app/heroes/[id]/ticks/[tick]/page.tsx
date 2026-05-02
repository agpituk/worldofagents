"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api, TickLlmCall } from "@/lib/api";

export default function TickLlmCallPage({
  params,
}: {
  params: Promise<{ id: string; tick: string }>;
}) {
  const { id, tick } = use(params);
  const tickNum = Number(tick);
  const [data, setData] = useState<TickLlmCall | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.tickLlmCall(id, tickNum)
      .then((d) => {
        if (live) setData(d);
      })
      .catch((e) => {
        if (live) setError(e?.message ?? "load failed");
      });
    return () => {
      live = false;
    };
  }, [id, tickNum]);

  if (error) {
    return (
      <main className="max-w-3xl mx-auto p-6 text-zinc-200">
        <header className="mb-4 text-sm text-zinc-400">
          <Link href={`/heroes/${id}`} className="hover:text-white">
            ← back to hero
          </Link>
        </header>
        <h1 className="text-xl font-semibold mb-2">Tick {tickNum}</h1>
        <p className="text-rose-400">Error: {error}</p>
      </main>
    );
  }

  if (data === null) {
    return (
      <main className="max-w-3xl mx-auto p-6 text-zinc-500">loading...</main>
    );
  }

  return (
    <main className="max-w-3xl mx-auto p-6 text-zinc-200">
      <header className="mb-4 text-sm text-zinc-400">
        <Link href={`/heroes/${id}`} className="hover:text-white">
          ← back to hero
        </Link>
      </header>

      <h1 className="text-xl font-semibold mb-2">
        Tick {tickNum} — LLM picked{" "}
        <code className="text-emerald-400">{data.chosen_tool ?? "—"}</code>
      </h1>
      {data.chosen_args && Object.keys(data.chosen_args).length > 0 && (
        <p className="text-xs text-zinc-500 mb-4 font-mono">
          args: {JSON.stringify(data.chosen_args)}
        </p>
      )}

      <section className="mb-6">
        <h2 className="text-sm uppercase tracking-wide text-zinc-400 mb-2">
          The LLM saw {data.tools_offered.length} tools
        </h2>
        <ol className="space-y-1 text-sm">
          {data.tools_offered.map((t) => {
            const mentioned = data.tool_mentions.includes(t.name);
            const chosen = t.name === data.chosen_tool;
            return (
              <li
                key={t.name}
                className={`px-2 py-1 rounded border ${
                  chosen
                    ? "border-emerald-700 bg-emerald-950/30"
                    : mentioned
                    ? "border-amber-700 bg-amber-950/20"
                    : "border-zinc-800"
                }`}
              >
                <code
                  className={
                    chosen
                      ? "text-emerald-300"
                      : mentioned
                      ? "text-amber-300"
                      : "text-zinc-300"
                  }
                >
                  {t.name}
                </code>
                {chosen && (
                  <span className="text-emerald-400 text-xs ml-2">CHOSEN</span>
                )}
                {!chosen && mentioned && (
                  <span className="text-amber-400 text-xs ml-2">
                    MENTIONED
                  </span>
                )}
                <p className="text-xs text-zinc-500 mt-0.5">{t.description}</p>
              </li>
            );
          })}
        </ol>
      </section>

      {data.reasoning_trace && (
        <section className="mb-6">
          <h2 className="text-sm uppercase tracking-wide text-zinc-400 mb-2">
            Reasoning (first 500 chars)
          </h2>
          <pre className="whitespace-pre-wrap font-mono text-xs text-zinc-300 border border-zinc-800 rounded p-3">
            {data.reasoning_trace}
          </pre>
        </section>
      )}

      <p className="text-xs text-zinc-500">
        The "MENTIONED" highlight uses simple substring matching on the
        reasoning trace — it's a hint, not a proof. The LLM's full
        deliberation isn't visible to us.
      </p>
    </main>
  );
}
