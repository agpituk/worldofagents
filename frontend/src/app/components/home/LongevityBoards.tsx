"use client";

import Link from "next/link";
import { Longevity } from "@/lib/api";
import { formatLifespan } from "@/lib/format";

export default function LongevityBoards({ longevity }: { longevity: Longevity | null }) {
  if (!longevity) return null;
  if (longevity.alive.length === 0 && longevity.hall_of_fame.length === 0) return null;
  return (
    <section>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <h2 className="text-sm uppercase tracking-wider text-fg-muted mb-3">
            longest alive · current streaks
          </h2>
          {longevity.alive.length === 0 ? (
            <p className="text-fg-muted text-sm">No heroes alive.</p>
          ) : (
            <ol className="border border-border bg-bg-card divide-y divide-border">
              {longevity.alive.slice(0, 8).map((row, i) => (
                <li key={row.id}>
                  <Link
                    href={`/heroes/${row.id}`}
                    className="flex items-center justify-between px-4 py-2 text-sm hover:bg-amber-dim/5"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="text-fg-muted font-mono w-6 text-right">{i + 1}.</span>
                      <span className="truncate">{row.name}</span>
                      <span className="text-xs text-fg-muted">{row.zone}</span>
                    </div>
                    <span className="text-emerald-400 font-mono">{formatLifespan(row.ticks_alive)}</span>
                  </Link>
                </li>
              ))}
            </ol>
          )}
        </div>
        <div>
          <h2 className="text-sm uppercase tracking-wider text-fg-muted mb-3">
            hall of fame · permadeath
          </h2>
          {longevity.hall_of_fame.length === 0 ? (
            <p className="text-fg-muted text-sm italic">
              No hero has died yet. The first death is yours to claim — or avoid.
            </p>
          ) : (
            <ol className="border border-border bg-bg-card divide-y divide-border">
              {longevity.hall_of_fame.slice(0, 8).map((row, i) => (
                <li key={row.id}>
                  <Link
                    href={`/heroes/${row.id}/death`}
                    className="flex items-center justify-between px-4 py-2 text-sm hover:bg-rose-900/10"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="text-fg-muted font-mono w-6 text-right">{i + 1}.</span>
                      <span className="truncate text-rose-300 line-through">{row.name}</span>
                    </div>
                    <span className="text-rose-400 font-mono">{formatLifespan(row.ticks_alive)}</span>
                  </Link>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </section>
  );
}
