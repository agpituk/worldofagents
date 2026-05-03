"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api, Hero, JournalEntry, Longevity, MemoryTrace, Quest } from "@/lib/api";
import { formatLifespan } from "@/lib/format";
import { useZoneStream } from "@/lib/use-zone-stream";
import ToolListPanel from "@/components/inspector/ToolListPanel";
import ActivityFeed from "./components/ActivityFeed";
import MemoryTracePanel from "./components/MemoryTracePanel";
import JournalPanel from "./components/JournalPanel";
import CraftViewer from "./components/CraftViewer";

export default function HeroPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [hero, setHero] = useState<Hero | null>(null);
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [quests, setQuests] = useState<Quest[]>([]);
  const [longevity, setLongevity] = useState<Longevity | null>(null);
  const [memoryTrace, setMemoryTrace] = useState<MemoryTrace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const { events, status } = useZoneStream(hero?.zone, 300, true);

  useEffect(() => {
    let live = true;
    async function load() {
      try {
        const [h, j, q, lg, mt] = await Promise.all([
          api.getHero(id),
          api.getJournal(id, 50),
          api.getQuests(id),
          api.longevity(1),
          api.getMemoryTrace(id),
        ]);
        if (live) {
          setHero(h);
          setJournal(j);
          setQuests(q);
          setLongevity(lg);
          setMemoryTrace(mt);
        }
      } catch (e: any) {
        if (live) setError(e?.message ?? "fetch failed");
      }
    }
    load();
    const t = setInterval(load, 4000);
    return () => { live = false; clearInterval(t); };
  }, [id]);

  function copyShareUrl() {
    if (!hero) return;
    const url = `${window.location.origin}/h/${encodeURIComponent(hero.name)}`;
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  }

  const heroFirstName = hero?.name.toLowerCase().split(" ")[0] || "";
  const heroLines = events.filter(
    (e) =>
      (e.kind === "narrator" && heroFirstName && (e.data?.text ?? "").toLowerCase().includes(heroFirstName)) ||
      (e.kind === "tick" && e.data?.hero_id === id),
  );
  const parseFailureCount = heroLines.filter(
    (e) => e.kind === "tick" && e.data?.kind === "parse_failure",
  ).length;

  if (error) {
    return (
      <div className="border border-rose-800 bg-rose-950/40 px-4 py-3 text-sm">
        Hero not found: <code>{id}</code>
      </div>
    );
  }

  if (!hero) return <div className="text-fg-muted">loading…</div>;

  const isDead = hero.status === "dead";
  const manifest = (hero.manifest || {}) as Record<string, any>;
  const memoryInit = manifest.memory?.initial || manifest.extras?.memory?.initial || {};
  const earnedTitle = journal
    .filter((j) => j.tags.includes("title_earned"))
    .map((j) => j.text.replace(/^You are now known as: /, "").replace(/\.$/, ""))
    .at(-1);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[2fr_3fr] gap-8">
      <aside>
        <Link href="/" className="text-xs text-fg-muted">← world</Link>
        <h1 className={`text-3xl mt-2 ${isDead ? "text-rose-400 line-through" : ""}`}>
          {hero.name}
        </h1>
        {hero.top_title && (
          <div className="mt-1 text-sm text-amber font-semibold">{hero.top_title}</div>
        )}
        {earnedTitle && (
          <div className="mt-1 text-sm text-amber italic">{earnedTitle}</div>
        )}
        {isDead && (
          <Link
            href={`/heroes/${hero.id}/death`}
            className="mt-2 inline-block text-xs uppercase tracking-wider text-rose-400 hover:text-rose-300"
          >
            view monument →
          </Link>
        )}
        <div className="mt-1 text-xs uppercase">
          <span className="text-amber">{hero.division}</span>
          <span className={`ml-2 ${isDead ? "text-rose-400" : "text-emerald-400"}`}>{hero.status}</span>
        </div>

        {longevity && hero.born_at_tick !== undefined && (
          <div className="mt-4 border border-border bg-bg-card px-4 py-3">
            <div className="text-[10px] uppercase tracking-wider text-fg-muted">
              {isDead ? "lived for" : "alive for"}
            </div>
            <div className={`text-2xl font-display ${isDead ? "text-rose-400" : "text-emerald-400"}`}>
              {formatLifespan(
                (isDead && hero.died_at_tick != null
                  ? hero.died_at_tick
                  : longevity.current_tick) - (hero.born_at_tick ?? 0),
              )}
            </div>
            <div className="mt-1 text-[10px] text-fg-muted font-mono">
              t{hero.born_at_tick} → {hero.died_at_tick != null ? `t${hero.died_at_tick}` : `t${longevity.current_tick}`}
            </div>
          </div>
        )}

        <p className="text-sm mt-3 text-fg/80 leading-relaxed">{hero.bio}</p>
        <p className="text-xs text-fg-muted mt-2">
          author <span className="text-fg">{hero.author}</span>
        </p>

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            onClick={copyShareUrl}
            className="text-xs text-amber-dim hover:text-amber border border-border bg-bg-card px-3 py-1"
          >
            {copied ? "copied!" : `share /h/${hero.name}`}
          </button>
          <Link
            href={`/deploy?fork=${hero.id}`}
            className="text-xs text-emerald-400 hover:text-emerald-300 border border-border bg-bg-card px-3 py-1"
          >
            fork this hero
          </Link>
        </div>

        <div className="mt-6 grid grid-cols-3 gap-2 text-center">
          {Object.entries(hero.build).map(([k, v]) => (
            <div key={k} className="border border-border bg-bg-card py-2">
              <div className="text-xs uppercase text-fg-muted">{k}</div>
              <div className="text-xl font-display text-amber">{v}</div>
            </div>
          ))}
        </div>

        <div className="mt-6 space-y-1 text-sm">
          <div>HP <span className={isDead ? "text-rose-400" : "text-amber"}>{hero.hp}</span></div>
          {hero.mana_max !== undefined && hero.mana_max > 0 && (
            <div>
              Mana{" "}
              <span className="text-blue-300">
                {hero.mana_current ?? 0}/{hero.mana_max}
              </span>
            </div>
          )}
          <div>Zone <Link href={`/zones/${hero.zone}`}>{hero.zone.replace(/_/g, " ")}</Link></div>
          <div>Position <span className="font-mono text-fg-muted">[{hero.pos[0]},{hero.pos[1]}]</span></div>
          {memoryInit.gold !== undefined && (
            <div>Gold <span className="text-amber">{memoryInit.gold}</span></div>
          )}
        </div>

        {hero.known_spells && hero.known_spells.length > 0 && (
          <div className="mt-6">
            <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">spells known</h2>
            <ul className="text-sm space-y-1">
              {hero.known_spells.map((s) => (
                <li key={s} className="text-blue-300">✦ {s.replace(/_/g, " ")}</li>
              ))}
            </ul>
          </div>
        )}

        {hero.equipped && Object.values(hero.equipped).some(Boolean) && (
          <div className="mt-6">
            <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">equipped</h2>
            <ul className="text-sm space-y-1">
              {Object.entries(hero.equipped).map(([slot, slug]) =>
                slug ? (
                  <li key={slot}>
                    <span className="text-fg-muted uppercase text-xs mr-2">{slot}</span>
                    <span className="text-amber">{slug.replace(/_/g, " ")}</span>
                  </li>
                ) : null,
              )}
            </ul>
          </div>
        )}

        {hero.skill_levels && Object.keys(hero.skill_levels).length > 0 && (
          <div className="mt-6">
            <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">skills</h2>
            <ul className="text-sm space-y-1">
              {Object.entries(hero.skill_levels).map(([name, lvl]) => {
                const rank = hero.skill_titles?.[name];
                return (
                  <li key={name} className="flex justify-between">
                    <span className="capitalize">
                      {name}
                      {rank && (
                        <span className="ml-2 text-[10px] uppercase tracking-wider text-amber/80">
                          {rank}
                        </span>
                      )}
                    </span>
                    <span className="text-amber font-mono">
                      lvl {lvl} <span className="text-fg-muted text-xs">({hero.skills?.[name] ?? 0} xp)</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {hero.reputation && (hero.reputation.kills ?? 0) + (hero.reputation.pvp_kills ?? 0) > 0 && (
          <div className="mt-6">
            <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">reputation</h2>
            <ul className="text-sm space-y-1">
              <li className="flex justify-between">
                <span>kills</span>
                <span className="text-amber font-mono">{hero.reputation.kills ?? 0}</span>
              </li>
              {(hero.reputation.pvp_kills ?? 0) > 0 && (
                <li className="flex justify-between">
                  <span>pvp kills</span>
                  <span className="text-rose-400 font-mono">{hero.reputation.pvp_kills}</span>
                </li>
              )}
            </ul>
          </div>
        )}

        {quests.length > 0 && (
          <div className="mt-6">
            <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">quests</h2>
            <ul className="text-sm space-y-2">
              {quests.map((q) => {
                const pct = Math.min(100, Math.round((q.count_done / q.count_required) * 100));
                const statusColour =
                  q.status === "claimed" ? "text-fg-muted line-through"
                  : q.status === "done" ? "text-emerald-400"
                  : "text-amber";
                return (
                  <li key={q.id} className="border-l-2 border-amber-dim pl-3">
                    <div className={statusColour}>{q.name}</div>
                    <div className="text-xs text-fg-muted">
                      {q.count_done}/{q.count_required} {q.kind.replace(/_/g, " ")} · {q.status}
                      {q.status === "active" && ` · ${pct}%`}
                    </div>
                    <div className="text-xs text-fg-muted">
                      from <span className="text-fg">{q.offered_by}</span>
                      {" · "}reward {q.reward_gold}g
                      {q.reward_faction && ` · +${q.reward_faction_amount} ${q.reward_faction}`}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {hero.faction_rep && Object.keys(hero.faction_rep).length > 0 && (
          <div className="mt-6">
            <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">factions</h2>
            <ul className="text-sm space-y-1">
              {Object.entries(hero.faction_rep).map(([f, r]) => (
                <li key={f} className="flex justify-between">
                  <span className="capitalize">{f}</span>
                  <span className={`font-mono ${r! > 0 ? "text-emerald-400" : r! < 0 ? "text-rose-400" : "text-fg-muted"}`}>
                    {r! > 0 ? "+" : ""}{r}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {memoryTrace && <MemoryTracePanel trace={memoryTrace} />}
        <JournalPanel entries={journal} />
        <CraftViewer hero={hero} />
        <div className="mt-6">
          <ToolListPanel heroId={id} />
        </div>
      </aside>

      <ActivityFeed
        heroId={id}
        events={heroLines}
        status={status}
        parseFailureCount={parseFailureCount}
      />
    </div>
  );
}
