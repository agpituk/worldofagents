"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { WORLD_API_URL } from "@/lib/api";

const HeroBlocksRO = dynamic(() => import("@/components/HeroBlocksRO"), { ssr: false });

type CompareTool = {
  tool_id: string;
  name: string;
  kind: "composite" | "override";
  canonical_yaml: string;
};

type CompareHero = {
  id: string;
  name: string;
  division: string;
  alive: boolean;
  tools_private: boolean;
  tools: CompareTool[];
};

type SharedTool = {
  name: string;
  identical: boolean;
  by_hero: { hero_id: string; tool_id: string; canonical_yaml: string }[];
};

type CompareData = { heroes: CompareHero[]; shared: SharedTool[] };

export default function ComparePageWrap() {
  return (
    <Suspense fallback={<div className="p-6 text-zinc-500">loading...</div>}>
      <ComparePage />
    </Suspense>
  );
}

function ComparePage() {
  const params = useSearchParams();
  const heroes = params?.get("heroes") ?? "";
  const [data, setData] = useState<CompareData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!heroes) return;
    let live = true;
    fetch(`${WORLD_API_URL}/api/compare?heroes=${encodeURIComponent(heroes)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => {
        if (live) setData(d);
      })
      .catch((e) => {
        if (live) setError(e?.message ?? "load failed");
      });
    return () => {
      live = false;
    };
  }, [heroes]);

  if (!heroes) {
    return (
      <main className="max-w-3xl mx-auto p-6 text-zinc-200">
        <h1 className="text-2xl font-semibold mb-2">Compare heroes</h1>
        <p className="text-sm text-zinc-400 mb-4">
          Pass 2-4 hero ids or names as a comma-separated list:
          <code className="ml-2 text-amber-300">/compare?heroes=alice,bob</code>
        </p>
      </main>
    );
  }
  if (error) return <main className="p-6 text-rose-400">Error: {error}</main>;
  if (data === null) return <main className="p-6 text-zinc-500">loading...</main>;

  const cols = data.heroes.length;
  const gridCols =
    cols === 2 ? "grid-cols-2" : cols === 3 ? "grid-cols-3" : "grid-cols-4";

  return (
    <main className="max-w-7xl mx-auto p-6 text-zinc-200">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">
          Comparing {data.heroes.length} heroes
        </h1>
        <p className="text-xs text-zinc-500 mt-1">
          <Link href="/tools" className="hover:text-white underline">
            ← tool leaderboards
          </Link>
        </p>
      </header>

      <div className={`grid ${gridCols} gap-4 mb-8`}>
        {data.heroes.map((h) => (
          <section
            key={h.id}
            className="border border-zinc-800 rounded p-3 text-sm"
          >
            <Link
              href={`/heroes/${h.id}`}
              className="block font-mono text-emerald-300 hover:text-emerald-200"
            >
              {h.name}
            </Link>
            <p className="text-xs text-zinc-500 mt-1">
              {h.division} · {h.alive ? "alive" : "dead"}
            </p>
            {h.tools_private ? (
              <p className="mt-3 text-xs text-zinc-500 italic">
                tool list private
              </p>
            ) : (
              <ul className="mt-3 space-y-1 text-xs">
                {h.tools.length === 0 && (
                  <li className="text-zinc-500">no custom tools</li>
                )}
                {h.tools.map((t) => (
                  <li key={t.tool_id}>
                    <Link
                      href={`/tools/${t.tool_id}`}
                      className={
                        t.kind === "override"
                          ? "italic text-amber-300 hover:underline"
                          : "text-emerald-300 hover:underline"
                      }
                    >
                      {t.name}
                    </Link>
                    <span className="ml-2 text-zinc-500">{t.kind}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        ))}
      </div>

      <section>
        <h2 className="text-sm uppercase tracking-wide text-zinc-400 mb-2">
          Shared tools ({data.shared.length})
        </h2>
        {data.shared.length === 0 ? (
          <p className="text-sm text-zinc-500">No tool name appears on ≥2 heroes.</p>
        ) : (
          <ul className="space-y-4">
            {data.shared.map((s) => (
              <li
                key={s.name}
                className="border border-zinc-800 rounded p-3 text-sm"
              >
                <header className="flex items-baseline gap-3 mb-2">
                  <span className="font-mono text-emerald-300">{s.name}</span>
                  <span
                    className={
                      s.identical
                        ? "text-xs text-emerald-400"
                        : "text-xs text-amber-400"
                    }
                  >
                    {s.identical ? "identical" : "forked — diff below"}
                  </span>
                </header>
                {!s.identical && (
                  <div className={`grid ${gridCols} gap-3 mt-2`}>
                    {s.by_hero.map((bh) => (
                      <div key={bh.hero_id}>
                        <p className="text-xs text-zinc-500 mb-1">
                          {data.heroes.find((h) => h.id === bh.hero_id)?.name ??
                            bh.hero_id.slice(0, 8)}
                        </p>
                        <HeroBlocksRO
                          yaml={`hero:\n  tools:\n    - ${bh.canonical_yaml
                            .split("\n")
                            .filter((l) => l.length > 0)
                            .join("\n      ")}`}
                          height={200}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
