"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api, TournamentDetail } from "@/lib/api";

const STATUS_COLOR: Record<TournamentDetail["status"], string> = {
  open: "text-emerald-400",
  in_progress: "text-amber",
  closed: "text-fg-muted",
};

const ROW_STATUS: Record<string, string> = {
  registered: "text-emerald-400",
  winner: "text-amber",
  finished: "text-fg-muted",
};

export default function TournamentPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const [t, setT] = useState<TournamentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const detail = await api.getTournament(slug);
        if (live) setT(detail);
      } catch (e: any) {
        if (live) setError(e?.message ?? "fetch failed");
      }
    }
    load();
    const i = setInterval(load, 4000);
    return () => { live = false; clearInterval(i); };
  }, [slug]);

  if (error) {
    return <div className="text-rose-400 text-sm">Failed: {error}</div>;
  }
  if (!t) {
    return <div className="text-fg-muted text-sm">Loading…</div>;
  }

  return (
    <div className="space-y-6">
      <Link href="/tournaments" className="text-xs text-fg-muted hover:text-amber-dim">
        ← all tournaments
      </Link>

      <section>
        <div className="flex items-baseline justify-between gap-3">
          <h1 className="text-3xl">{t.name}</h1>
          <span className={`text-xs uppercase ${STATUS_COLOR[t.status]}`}>{t.status}</span>
        </div>
        <p className="text-fg-muted text-sm mt-2 max-w-2xl">{t.description}</p>
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          <Stat label="division" value={t.division} />
          <Stat label="zone" value={<Link className="text-amber-dim hover:text-amber" href={`/zones/${t.zone}`}>{t.zone}</Link>} />
          <Stat label="entries" value={`${t.entries}/${t.max_entries}`} />
          <Stat label="window" value={`${t.starts_at_tick} → ${t.ends_at_tick}`} />
        </div>
        <div className="mt-3 text-sm text-amber">
          Prize: {t.prize_gold}g
          {t.prize_faction ? ` + ${t.prize_faction_amount} ${t.prize_faction} rep` : ""}
        </div>
      </section>

      <section>
        <h2 className="text-sm uppercase tracking-wider text-fg-muted mb-3">leaderboard</h2>
        {t.leaderboard.length === 0 ? (
          <p className="text-fg-muted text-sm">No registrations yet — be the first.</p>
        ) : (
          <div className="border border-border bg-bg-card divide-y divide-border">
            {t.leaderboard.map((row, i) => (
              <Link
                key={row.hero_id}
                href={`/heroes/${row.hero_id}`}
                className="flex items-center justify-between px-4 py-2 text-sm hover:bg-bg-card/60"
              >
                <div className="flex items-center gap-3">
                  <span className="text-fg-muted font-mono w-6 text-right">{i + 1}.</span>
                  <span>{row.name}</span>
                  <span className={`text-xs uppercase ${ROW_STATUS[row.status] ?? ""}`}>{row.status}</span>
                </div>
                <span className="text-amber font-mono">{row.kills} kills</span>
              </Link>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="border border-border bg-bg-card px-3 py-2">
      <div className="text-fg-muted uppercase text-[10px] tracking-wider">{label}</div>
      <div className="font-mono text-fg mt-0.5">{value}</div>
    </div>
  );
}
