"use client";

import Link from "next/link";
import { Hero, Zone } from "@/lib/api";

const KIND_COLOR: Record<Zone["kind"], string> = {
  sanctuary: "text-emerald-400",
  frontier: "text-amber",
  dungeon: "text-rose-400",
  arena: "text-violet-400",
};

type Props = {
  zones: Zone[];
  heroes: Hero[];
  heroesByZone: Map<string, Hero[]>;
};

export default function ZonesGrid({ zones, heroes, heroesByZone }: Props) {
  return (
    <section>
      <h2 className="text-sm uppercase tracking-wider text-fg-muted mb-3">
        {zones.length} zones · {heroes.length} heroes alive
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {zones.map((z) => {
          const occupants = heroesByZone.get(z.slug) || [];
          return (
            <Link
              key={z.slug}
              href={`/zones/${z.slug}`}
              className="group border border-border bg-bg-card hover:border-amber-dim transition-colors px-5 py-4 block"
            >
              <div className="flex items-baseline justify-between gap-3">
                <h3 className="text-lg group-hover:text-amber">{z.name}</h3>
                <span className={`text-xs uppercase ${KIND_COLOR[z.kind]}`}>{z.kind}</span>
              </div>
              <p className="text-xs text-fg-muted mt-1 line-clamp-2">
                {z.description}
              </p>
              <div className="mt-3 text-xs flex items-center justify-between text-fg-muted">
                <span>
                  {occupants.length}/{z.capacity_soft} heroes
                </span>
                <span className="font-mono">
                  {z.width}×{z.height}
                </span>
              </div>
              {occupants.length > 0 && (
                <div className="mt-2 text-xs text-amber-dim truncate">
                  {occupants.map((h) => h.name).join(" · ")}
                </div>
              )}
            </Link>
          );
        })}
      </div>
    </section>
  );
}
