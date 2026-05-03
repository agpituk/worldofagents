"use client";

// First-tick simulation panel — debounced server-side dry-run.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SimulateTickResult } from "@/lib/api";

export default function SimulationPanel({ manifest }: { manifest: string }) {
  const [data, setData] = useState<SimulateTickResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (manifest.trim().length === 0) {
      setData(null);
      return;
    }
    setPending(true);
    const id = setTimeout(async () => {
      try {
        const r = await api.simulateTick(manifest);
        setData(r);
        setError(null);
      } catch (e: any) {
        setError(e?.message ?? "simulate failed");
      } finally {
        setPending(false);
      }
    }, 600);
    return () => clearTimeout(id);
  }, [manifest]);

  return (
    <section className="border border-border bg-bg-card p-3 text-xs">
      <div className="uppercase tracking-wider text-fg-muted mb-2">
        first-tick simulation {pending && <span className="text-amber-dim">(refreshing…)</span>}
      </div>
      {error && <p className="text-rose-400">{error}</p>}
      {!error && data && (
        <div className="space-y-1">
          <p>
            <span className="text-fg-muted">would do:</span>{" "}
            <code className="text-amber">
              {data.chosen_action.do}
              {Object.keys(data.chosen_action).filter((k) => k !== "do" && !k.startsWith("_")).length > 0
                ? `(${Object.entries(data.chosen_action)
                    .filter(([k]) => k !== "do" && !k.startsWith("_"))
                    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                    .join(", ")})`
                : "()"}
            </code>
          </p>
          {data.when && (
            <p>
              <span className="text-fg-muted">via reflex #{data.chosen_reflex_index}:</span>{" "}
              <code className="text-fg-muted">when {data.when}</code>
            </p>
          )}
          {data.chosen_reflex_index === null && (
            <p className="text-fg-muted italic">
              no reflex matched — would emit `wait` (LLM only fires on
              explicit invoke_llm).
            </p>
          )}
          <p className="text-fg-muted mt-2">
            LLM tool list: {data.tools_visible_to_llm.length} tools (
            {data.composite_count} composites, {data.override_count} overrides).
          </p>
        </div>
      )}
    </section>
  );
}
