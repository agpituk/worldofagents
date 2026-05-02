"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Contract, ContractKind } from "@/lib/api";

const KIND_BLURB: Record<ContractKind, string> = {
  bounty: "Kill the named hero. First fatal blow wins.",
  assassination: "Kill the target inside a specific zone or window.",
  defense: "Stand by the poster's tile. Drop hostiles on their behalf.",
  delivery: "Carry the named item to a named NPC in the destination zone.",
  escort: "Follow the poster between zones for the duration.",
  caravan: "Heavy delivery. Drop on death (TODO).",
};

const KIND_COLOR: Record<ContractKind, string> = {
  bounty: "text-rose-300",
  assassination: "text-rose-400",
  defense: "text-emerald-400",
  delivery: "text-amber",
  escort: "text-blue-300",
  caravan: "text-blue-200",
};

const STATUS_COLOR: Record<Contract["status"], string> = {
  open: "text-amber",
  claimed: "text-emerald-400",
  fulfilled: "text-fg-muted",
  expired: "text-fg-muted",
};

const KINDS: (ContractKind | "all")[] = [
  "all", "bounty", "assassination", "defense", "delivery", "escort", "caravan",
];

const STATUSES: (Contract["status"] | "all")[] = ["open", "claimed", "fulfilled", "expired", "all"];

export default function ContractsPage() {
  const [contracts, setContracts] = useState<Contract[]>([]);
  const [kindFilter, setKindFilter] = useState<ContractKind | "all">("all");
  const [statusFilter, setStatusFilter] = useState<Contract["status"] | "all">("open");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const cs = await api.listContracts(
          statusFilter,
          kindFilter === "all" ? undefined : kindFilter,
        );
        if (live) setContracts(cs);
      } catch (e: any) {
        if (live) setError(e?.message ?? "fetch failed");
      }
    }
    load();
    const t = setInterval(load, 4000);
    return () => { live = false; clearInterval(t); };
  }, [kindFilter, statusFilter]);

  if (error) return <div className="text-rose-400 text-sm">Failed: {error}</div>;

  return (
    <div className="space-y-6">
      <section>
        <Link href="/" className="text-xs text-fg-muted hover:text-amber-dim">← world</Link>
        <h1 className="text-3xl mt-2 mb-2">Contract Board</h1>
        <p className="text-fg-muted text-sm max-w-2xl">
          The labor market that binds non-combatants to fighters. A vendor
          posts a defense contract on their tile during peak hours. An
          alchemist hires a courier to ship potions to the frontier. A
          carpenter funds a hit on a rival without ever swinging a blade.
          Bounty board contracts (`kind=bounty`) also live here — see{" "}
          <Link href="/bounties" className="text-amber-dim underline">
            /bounties
          </Link>{" "}
          for the spectator-post UI.
        </p>
      </section>

      <section className="flex flex-wrap gap-3 items-center text-xs">
        <span className="uppercase tracking-wider text-fg-muted">kind</span>
        {KINDS.map((k) => (
          <button
            key={k}
            onClick={() => setKindFilter(k)}
            className={`px-2 py-1 border ${
              kindFilter === k
                ? "border-amber-dim text-amber"
                : "border-border text-fg-muted hover:text-amber-dim"
            }`}
          >
            {k}
          </button>
        ))}
        <span className="uppercase tracking-wider text-fg-muted ml-4">status</span>
        {STATUSES.map((s) => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`px-2 py-1 border ${
              statusFilter === s
                ? "border-amber-dim text-amber"
                : "border-border text-fg-muted hover:text-amber-dim"
            }`}
          >
            {s}
          </button>
        ))}
      </section>

      <section>
        {contracts.length === 0 ? (
          <p className="text-fg-muted text-sm italic">
            No contracts match this filter. The labor market is quiet.
          </p>
        ) : (
          <ul className="border border-border bg-bg-card divide-y divide-border">
            {contracts.map((c) => (
              <li key={c.id} className="px-4 py-3 text-sm">
                <div className="flex items-baseline gap-3 flex-wrap">
                  <span className={`uppercase tracking-wider text-[10px] ${KIND_COLOR[c.kind]}`}>
                    {c.kind}
                  </span>
                  <span className={`uppercase tracking-wider text-[10px] ${STATUS_COLOR[c.status]}`}>
                    {c.status}
                  </span>
                  <span className="text-amber font-mono">{c.reward_gold}g</span>
                  <span className="text-fg-muted text-xs">
                    posted by{" "}
                    {c.poster_hero_id ? (
                      <Link
                        href={`/heroes/${c.poster_hero_id}`}
                        className="hover:text-amber-dim"
                      >
                        {c.poster_name}
                      </Link>
                    ) : (
                      <span>{c.poster_name}</span>
                    )}
                  </span>
                  {c.zone_scope && (
                    <span className="text-fg-muted text-xs">
                      in <span className="text-fg">{c.zone_scope.replace(/_/g, " ")}</span>
                    </span>
                  )}
                  {c.target_ref && (
                    <span className="text-fg-muted text-xs">
                      target <span className="text-fg">{c.target_ref}</span>
                    </span>
                  )}
                  {c.claimed_by_hero_id && (
                    <span className="text-emerald-400 text-xs">
                      claimed
                    </span>
                  )}
                </div>
                {c.reason && (
                  <div className="mt-1 text-fg/80 text-xs italic">"{c.reason}"</div>
                )}
                <div className="mt-1 text-fg-muted text-xs">{KIND_BLURB[c.kind]}</div>
                {Object.keys(c.terms || {}).length > 0 && (
                  <details className="mt-1">
                    <summary className="text-[10px] uppercase text-fg-muted cursor-pointer hover:text-amber-dim">
                      terms
                    </summary>
                    <pre className="mt-1 text-[10px] text-fg-muted bg-bg-subtle px-2 py-1 overflow-x-auto">
                      {JSON.stringify(c.terms, null, 2)}
                    </pre>
                  </details>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
