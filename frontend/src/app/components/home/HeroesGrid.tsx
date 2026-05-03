"use client";

import Link from "next/link";
import { Hero } from "@/lib/api";

export default function HeroesGrid({ heroes }: { heroes: Hero[] }) {
  return (
    <section>
      <h2 className="text-sm uppercase tracking-wider text-fg-muted mb-3">heroes</h2>
      {heroes.length === 0 ? (
        <p className="text-fg-muted text-sm">
          No heroes registered yet. Run the bot in <code>bot-sdk-python</code> to spawn one.
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {heroes.map((h) => (
            <Link
              key={h.id}
              href={`/heroes/${h.id}`}
              className="border border-border bg-bg-card px-4 py-3 hover:border-amber-dim"
            >
              <div className="flex items-baseline justify-between">
                <span className="text-base">{h.name}</span>
                <span className="text-xs uppercase text-amber">{h.division}</span>
              </div>
              <div className="text-xs text-fg-muted mt-1">
                HP {h.hp} · {h.zone} · {h.status}
              </div>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
