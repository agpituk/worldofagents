"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import CopyToolModal from "@/components/showcase/CopyToolModal";

type ToolDetail = {
  tool_id: string;
  name: string;
  kind: "composite" | "override";
  author: string;
  parent_tool_id: string | null;
  canonical_yaml: string;
  users: { id: string; name: string; alive: boolean }[];
  copy_count: number;
};

export default function ToolDetailPage({
  params,
}: {
  params: Promise<{ toolId: string }>;
}) {
  const { toolId } = use(params);
  const [data, setData] = useState<ToolDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [showCopyModal, setShowCopyModal] = useState(false);

  useEffect(() => {
    let live = true;
    api.toolMeta(toolId)
      .then((d) => {
        if (live) setData(d);
      })
      .catch((e) => {
        if (live) setError(e?.message ?? "load failed");
      });
    return () => {
      live = false;
    };
  }, [toolId]);

  if (error) {
    return (
      <main className="max-w-3xl mx-auto p-6 text-zinc-200">
        <Link href="/tools" className="text-sm text-zinc-400 hover:text-white">
          ← back to leaderboards
        </Link>
        <p className="text-rose-400 mt-4">Error: {error}</p>
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
      <header className="mb-4">
        <Link href="/tools" className="text-sm text-zinc-400 hover:text-white">
          ← back to leaderboards
        </Link>
      </header>

      <h1 className="text-2xl font-mono text-emerald-300">{data.name}</h1>
      <p className="text-sm text-zinc-400 mt-1">
        {data.kind} · first seen on{" "}
        <span className="text-zinc-300">{data.author}</span>
        {data.parent_tool_id && (
          <>
            {" "}
            · forked from{" "}
            <Link
              href={`/tools/${data.parent_tool_id}`}
              className="underline decoration-dotted"
            >
              {data.parent_tool_id.slice(0, 12)}…
            </Link>
          </>
        )}
      </p>
      <p className="text-xs text-zinc-500 mt-1 font-mono">
        tool_id: {data.tool_id}
      </p>

      <section className="mt-6">
        <h2 className="text-sm uppercase tracking-wide text-zinc-400 mb-2">
          Canonical YAML
        </h2>
        <pre className="font-mono text-xs text-zinc-300 border border-zinc-800 rounded p-3 whitespace-pre-wrap overflow-auto">
          {data.canonical_yaml}
        </pre>
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={() => {
              navigator.clipboard.writeText(data.canonical_yaml);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}
            className="text-xs px-2 py-1 border border-zinc-700 rounded hover:border-zinc-600 hover:bg-zinc-900"
          >
            {copied ? "copied!" : "Copy YAML to clipboard"}
          </button>
          <button
            type="button"
            onClick={() => setShowCopyModal(true)}
            className="text-xs px-2 py-1 border border-emerald-700 bg-emerald-950/30 text-emerald-200 rounded hover:bg-emerald-900/40"
          >
            Copy this tool to my hero
          </button>
        </div>
      </section>

      {showCopyModal && (
        <CopyToolModal
          toolId={data.tool_id}
          toolName={data.name}
          onClose={() => setShowCopyModal(false)}
        />
      )}

      <section className="mt-6">
        <h2 className="text-sm uppercase tracking-wide text-zinc-400 mb-2">
          Heroes using this tool ({data.users.length})
        </h2>
        {data.users.length === 0 ? (
          <p className="text-zinc-500 text-sm">No heroes currently use it.</p>
        ) : (
          <ul className="text-sm space-y-1">
            {data.users.map((u) => (
              <li key={u.id}>
                <Link
                  href={`/heroes/${u.id}`}
                  className="text-emerald-300 hover:text-emerald-200"
                >
                  {u.name}
                </Link>
                {!u.alive && (
                  <span className="text-zinc-500 ml-2 text-xs">(dead)</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-6">
        <h2 className="text-sm uppercase tracking-wide text-zinc-400 mb-2">
          Activity
        </h2>
        <p className="text-sm text-zinc-300">
          Copied {data.copy_count} time{data.copy_count === 1 ? "" : "s"}.
        </p>
      </section>
    </main>
  );
}
