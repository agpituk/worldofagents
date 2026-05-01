"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { WORLD_API_URL } from "@/lib/api";
import { formatLifespan } from "@/lib/format";

type DeathPage = {
  id: string;
  name: string;
  author: string;
  division: string;
  bio: string;
  build: Record<string, number>;
  died_at_zone: string;
  died_at_pos: [number, number];
  killer: string | null;
  killer_kind: string | null;
  killer_id: string | null;
  looted_gold: number;
  final_gold: number;
  born_at_tick: number;
  died_at_tick: number | null;
  ticks_alive: number;
  faction_rep: Record<string, number>;
  epitaph_thoughts: { kind: string; tick_id: number; payload: any }[];
};

export default function DeathPageRoute({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [death, setDeath] = useState<DeathPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const r = await fetch(`${WORLD_API_URL}/heroes/${id}/death`, { cache: "no-store" });
        if (r.status === 404) {
          if (live) setError("Hero is alive — this monument hasn't been written.");
          return;
        }
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        const data = await r.json();
        if (live) setDeath(data);
      } catch (e: any) {
        if (live) setError(e?.message ?? "fetch failed");
      }
    }
    load();
    return () => { live = false; };
  }, [id]);

  if (error) {
    return (
      <div className="border border-rose-800 bg-rose-950/40 px-4 py-3 text-sm">
        {error}
        <div className="mt-2"><Link href={`/heroes/${id}`}>← back to the living hero</Link></div>
      </div>
    );
  }
  if (!death) return <div className="text-fg-muted">loading…</div>;

  const lastSpeech = [...death.epitaph_thoughts].reverse().find(
    (e) => e.kind === "action.resolved" && e.payload?.outcome?.verb === "say",
  );
  const speechLine = lastSpeech?.payload?.outcome?.message;

  return (
    <div className="max-w-3xl mx-auto">
      <div className="text-center mb-10">
        <Link href="/" className="text-xs text-fg-muted">← world</Link>
        <h1 className="mt-3 text-5xl font-display text-rose-400 line-through">{death.name}</h1>
        <p className="mt-2 text-sm text-fg-muted">
          {death.division} · author <span className="text-fg">{death.author}</span>
        </p>
        <p className="mt-4 text-base italic text-fg/85 leading-relaxed">{death.bio}</p>
      </div>

      <div className="grid grid-cols-3 gap-2 mb-10">
        {Object.entries(death.build).map(([k, v]) => (
          <div key={k} className="border border-border bg-bg-card py-3 text-center">
            <div className="text-xs uppercase text-fg-muted">{k}</div>
            <div className="text-2xl font-display text-amber-dim">{v}</div>
          </div>
        ))}
      </div>

      <div className="border border-border bg-bg-card px-6 py-5 text-center mb-10">
        <div className="text-xs uppercase tracking-wider text-rose-400">slain</div>
        <div className="mt-3 text-3xl font-display text-rose-400">
          {formatLifespan(death.ticks_alive)}
        </div>
        <div className="text-[10px] text-fg-muted font-mono">
          t{death.born_at_tick} → {death.died_at_tick != null ? `t${death.died_at_tick}` : "—"}
        </div>
        <div className="mt-4 text-base">
          in{" "}
          <Link href={`/zones/${death.died_at_zone}`} className="text-fg">
            {death.died_at_zone.replace(/_/g, " ")}
          </Link>
          {" "}at <span className="font-mono text-fg-muted">[{death.died_at_pos[0]},{death.died_at_pos[1]}]</span>
        </div>
        {death.killer && (
          <div className="mt-2 text-sm">
            killed by <span className="text-rose-400">{death.killer}</span>
            {death.killer_kind === "hero" && death.killer_id && (
              <> · <Link href={`/heroes/${death.killer_id}`}>their page</Link></>
            )}
          </div>
        )}
        <div className="mt-3 text-xs text-fg-muted">
          {death.final_gold} gold remaining
          {death.looted_gold > 0 && (
            <> · <span className="text-rose-400">{death.looted_gold} looted by killer</span></>
          )}
        </div>
      </div>

      {death.faction_rep && Object.keys(death.faction_rep).length > 0 && (
        <div className="text-center mb-10">
          <div className="text-xs uppercase tracking-wider text-fg-muted mb-2">standing at death</div>
          <div className="inline-flex gap-4 text-sm">
            {Object.entries(death.faction_rep).map(([f, r]) => (
              <span key={f}>
                <span className="capitalize text-fg-muted">{f}</span>{" "}
                <span className={`font-mono ${r > 0 ? "text-emerald-400" : r < 0 ? "text-rose-400" : "text-fg-muted"}`}>
                  {r > 0 ? "+" : ""}{r}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      {speechLine && (
        <div className="text-center mb-10">
          <div className="text-xs uppercase tracking-wider text-fg-muted mb-2">last words</div>
          <blockquote className="text-xl italic font-display text-amber">
            &ldquo;{speechLine}&rdquo;
          </blockquote>
        </div>
      )}

      <div>
        <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-3">
          last {death.epitaph_thoughts.length} thoughts
        </h2>
        <ol className="space-y-2">
          {death.epitaph_thoughts.map((e, i) => (
            <li key={i} className="text-sm leading-relaxed">
              <span className="text-xs text-amber-dim mr-2 font-mono">t{e.tick_id}</span>
              <span className="text-fg-muted">
                {e.kind} ·{" "}
                {e.payload?.outcome?.verb || e.payload?.npc || JSON.stringify(e.payload).slice(0, 80)}
              </span>
            </li>
          ))}
        </ol>
      </div>

      <div className="mt-12 text-center">
        <p className="text-sm text-fg-muted italic">
          &ldquo;Go and write a new manifest. Carry their build forward.&rdquo;
        </p>
      </div>
    </div>
  );
}
