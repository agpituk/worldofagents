"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, CurrentEvents, Discovery, Hero, Highlight, Longevity, Zone } from "@/lib/api";
import { formatLifespan } from "@/lib/format";

const KIND_COLOR: Record<Zone["kind"], string> = {
  sanctuary: "text-emerald-400",
  frontier: "text-amber",
  dungeon: "text-rose-400",
  arena: "text-violet-400",
};

export default function WorldPage() {
  const [zones, setZones] = useState<Zone[]>([]);
  const [heroes, setHeroes] = useState<Hero[]>([]);
  const [longevity, setLongevity] = useState<Longevity | null>(null);
  const [events, setEvents] = useState<CurrentEvents | null>(null);
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const [discoveries, setDiscoveries] = useState<Discovery[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const [zs, hs, lg, ev, hl, ds] = await Promise.all([
          api.listZones(),
          api.listHeroes(),
          api.longevity(8),
          api.currentEvents(),
          api.listHighlights(8),
          api.listDiscoveries(),
        ]);
        if (!live) return;
        setZones(zs);
        setHeroes(hs);
        setLongevity(lg);
        setEvents(ev);
        setHighlights(hl);
        setDiscoveries(ds);
      } catch (e: any) {
        if (live) setError(e?.message ?? "fetch failed");
      }
    }
    load();
    const t = setInterval(load, 5000);
    return () => { live = false; clearInterval(t); };
  }, []);

  if (error) {
    return (
      <div className="border border-rose-700 bg-rose-950/40 px-4 py-3 text-sm">
        World API unreachable: <code>{error}</code>
        <div className="mt-2 text-fg-muted text-xs">
          Make sure the stack is up: <code>make dev</code>.
        </div>
      </div>
    );
  }

  const heroesByZone = new Map<string, Hero[]>();
  for (const h of heroes) {
    if (!heroesByZone.has(h.zone)) heroesByZone.set(h.zone, []);
    heroesByZone.get(h.zone)!.push(h);
  }

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-3xl mb-2">Threshold &amp; the Sundered Mile</h1>
        <p className="text-fg-muted max-w-2xl">
          A persistent world where LLM-driven heroes live a life on the prompts you wrote. Click a zone to spectate live.
        </p>
        <div className="mt-3 text-xs flex gap-4">
          <Link href="/deploy" className="text-emerald-400 hover:text-emerald-300 underline font-semibold">
            deploy a hero →
          </Link>
          <Link href="/tournaments" className="text-amber-dim hover:text-amber underline">
            tournaments →
          </Link>
          <Link href="/bounties" className="text-rose-300 hover:text-rose-200 underline">
            bounty board →
          </Link>
        </div>
      </section>

      {events?.tide.active && (events.tide.leading_faction || events.tide.last_winner) && (
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

      {events?.wyrm.active && (
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

      {events && !events.wyrm.active && events.wyrm.ticks_until_next < 600 && (
        <div className="border border-border bg-bg-card px-4 py-2 text-xs text-fg-muted">
          The Wyrm of the Sundering wakes in{" "}
          <span className="text-amber font-mono">
            {formatLifespan(events.wyrm.ticks_until_next)}
          </span>.
        </div>
      )}

      {(highlights.length > 0 || discoveries.length > 0) && (
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
      )}

      {longevity && (longevity.alive.length > 0 || longevity.hall_of_fame.length > 0) && (
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
      )}

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
    </div>
  );
}
