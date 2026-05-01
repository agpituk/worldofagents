"use client";

// Clip page — visual replay of the 30-tick window of events around a notable
// moment. Scrubber controls which tick is "now"; the zone map flashes the
// hits at that tick. Linked from the home page "notable moments" feed and
// designed as the share surface for "look what just happened" posts.

import Link from "next/link";
import { use, useEffect, useMemo, useState } from "react";
import { api, Clip, ZoneDetail } from "@/lib/api";
import type { StreamEvent } from "@/lib/use-zone-stream";
import { ZoneMap } from "@/components/ZoneMap";

export default function ClipPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [clip, setClip] = useState<Clip | null>(null);
  const [zone, setZone] = useState<ZoneDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [currentTick, setCurrentTick] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .getClip(parseInt(id, 10), 15)
      .then((c) => {
        if (live) {
          setClip(c);
          setCurrentTick(c.pivot_tick);
        }
      })
      .catch((e) => {
        if (live) setError(e?.message ?? "fetch failed");
      });
    return () => { live = false; };
  }, [id]);

  // Derive the primary zone from the events list (mode of zone field).
  const primaryZone = useMemo(() => {
    if (!clip) return null;
    const counts = new Map<string, number>();
    for (const e of clip.events) {
      if (e.zone) counts.set(e.zone, (counts.get(e.zone) ?? 0) + 1);
    }
    let best: string | null = null;
    let bestN = 0;
    for (const [z, n] of counts) {
      if (n > bestN) { best = z; bestN = n; }
    }
    return best;
  }, [clip]);

  useEffect(() => {
    if (!primaryZone) return;
    let live = true;
    api.getZone(primaryZone).then((z) => { if (live) setZone(z); }).catch(() => {});
    return () => { live = false; };
  }, [primaryZone]);

  // Synthesize StreamEvents at the scrubber's current tick. ZoneMap reacts
  // to events.length and flashes for combat hits — feeding it the events
  // for the active tick gives us replay flashes.
  const eventsAtTick = useMemo<StreamEvent[]>(() => {
    if (!clip || currentTick == null) return [];
    return clip.events
      .filter((e) => e.tick_id === currentTick)
      .map((e, i) => ({
        kind: "tick",
        ts: Date.now() + i,
        data: {
          tick_id: e.tick_id,
          zone: e.zone,
          kind: e.kind,
          payload: e.payload,
        },
      }));
  }, [clip, currentTick]);

  // Auto-play: advance currentTick every 700ms, loop at end.
  useEffect(() => {
    if (!playing || !clip || currentTick == null) return;
    const interval = setInterval(() => {
      setCurrentTick((t) => {
        if (t == null) return clip.window[0];
        return t >= clip.window[1] ? clip.window[0] : t + 1;
      });
    }, 700);
    return () => clearInterval(interval);
  }, [playing, clip, currentTick]);

  if (error) return <div className="text-rose-400 text-sm">Failed: {error}</div>;
  if (!clip || currentTick == null) return <div className="text-fg-muted text-sm">loading…</div>;

  function copyShareUrl() {
    navigator.clipboard.writeText(window.location.href).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  // Group events by tick for replay-friendly rendering of the timeline.
  const byTick = new Map<number, typeof clip.events>();
  for (const e of clip.events) {
    if (!byTick.has(e.tick_id)) byTick.set(e.tick_id, []);
    byTick.get(e.tick_id)!.push(e);
  }

  const ticksRange: number[] = [];
  for (let t = clip.window[0]; t <= clip.window[1]; t++) ticksRange.push(t);

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <Link href="/" className="text-xs text-fg-muted hover:text-amber-dim">← world</Link>

      <section>
        <div className="text-xs uppercase tracking-wider text-rose-400">notable moment</div>
        <h1 className="text-3xl font-display text-amber mt-1">{clip.headline}</h1>
        <div className="mt-2 text-xs text-fg-muted font-mono">
          tick t{clip.pivot_tick} · window t{clip.window[0]}–t{clip.window[1]}
          {primaryZone && <> · in <Link href={`/zones/${primaryZone}`} className="text-amber-dim hover:text-amber">{primaryZone.replace(/_/g, " ")}</Link></>}
        </div>
        <button
          onClick={copyShareUrl}
          className="mt-3 text-xs text-amber-dim hover:text-amber border border-border bg-bg-card px-3 py-1"
        >
          {copied ? "link copied" : "copy share link"}
        </button>
      </section>

      {/* Visual replay — zone map keyed to scrubber tick.
          Static occupant positions (we don't snapshot them per-tick yet) but
          flashes/floats sync to the scrubber, so impact moments are visible. */}
      {zone && (
        <section className="space-y-3">
          <div className="flex items-center gap-3 text-xs">
            <button
              onClick={() => setPlaying((p) => !p)}
              className="border border-amber bg-amber-dim/10 text-amber px-3 py-1 hover:bg-amber-dim/20"
            >
              {playing ? "❚❚ pause" : "▶ play"}
            </button>
            <button
              onClick={() => { setCurrentTick(clip.window[0]); setPlaying(false); }}
              className="border border-border bg-bg-card text-fg-muted px-3 py-1 hover:border-amber-dim"
            >
              ⏮ start
            </button>
            <button
              onClick={() => { setCurrentTick(clip.pivot_tick); setPlaying(false); }}
              className="border border-border bg-bg-card text-fg-muted px-3 py-1 hover:border-amber-dim"
            >
              ⊙ pivot
            </button>
            <span
              className={`ml-auto font-mono ${currentTick === clip.pivot_tick ? "text-amber" : "text-fg-muted"}`}
            >
              t{currentTick}
              {currentTick === clip.pivot_tick && " · pivot"}
            </span>
          </div>

          <input
            type="range"
            min={clip.window[0]}
            max={clip.window[1]}
            value={currentTick}
            onChange={(e) => { setCurrentTick(parseInt(e.target.value, 10)); setPlaying(false); }}
            className="w-full accent-amber"
          />

          <div className="flex gap-px h-4 -mt-2 text-[8px]">
            {ticksRange.map((t) => {
              const hasEvents = byTick.has(t);
              const isPivot = t === clip.pivot_tick;
              const isCurrent = t === currentTick;
              return (
                <button
                  key={t}
                  onClick={() => { setCurrentTick(t); setPlaying(false); }}
                  className={`flex-1 border-t-2 ${
                    isCurrent ? "border-amber"
                      : isPivot ? "border-rose-400"
                      : hasEvents ? "border-amber-dim/50"
                      : "border-border"
                  } hover:border-amber transition-colors`}
                  title={`t${t}${hasEvents ? ` · ${byTick.get(t)!.length} events` : ""}`}
                />
              );
            })}
          </div>

          <ZoneMap zone={zone} events={eventsAtTick} />
        </section>
      )}

      <section>
        <h2 className="text-sm uppercase tracking-wider text-fg-muted mb-3">timeline</h2>
        <ol className="space-y-3">
          {ticksRange.filter((t) => byTick.has(t)).map((t) => {
            const isPivot = t === clip.pivot_tick;
            const isCurrent = t === currentTick;
            const evs = byTick.get(t) || [];
            return (
              <li
                key={t}
                onClick={() => setCurrentTick(t)}
                className={`border-l-2 pl-3 cursor-pointer ${
                  isCurrent
                    ? "border-amber bg-amber-dim/10"
                    : isPivot
                      ? "border-rose-400 bg-rose-950/10"
                      : "border-border hover:border-amber-dim"
                }`}
              >
                <div
                  className={`text-xs font-mono mb-1 ${
                    isCurrent ? "text-amber" : isPivot ? "text-rose-400" : "text-fg-muted"
                  }`}
                >
                  t{t}{isPivot ? " · pivot" : ""}{isCurrent ? " · now" : ""}
                </div>
                <ul className="space-y-1 text-sm">
                  {evs.map((e) => {
                    const out = e.payload?.outcome ?? e.payload;
                    const verb = out?.verb;
                    return (
                      <li key={e.id} className="text-fg/85">
                        <span className="text-fg-muted text-xs uppercase tracking-wider mr-2">{e.kind}</span>
                        {verb && <span className="text-amber-dim">{verb}</span>}
                        {out?.target && (<span> → <span className="text-fg">{out.target}</span></span>)}
                        {out?.killed && <span className="text-rose-400 ml-2">killed</span>}
                        {out?.damage !== undefined && (
                          <span className="text-fg-muted text-xs ml-2 font-mono">{out.damage} dmg</span>
                        )}
                        {!verb && (
                          <span className="text-fg-muted text-xs">{JSON.stringify(out).slice(0, 120)}</span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </li>
            );
          })}
        </ol>
      </section>

      {clip.journal.length > 0 && (
        <section>
          <h2 className="text-sm uppercase tracking-wider text-fg-muted mb-3">journal entries in window</h2>
          <ol className="space-y-2 text-sm">
            {clip.journal.map((j) => (
              <li
                key={j.id}
                className={`border-l-2 pl-3 ${j.kind === "milestone" ? "border-amber-dim" : "border-blue-700"}`}
              >
                <div className="text-xs text-amber-dim font-mono mb-0.5">t{j.tick_id} · {j.kind}</div>
                <div className={j.kind === "player" ? "italic text-fg" : "text-fg/85"}>{j.text}</div>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}
