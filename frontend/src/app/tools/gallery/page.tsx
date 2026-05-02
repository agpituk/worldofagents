"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { WORLD_API_URL } from "@/lib/api";

type Card = {
  tool_id: string;
  name: string;
  kind: "composite" | "override";
  author: string;
  description: string;
  metric: number;
  metric_label: string;
};

type GalleryData = {
  featured?: Card[];
  new_and_noteworthy?: Card[];
  by_category?: Record<string, Card[]>;
  category?: string;
  entries?: Card[];
};

export default function GalleryPage() {
  const [data, setData] = useState<GalleryData | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setData(null);
    const url = category
      ? `${WORLD_API_URL}/api/tools-gallery?category=${category}`
      : `${WORLD_API_URL}/api/tools-gallery`;
    fetch(url)
      .then((r) => r.json())
      .then((d) => {
        if (live) setData(d);
      })
      .catch((e) => {
        if (live) setError(e?.message ?? "load failed");
      });
    return () => {
      live = false;
    };
  }, [category]);

  if (error) return <main className="p-6 text-rose-400">Error: {error}</main>;
  if (data === null) return <main className="p-6 text-zinc-500">loading...</main>;

  return (
    <main className="max-w-4xl mx-auto p-6 text-zinc-200">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Tools gallery</h1>
        <p className="text-sm text-zinc-400 mt-1">
          Curated discovery — featured picks, new arrivals, and tools by inferred
          role.
          <Link href="/tools" className="ml-2 underline hover:text-white">
            (or browse leaderboards)
          </Link>
        </p>
      </header>

      <nav className="flex gap-2 mb-6 flex-wrap">
        <button
          type="button"
          onClick={() => setCategory(null)}
          className={`px-3 py-1 text-sm rounded border ${
            category === null
              ? "border-emerald-700 bg-emerald-950/30 text-emerald-200"
              : "border-zinc-800 hover:border-zinc-700"
          }`}
        >
          overview
        </button>
        {data.by_category &&
          Object.keys(data.by_category).map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => setCategory(c)}
              className={`px-3 py-1 text-sm rounded border ${
                category === c
                  ? "border-emerald-700 bg-emerald-950/30 text-emerald-200"
                  : "border-zinc-800 hover:border-zinc-700"
              }`}
            >
              {c}
            </button>
          ))}
      </nav>

      {category ? (
        <Section title={category} cards={data.entries ?? []} />
      ) : (
        <>
          {data.featured && data.featured.length > 0 && (
            <Section title="Featured" cards={data.featured} />
          )}
          {data.new_and_noteworthy && data.new_and_noteworthy.length > 0 && (
            <Section title="New & noteworthy" cards={data.new_and_noteworthy} />
          )}
          {data.by_category &&
            Object.entries(data.by_category).map(([cat, cards]) =>
              cards.length === 0 ? null : (
                <Section key={cat} title={cat} cards={cards.slice(0, 6)} />
              ),
            )}
        </>
      )}
    </main>
  );
}

function Section({ title, cards }: { title: string; cards: Card[] }) {
  return (
    <section className="mb-8">
      <h2 className="text-sm uppercase tracking-wide text-zinc-400 mb-2">
        {title}
      </h2>
      {cards.length === 0 ? (
        <p className="text-zinc-500 text-sm">nothing here yet</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {cards.map((c) => (
            <Link
              key={c.tool_id}
              href={`/tools/${c.tool_id}`}
              className="block border border-zinc-800 rounded p-3 hover:border-zinc-700"
            >
              <div className="flex items-baseline gap-2">
                <code
                  className={
                    c.kind === "override"
                      ? "italic text-amber-300"
                      : "text-emerald-300"
                  }
                >
                  {c.name}
                </code>
                <span className="text-xs text-zinc-500">{c.kind}</span>
                <span className="ml-auto text-xs text-zinc-400 tabular-nums">
                  {c.metric > 0 ? `${c.metric} ${c.metric_label}` : ""}
                </span>
              </div>
              <p className="text-xs text-zinc-400 mt-1 line-clamp-2">
                {c.description || <em className="text-zinc-600">no description</em>}
              </p>
              <p className="text-xs text-zinc-500 mt-1">by {c.author}</p>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
