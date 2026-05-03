"use client";

// Owner-only prompt / token / latency view for the hero's most recent
// LLM tick. Collapsed by default; expands on click. Non-owners see a
// terse "owner only" placeholder. The standalone tick page at
// /heroes/[id]/ticks/[tick] remains the deep-dive — this panel is the
// at-a-glance summary.

import { useEffect, useState } from "react";
import { api, LatestLlmCall } from "@/lib/api";
import { ownerTokenFor } from "@/lib/heroOwnership";
import PromptInspectorBody from "./PromptInspectorBody";

type Props = { heroId: string };

export default function PromptInspector({ heroId }: Props) {
  const [data, setData] = useState<LatestLlmCall | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    setToken(ownerTokenFor(heroId));
  }, [heroId]);

  useEffect(() => {
    let live = true;
    function load() {
      api
        .latestLlmCall(heroId, token)
        .then((d) => {
          if (live) setData(d);
        })
        .catch((e) => {
          if (live) setError(e?.message ?? "load failed");
        });
    }
    load();
    const t = setInterval(load, 6000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [heroId, token]);

  // Visibility logic. The panel is owner-only — non-owners see the
  // placeholder so they know the surface exists but is gated.
  const isOwner = !!token;

  return (
    <section className="mt-6 border border-border bg-bg-card">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-4 py-2 flex items-center justify-between hover:bg-bg-card/80"
      >
        <span className="text-xs uppercase tracking-wider text-fg-muted">
          prompt inspector{" "}
          {isOwner ? (
            <span className="text-emerald-400">owner</span>
          ) : (
            <span className="text-rose-400">owner only</span>
          )}
        </span>
        <span className="text-xs text-fg-muted">{open ? "−" : "+"}</span>
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 text-sm">
          {!isOwner && (
            <p className="text-xs text-fg-muted">
              Prompt, tokens, and latency are hidden — only the hero's
              owner (the browser that deployed it) can see them. The
              public tick-detail page is still available from the
              activity feed.
            </p>
          )}

          {isOwner && error && (
            <p className="text-xs text-rose-400">load failed: {error}</p>
          )}

          {isOwner && !error && data && data.tick_id === null && (
            <p className="text-xs text-fg-muted">
              No LLM tick yet — your hero hasn't called the model. If
              your reflexes route to <code>invoke_llm</code> only on
              specific conditions (low HP, NPC adjacency), this is
              normal.
            </p>
          )}

          {isOwner && data && data.tick_id !== null && (
            <PromptInspectorBody heroId={heroId} data={data} />
          )}
        </div>
      )}
    </section>
  );
}

