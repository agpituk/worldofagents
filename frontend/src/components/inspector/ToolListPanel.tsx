"use client";

import { useEffect, useState } from "react";
import { api, ToolSummary } from "@/lib/api";
import ToolDetailDrawer from "./ToolDetailDrawer";

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
    <>
      <section className="border border-zinc-800 rounded">
        <header className="px-3 py-2 border-b border-zinc-800 text-xs uppercase tracking-wide text-zinc-400">
          Tools ({tools.length})
        </header>
        <ol className="divide-y divide-zinc-800">
          {tools.map((t) => (
            <ToolRow
              key={t.name}
              tool={t}
              onOpen={() => setOpenTool(t.name)}
            />
          ))}
        </ol>
      </section>
      {openTool && (
        <ToolDetailDrawer
          heroId={heroId}
          toolName={openTool}
          onClose={() => setOpenTool(null)}
        />
      )}
    </>
  );
}

function ToolRow({
  tool,
  onOpen,
}: {
  tool: ToolSummary;
  onOpen: () => void;
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
        onClick={onOpen}
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
    </li>
  );
}
