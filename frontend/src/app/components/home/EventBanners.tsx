"use client";

import Link from "next/link";
import { CurrentEvents } from "@/lib/api";
import { formatLifespan } from "@/lib/format";

export default function EventBanners({ events }: { events: CurrentEvents | null }) {
  if (!events) return null;
  return (
    <>
      {events.tide.active && (events.tide.leading_faction || events.tide.last_winner) && (
        <div className="border border-amber-dim bg-amber-900/10 px-4 py-3 text-sm flex items-baseline justify-between gap-3">
          <div>
            <span className="text-xs uppercase text-fg-muted mr-2">faction tide</span>
            {events.tide.leading_faction ? (
              <>
                <span className="text-amber capitalize">{events.tide.leading_faction}</span>
                <span className="text-fg-muted"> leads the surge over </span>
                <Link href={`/zones/${events.tide.contested_zone}`} className="text-amber-dim hover:text-amber">
                  {events.tide.contested_zone.replace(/_/g, " ")}
                </Link>
              </>
            ) : (
              <span className="text-fg-muted italic">no faction has gained ground this window</span>
            )}
            {events.tide.last_winner && (
              <span className="text-fg-muted"> · last claim: <span className="text-fg capitalize">{events.tide.last_winner}</span></span>
            )}
          </div>
          <span className="text-xs text-fg-muted whitespace-nowrap">
            tide closes in <span className="text-amber font-mono">{formatLifespan(events.tide.ticks_remaining)}</span>
          </span>
        </div>
      )}

      {events.wyrm.active && (
        <Link
          href={`/zones/${events.wyrm.zone}`}
          className="block border-2 border-rose-700 bg-gradient-to-r from-rose-950/40 to-amber-900/20 px-5 py-4 hover:border-rose-500 transition-colors"
        >
          <div className="flex items-baseline justify-between gap-3">
            <div>
              <div className="text-xs uppercase tracking-wider text-rose-400">live event</div>
              <div className="text-xl font-display text-amber mt-1">
                {events.wyrm.name} stalks {events.wyrm.zone.replace(/_/g, " ")}
              </div>
              <div className="text-xs text-fg-muted mt-1">
                hp {events.wyrm.hp}/{events.wyrm.hp_max} · drops a Dragon Scale to its slayer
              </div>
            </div>
            <div className="text-right shrink-0">
              <div className="text-[10px] uppercase text-fg-muted">despawns in</div>
              <div className="text-amber font-mono">
                {formatLifespan(events.wyrm.ticks_remaining)}
              </div>
            </div>
          </div>
        </Link>
      )}

      {!events.wyrm.active && events.wyrm.ticks_until_next < 600 && (
        <div className="border border-border bg-bg-card px-4 py-2 text-xs text-fg-muted">
          The Wyrm of the Sundering wakes in{" "}
          <span className="text-amber font-mono">
            {formatLifespan(events.wyrm.ticks_until_next)}
          </span>.
        </div>
      )}
    </>
  );
}
