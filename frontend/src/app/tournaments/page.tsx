"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Tournament } from "@/lib/api";

const STATUS_COLOR: Record<Tournament["status"], string> = {
  open: "text-emerald-400",
  in_progress: "text-amber",
  closed: "text-fg-muted",
};

export default function TournamentsPage() {
  const [tournaments, setTournaments] = useState<Tournament[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const ts = await api.listTournaments();
        if (live) setTournaments(ts);
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
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-3xl mb-2">Tournaments</h1>
        <p className="text-fg-muted max-w-2xl text-sm">
          Pay the wood, the wood pays you back. Register your hero inside the
          arena zone to compete; kills against other heroes in the window count.
          Top of the ladder when the window closes wins the prize.
        </p>
      </section>

      {tournaments.length === 0 ? (
        <p className="text-fg-muted text-sm">No tournaments seeded.</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {tournaments.map((t) => (
            <Link
              key={t.slug}
              href={`/tournaments/${t.slug}`}
              className="border border-border bg-bg-card hover:border-amber-dim px-5 py-4 block transition-colors"
            >
              <div className="flex items-baseline justify-between gap-3">
                <h3 className="text-lg group-hover:text-amber">{t.name}</h3>
                <span className={`text-xs uppercase ${STATUS_COLOR[t.status]}`}>{t.status}</span>
              </div>
              <p className="text-xs text-fg-muted mt-1 line-clamp-2">{t.description}</p>
              <div className="mt-3 grid grid-cols-3 gap-2 text-xs text-fg-muted">
                <span>div · <span className="text-fg">{t.division}</span></span>
                <span>zone · <span className="text-fg">{t.zone}</span></span>
                <span>{t.entries}/{t.max_entries} heroes</span>
              </div>
              <div className="mt-2 text-xs text-amber">
                {t.prize_gold}g
                {t.prize_faction ? ` + ${t.prize_faction_amount} ${t.prize_faction} rep` : ""}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
