"use client";

import Link from "next/link";
import { Discovery, Highlight } from "@/lib/api";

type Props = {
  highlights: Highlight[];
  discoveries: Discovery[];
};

export default function MomentsAndDiscoveries({ highlights, discoveries }: Props) {
  if (highlights.length === 0 && discoveries.length === 0) return null;
  return (
    <section>
      <div className="grid grid-cols-1 md:grid-cols-[3fr_2fr] gap-6">
        <div>
          <h2 className="text-sm uppercase tracking-wider text-fg-muted mb-3">notable moments</h2>
          {highlights.length === 0 ? (
            <p className="text-fg-muted text-sm italic">The world is quiet.</p>
          ) : (
            <ol className="border border-border bg-bg-card divide-y divide-border">
              {highlights.map((h) => (
                <li key={h.event_id}>
                  <Link
                    href={`/clip/${h.event_id}`}
                    className="flex items-baseline justify-between gap-3 px-4 py-2 text-sm hover:bg-amber-dim/5"
                  >
                    <span className="truncate">{h.headline}</span>
                    <span className="text-xs text-fg-muted whitespace-nowrap font-mono">t{h.tick_id}</span>
                  </Link>
                </li>
              ))}
            </ol>
          )}
        </div>
        <div>
          <h2 className="text-sm uppercase tracking-wider text-fg-muted mb-3">discoveries</h2>
          {discoveries.length === 0 ? (
            <p className="text-fg-muted text-sm italic">
              No hidden recipes have been found. The world holds secrets.
            </p>
          ) : (
            <ol className="border border-border bg-bg-card divide-y divide-border">
              {discoveries.map((d) => (
                <li key={d.recipe_slug} className="px-4 py-2 text-sm">
                  <div className="text-amber">{d.recipe_name}</div>
                  <div className="text-xs text-fg-muted">
                    first by{" "}
                    <Link href={`/heroes/${d.discoverer_hero_id}`} className="hover:text-amber-dim">
                      {d.discoverer_name}
                    </Link>
                    <span className="font-mono ml-2">t{d.tick_id}</span>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </section>
  );
}
