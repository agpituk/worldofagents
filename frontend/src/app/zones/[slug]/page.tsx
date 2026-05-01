"use client";

import Link from "next/link";
import { use, useEffect, useRef, useState } from "react";
import { api, ZoneDetail } from "@/lib/api";
import { useZoneStream } from "@/lib/use-zone-stream";
import { ZoneMap } from "@/components/ZoneMap";

export default function ZonePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const [zone, setZone] = useState<ZoneDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { events, status } = useZoneStream(slug);
  const feedRef = useRef<HTMLOListElement | null>(null);

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const z = await api.getZone(slug);
        if (live) setZone(z);
      } catch (e: any) {
        if (live) setError(e?.message ?? "fetch failed");
      }
    }
    load();
    const t = setInterval(load, 4000);
    return () => { live = false; clearInterval(t); };
  }, [slug]);

  const narrator = events.filter((e) => e.kind === "narrator");
  const ticks = events.filter((e) => e.kind === "tick");

  // Auto-scroll the narrator feed to the latest line whenever it grows.
  useEffect(() => {
    const el = feedRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [narrator.length]);

  const aliveNPCs = (zone?.npcs ?? []).filter((n) => n.alive);
  const deadNPCs = (zone?.npcs ?? []).filter((n) => !n.alive);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[2fr_3fr] gap-6">
      <aside className="space-y-5">
        <div>
          <Link href="/" className="text-xs text-fg-muted">← world</Link>
          <h1 className="text-2xl mt-1">{zone?.name ?? slug}</h1>
          {zone && (
            <p className="text-xs text-fg-muted uppercase mt-1">
              {zone.kind} · {zone.width}×{zone.height}
            </p>
          )}
        </div>

        {zone && <p className="text-sm text-fg/80 leading-relaxed">{zone.description}</p>}

        {/* Narrator ticker — last 5 narration lines, oldest faded.
            Closes the "what's happening?" gap above the map. */}
        {narrator.length > 0 && (
          <div className="border border-border bg-bg-card px-3 py-2 text-xs space-y-0.5 font-mono">
            {narrator.slice(-5).map((e, i, arr) => {
              const ageRank = arr.length - 1 - i;  // 0 = newest, 4 = oldest
              const opacity = Math.max(0.35, 1 - ageRank * 0.16);
              return (
                <div
                  key={`${e.ts}-${i}`}
                  style={{ opacity }}
                  className={ageRank === 0 ? "text-amber" : "text-fg-muted"}
                >
                  <span className="text-fg-muted/70 mr-2">t{e.data?.tick_id}</span>
                  {e.data?.text}
                </div>
              );
            })}
          </div>
        )}

        {zone && <ZoneMap zone={zone} events={events} />}

        <div>
          <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">
            heroes ({zone?.occupants.length ?? 0})
          </h2>
          {zone?.occupants.length === 0 ? (
            <p className="text-xs text-fg-muted italic">none here right now</p>
          ) : (
            <ul className="text-sm space-y-1">
              {zone?.occupants.map((o) => (
                <li
                  key={o.id}
                  className={o.status === "dead" ? "text-rose-400 line-through" : ""}
                >
                  <Link href={`/heroes/${o.id}`}>{o.name}</Link>
                  <span className="text-xs text-fg-muted ml-2">
                    [{o.pos[0]},{o.pos[1]}] · {o.hp} hp{o.status !== "alive" ? ` · ${o.status}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {aliveNPCs.length > 0 && (
          <div>
            <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">
              denizens ({aliveNPCs.length})
            </h2>
            <ul className="text-sm space-y-2">
              {aliveNPCs.map((n) => (
                <li key={n.slug}>
                  <div>
                    <span className={n.hostility === "hostile" ? "text-rose-400" : ""}>{n.name}</span>
                    <span className="text-xs text-fg-muted ml-2">
                      [{n.pos[0]},{n.pos[1]}]
                      {n.hostility === "hostile" && ` · ${n.hp}/${n.hp_max} hp`}
                      {n.kind !== "mob" && ` · ${n.kind}`}
                    </span>
                  </div>
                  {n.merchant_stock && n.merchant_stock.length > 0 && (
                    <details className="mt-1 ml-3">
                      <summary className="text-xs text-amber-dim cursor-pointer hover:text-amber">
                        wares ({n.merchant_stock.length})
                      </summary>
                      <table className="mt-1 text-xs w-full">
                        <thead className="text-fg-muted">
                          <tr>
                            <th className="text-left pr-3">item</th>
                            <th className="text-right pr-3">buy</th>
                            <th className="text-right pr-3">sell</th>
                            <th className="text-right">qty</th>
                          </tr>
                        </thead>
                        <tbody>
                          {n.merchant_stock.map((w) => (
                            <tr key={w.slug} className={w.qty === 0 ? "text-fg-muted line-through" : ""}>
                              <td className="pr-3">{w.name ?? w.slug}</td>
                              <td className="text-right pr-3 text-amber">{w.buy_price ?? "—"}g</td>
                              <td className="text-right pr-3 text-emerald-400">{w.sell_price ?? "—"}g</td>
                              <td className="text-right font-mono">{w.qty ?? "∞"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </details>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {deadNPCs.length > 0 && (
          <div>
            <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">slain</h2>
            <ul className="text-xs text-fg-muted">
              {deadNPCs.map((n) => (
                <li key={n.slug} className="line-through">{n.name}</li>
              ))}
            </ul>
          </div>
        )}

        {zone?.connections && zone.connections.length > 0 && (
          <div>
            <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">connects to</h2>
            <ul className="text-sm">
              {zone.connections.map((c) => (
                <li key={c}>
                  <Link href={`/zones/${c}`}>{c.replace(/_/g, " ")}</Link>
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>

      <section className="border-l border-border pl-6 min-h-[60vh]">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-sm uppercase tracking-wider text-fg-muted">live narration</h2>
          <span className={`text-xs ${status === "open" ? "text-emerald-400" : status === "connecting" ? "text-amber" : "text-rose-400"}`}>
            ● {status}
          </span>
        </div>
        {error && (
          <div className="border border-rose-800 bg-rose-950/40 px-3 py-2 text-xs mb-3">{error}</div>
        )}
        {narrator.length === 0 ? (
          <p className="text-sm text-fg-muted italic">
            Quiet here. Run a bot to populate the zone.
          </p>
        ) : (
          <ol
            ref={feedRef}
            className="space-y-2 max-h-[70vh] overflow-y-auto pr-2"
          >
            {narrator.map((e, i) => (
              <li key={`${e.ts}-${i}`} className="text-sm leading-relaxed">
                <span className="text-xs text-amber-dim mr-2 font-mono">t{e.data?.tick_id}</span>
                <span>{e.data?.text}</span>
              </li>
            ))}
          </ol>
        )}

        <details className="mt-8 text-xs text-fg-muted">
          <summary className="cursor-pointer hover:text-amber">
            firehose · {ticks.length} raw events
          </summary>
          <pre className="mt-3 max-h-80 overflow-y-auto p-3 bg-black/40 border border-border whitespace-pre-wrap">
            {ticks.slice(-30).map((e, i) => (
              <div key={i}>
                t{e.data?.tick_id} {e.data?.kind} {JSON.stringify(e.data?.payload).slice(0, 140)}
              </div>
            ))}
          </pre>
        </details>
      </section>
    </div>
  );
}
