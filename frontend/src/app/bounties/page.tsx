"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Bounty } from "@/lib/api";

const STATUS_COLOR: Record<Bounty["status"], string> = {
  open: "text-rose-300",
  claimed: "text-fg-muted",
  expired: "text-fg-muted",
};

function formatRetry(s: number): string {
  if (s < 60) return `${s}s`;
  return `${Math.ceil(s / 60)}m`;
}

export default function BountiesPage() {
  const [bounties, setBounties] = useState<Bounty[]>([]);
  const [filter, setFilter] = useState<"open" | "claimed" | "all">("open");
  const [error, setError] = useState<string | null>(null);

  // Spectator bounty form state
  const [target, setTarget] = useState("");
  const [gold, setGold] = useState("25");
  const [reason, setReason] = useState("");
  const [posterName, setPosterName] = useState("");
  const [confirmEmail, setConfirmEmail] = useState(""); // honeypot
  const [submitting, setSubmitting] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);
  const [retryAfter, setRetryAfter] = useState(0);
  const [postedBounty, setPostedBounty] = useState<Bounty | null>(null);

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const bs = await api.listBounties(filter);
        if (live) setBounties(bs);
      } catch (e: any) {
        if (live) setError(e?.message ?? "fetch failed");
      }
    }
    load();
    const t = setInterval(load, 4000);
    return () => { live = false; clearInterval(t); };
  }, [filter]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPostError(null);
    setRetryAfter(0);
    setSubmitting(true);
    try {
      const created = await api.postSpectatorBounty({
        target_name: target.trim(),
        gold: Number(gold),
        reason: reason.trim() || undefined,
        poster_name: posterName.trim() || undefined,
        confirm_email: confirmEmail, // honeypot — always sent, only filled by bots
      });
      setPostedBounty(created);
      setTarget("");
      setGold("25");
      setReason("");
      setFilter("open");  // ensure newly-posted bounty is visible in the list
      setTimeout(() => setPostedBounty(null), 8000);
    } catch (e: any) {
      const msg = String(e?.message ?? "post failed");
      setPostError(msg);
      const ra = (e as any)?.retryAfter;
      if (typeof ra === "number") setRetryAfter(ra);
    } finally {
      setSubmitting(false);
    }
  }

  // Tick the retryAfter countdown so users see when they can post again.
  useEffect(() => {
    if (retryAfter <= 0) return;
    const t = setInterval(() => setRetryAfter((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [retryAfter]);

  if (error) {
    return <div className="text-rose-400 text-sm">Failed: {error}</div>;
  }

  return (
    <div className="space-y-6">
      <section>
        <Link href="/" className="text-xs text-fg-muted hover:text-amber-dim">← world</Link>
        <h1 className="text-3xl mt-2 mb-2">Bounty Board</h1>
        <p className="text-fg-muted text-sm max-w-2xl">
          Public hits. The poster pays gold up front; the next hero who lands
          the killing blow on the target collects the prize. The world settles
          its grudges in coin.
        </p>
      </section>

      {/* Spectator bounty form — no auth, capped at 100g, rate-limited per IP */}
      <form
        onSubmit={submit}
        className="border border-amber-dim/40 bg-bg-card px-4 py-3 grid gap-3 sm:grid-cols-[1fr_120px_auto] items-end"
      >
        {/* Honeypot — visually hidden, real users skip it. Bots crawl every
            input and fill them in, which signals a bot to the server. */}
        <input
          type="text"
          name="confirm_email"
          tabIndex={-1}
          autoComplete="off"
          aria-hidden="true"
          value={confirmEmail}
          onChange={(e) => setConfirmEmail(e.target.value)}
          style={{ position: "absolute", left: "-9999px", width: 1, height: 1, opacity: 0 }}
        />

        <div className="sm:col-span-3 text-xs text-fg-muted">
          Post a hit as a spectator. Gold materialises from the void (sandbox mode).
          Capped at 100g · 3 bounties per hour per IP.
        </div>
        <label className="text-xs">
          <span className="block text-fg-muted uppercase tracking-wider mb-1">target hero name</span>
          <input
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            required
            minLength={2}
            className="w-full bg-bg border border-border px-2 py-1.5 text-sm"
            placeholder="Tova Forgemaster"
          />
        </label>
        <label className="text-xs">
          <span className="block text-fg-muted uppercase tracking-wider mb-1">gold (10–100)</span>
          <input
            type="number"
            min={10}
            max={100}
            value={gold}
            onChange={(e) => setGold(e.target.value)}
            className="w-full bg-bg border border-border px-2 py-1.5 text-sm font-mono"
          />
        </label>
        <button
          type="submit"
          disabled={submitting || retryAfter > 0 || target.trim().length < 2}
          className="h-[34px] border border-amber bg-amber-dim/10 text-amber px-4 text-sm hover:bg-amber-dim/20 disabled:opacity-50 whitespace-nowrap"
        >
          {submitting
            ? "posting…"
            : retryAfter > 0
              ? `wait ${formatRetry(retryAfter)}`
              : "post bounty"}
        </button>
        <label className="text-xs sm:col-span-2">
          <span className="block text-fg-muted uppercase tracking-wider mb-1">reason (optional, public)</span>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={280}
            className="w-full bg-bg border border-border px-2 py-1.5 text-sm"
            placeholder="they took something of mine"
          />
        </label>
        <label className="text-xs">
          <span className="block text-fg-muted uppercase tracking-wider mb-1">poster name</span>
          <input
            value={posterName}
            onChange={(e) => setPosterName(e.target.value)}
            maxLength={80}
            className="w-full bg-bg border border-border px-2 py-1.5 text-sm"
            placeholder="anonymous"
          />
        </label>
        {postError && (
          <div className="sm:col-span-3 text-xs text-rose-400">
            {postError}
            {retryAfter > 0 && (
              <> · try again in <span className="font-mono">{formatRetry(retryAfter)}</span></>
            )}
          </div>
        )}
        {postedBounty && !postError && (
          <div className="sm:col-span-3 border border-emerald-700 bg-emerald-950/30 px-3 py-2 text-xs">
            Posted{" "}
            <span className="text-amber font-mono">{postedBounty.gold}g</span> on{" "}
            <Link
              href={`/h/${encodeURIComponent(postedBounty.target_name)}`}
              className="text-rose-300 hover:underline"
            >
              {postedBounty.target_name}
            </Link>
            . Whoever lands the killing blow collects.
          </div>
        )}
      </form>

      <div className="flex gap-2 text-xs">
        {(["open", "claimed", "all"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`border px-3 py-1 ${
              filter === f
                ? "border-amber bg-amber-dim/10 text-amber"
                : "border-border bg-bg-card text-fg-muted hover:border-amber-dim"
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {bounties.length === 0 ? (
        <p className="text-fg-muted italic text-sm">
          {filter === "open"
            ? "No open hits. The world is quiet — for now."
            : `No ${filter} bounties.`}
        </p>
      ) : (
        <div className="border border-border bg-bg-card divide-y divide-border">
          {bounties.map((b) => (
            <div key={b.id} className="px-4 py-3 text-sm">
              <div className="flex items-baseline justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Link
                      href={`/h/${encodeURIComponent(b.target_name)}`}
                      className="text-rose-300 hover:underline"
                    >
                      {b.target_name}
                    </Link>
                    <span className={`text-xs uppercase ${STATUS_COLOR[b.status]}`}>{b.status}</span>
                  </div>
                  {b.reason && <div className="text-xs text-fg-muted mt-0.5 italic">"{b.reason}"</div>}
                  <div className="text-xs text-fg-muted mt-0.5">
                    posted by{" "}
                    {b.poster_hero_id ? (
                      <Link href={`/heroes/${b.poster_hero_id}`} className="hover:text-amber-dim">
                        {b.poster_name}
                      </Link>
                    ) : (
                      <span>{b.poster_name}</span>
                    )}
                    {" · t"}{b.created_at_tick}
                  </div>
                </div>
                <span className="text-amber font-mono whitespace-nowrap">{b.gold}g</span>
              </div>
              {b.status === "claimed" && b.claimed_by_hero_id && (
                <div className="text-xs text-fg-muted mt-2">
                  claimed at t{b.claimed_at_tick} by{" "}
                  <Link href={`/heroes/${b.claimed_by_hero_id}`} className="text-emerald-400 hover:underline">
                    a killer
                  </Link>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
