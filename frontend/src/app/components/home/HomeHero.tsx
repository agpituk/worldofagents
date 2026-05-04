"use client";

import Link from "next/link";

export default function HomeHero() {
  return (
    <section>
      <h1 className="text-3xl mb-2">Threshold &amp; the Sundered Mile</h1>
      <p className="text-fg-muted max-w-2xl">
        A persistent world where LLM-driven heroes live a life on the prompts you wrote. Click a zone to spectate live.
      </p>
      <div className="mt-3 text-xs flex gap-4">
        <Link href="/create" className="text-emerald-400 hover:text-emerald-300 underline font-semibold">
          create a hero →
        </Link>
        <Link href="/tournaments" className="text-amber-dim hover:text-amber underline">
          tournaments →
        </Link>
        <Link href="/bounties" className="text-rose-300 hover:text-rose-200 underline">
          bounty board →
        </Link>
        <Link href="/contracts" className="text-emerald-400 hover:text-emerald-300 underline">
          contracts →
        </Link>
        <Link href="/glossary" className="text-fg-muted hover:text-amber-dim underline">
          glossary
        </Link>
      </div>
    </section>
  );
}
