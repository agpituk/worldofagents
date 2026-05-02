"use client";

import Link from "next/link";
import { use, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import yaml from "js-yaml";
import { api, Hero, JournalEntry, Longevity, MemoryTrace, Quest } from "@/lib/api";
import { formatLifespan } from "@/lib/format";
import { useZoneStream } from "@/lib/use-zone-stream";
import ToolListPanel from "@/components/inspector/ToolListPanel";

// Lazy-load Blockly here too — keeps hero pages light when the user
// hasn't expanded the blocks panel.
const HeroBlocksRO = dynamic(() => import("@/components/HeroBlocksRO"), { ssr: false });

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
  const feedRef = useRef<HTMLOListElement | null>(null);

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

  // P0-3 step 3 surface: "your model emitted invalid JSON N times" —
  // a running tally of parse failures lets a player notice immediately
  // when their manifest+model combo is fragile, without having to scan
  // the feed for individual rows.
  const parseFailureCount = heroLines.filter(
    (e) => e.kind === "tick" && e.data?.kind === "parse_failure",
  ).length;

  useEffect(() => {
    const el = feedRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [heroLines.length]);

  if (error) {
    return (
      <div className="border border-rose-800 bg-rose-950/40 px-4 py-3 text-sm">
        Hero not found: <code>{id}</code>
      </div>
    );
  }

  if (!hero) return <div className="text-fg-muted">loading…</div>;

  const isDead = hero.status === "dead";
  if (isDead) {
    // Heroes who've died get the monument route. Soft redirect via Link banner;
    // we don't auto-push so spectators can still inspect the live state.
  }

  // Pull a few public manifest sections to show. The server already strips
  // `system` (the player's actual prompt) before sending.
  const manifest = (hero.manifest || {}) as Record<string, any>;
  const reflexes = manifest.reflexes || manifest.extras?.reflexes || [];
  const abilities = manifest.abilities || manifest.extras?.abilities || {};
  const memoryInit = manifest.memory?.initial || manifest.extras?.memory?.initial || {};

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[2fr_3fr] gap-8">
      <aside>
        <Link href="/" className="text-xs text-fg-muted">← world</Link>
        <h1 className={`text-3xl mt-2 ${isDead ? "text-rose-400 line-through" : ""}`}>
          {hero.name}
        </h1>
        {/* Phase 5 — derived skill identity (GM Fisherman, Expert Smith). */}
        {hero.top_title && (
          <div className="mt-1 text-sm text-amber font-semibold">{hero.top_title}</div>
        )}
        {(() => {
          const title = (hero as any)?.manifest?.memory?.initial?.title; // never set here
          // Pull title from server-side `memory` (live, not manifest). The
          // public Hero schema doesn't expose memory directly today; we surface
          // titles via journal entries tagged `title_earned` instead. Render
          // the most recent one if present.
          const earned = journal
            .filter((j) => j.tags.includes("title_earned"))
            .map((j) => j.text.replace(/^You are now known as: /, "").replace(/\.$/, ""));
          const latest = earned[earned.length - 1] || title;
          return latest ? (
            <div className="mt-1 text-sm text-amber italic">{latest}</div>
          ) : null;
        })()}
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
          <span className={`ml-2 ${isDead ? "text-rose-400" : "text-emerald-400"}`}>
            {hero.status}
          </span>
        </div>

        {/* Lifespan card — the headline metric. Stays counting if alive, frozen if dead. */}
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
                <li key={s} className="text-blue-300">
                  ✦ {s.replace(/_/g, " ")}
                </li>
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

        {/* Phase 5 — public reputation. Only render when at least one
            counter is non-zero so brand-new heroes don't see a noisy block. */}
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

        {memoryTrace && (memoryTrace.recall_tags.length > 0 || memoryTrace.system_summary || memoryTrace.journal_relevant.length > 0) && (
          <details className="mt-6" open>
            <summary className="text-xs uppercase tracking-wider text-fg-muted cursor-pointer hover:text-amber">
              memory trace
              <span className="ml-2 text-fg-muted normal-case font-mono">
                via {memoryTrace.retriever_name}
              </span>
            </summary>
            <div className="mt-3 space-y-3 text-sm">
              {memoryTrace.system_summary && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">always-on</div>
                  <p className="text-fg/80 italic whitespace-pre-line text-xs leading-relaxed border-l-2 border-amber-dim/40 pl-3">
                    {memoryTrace.system_summary}
                  </p>
                </div>
              )}
              {memoryTrace.recall_tags.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">recall tags</div>
                  <div className="flex flex-wrap gap-1">
                    {memoryTrace.recall_tags.map((t) => (
                      <span key={t} className="text-xs px-2 py-0.5 bg-amber-dim/10 border border-amber-dim/40 text-amber-dim">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {memoryTrace.journal_relevant.length > 0 ? (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">
                    pulled this tick ({memoryTrace.journal_relevant.length})
                  </div>
                  <ol className="space-y-1.5">
                    {memoryTrace.journal_relevant.map((m, i) => (
                      <li key={i} className="border-l-2 border-blue-700 pl-3 text-xs">
                        <div className="text-fg-muted font-mono">
                          {m.tick_id != null ? `t${m.tick_id}` : "—"} · {m.kind}
                          {m.tags.length > 0 && (
                            <span className="ml-2">{m.tags.slice(0, 4).join(" · ")}</span>
                          )}
                        </div>
                        <div className="text-fg/85">{m.text}</div>
                      </li>
                    ))}
                  </ol>
                </div>
              ) : memoryTrace.recall_tags.length > 0 ? (
                <p className="text-xs text-fg-muted italic">
                  Tags declared, but the retriever found nothing matching yet.
                </p>
              ) : null}
              {memoryTrace.titles.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">titles earned</div>
                  <div className="flex flex-wrap gap-1">
                    {memoryTrace.titles.map((t) => (
                      <span key={t} className="text-xs px-2 py-0.5 bg-amber/10 border border-amber/40 text-amber">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {memoryTrace.discovered_recipes.length > 0 && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-fg-muted mb-1">recipes discovered</div>
                  <ul className="text-xs space-y-0.5">
                    {memoryTrace.discovered_recipes.map((r) => (
                      <li key={r} className="text-amber-dim">✦ {r}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </details>
        )}

        {journal.length > 0 && (
          <details className="mt-6" open>
            <summary className="text-xs uppercase tracking-wider text-fg-muted cursor-pointer hover:text-amber">
              journal ({journal.length})
            </summary>
            <ol className="mt-2 space-y-2 max-h-[40vh] overflow-y-auto pr-2">
              {journal.map((j) => (
                <li
                  key={j.id}
                  className={`text-sm leading-relaxed border-l-2 pl-3 ${
                    j.kind === "milestone" ? "border-amber-dim" : "border-blue-700"
                  }`}
                >
                  <div className="text-xs text-amber-dim font-mono mb-0.5">
                    t{j.tick_id} · {j.kind}
                    {j.tags.length > 0 && (
                      <span className="text-fg-muted ml-2">{j.tags.join(" · ")}</span>
                    )}
                  </div>
                  <div className={j.kind === "player" ? "italic text-fg" : "text-fg/85"}>
                    {j.text}
                  </div>
                </li>
              ))}
            </ol>
          </details>
        )}

        {/* Public manifest viewer — the player's craft, sans system prompt. */}
        <details className="mt-8 group" open>
          <summary className="text-xs uppercase tracking-wider text-fg-muted cursor-pointer hover:text-amber">
            craft · reflexes ({Array.isArray(reflexes) ? reflexes.length : 0})
            {Object.keys(abilities).length > 0 && ` · abilities (${Object.keys(abilities).length})`}
          </summary>
          {Array.isArray(reflexes) && reflexes.length > 0 && (
            <div className="mt-3 space-y-2">
              {reflexes.map((r: any, i: number) => (
                <div key={i} className="border-l-2 border-amber-dim pl-3 text-xs">
                  <div className="text-amber-dim font-mono">when {r.when}</div>
                  <div className="text-fg-muted">→ {JSON.stringify(r.then)}</div>
                </div>
              ))}
            </div>
          )}
          {Object.keys(abilities).length > 0 && (
            <div className="mt-4">
              <div className="text-xs uppercase text-fg-muted mb-1">abilities</div>
              <ul className="text-xs">
                {Object.entries(abilities).map(([name, spec]: [string, any]) => (
                  <li key={name} className="mb-1">
                    <span className="text-amber">{name}</span>
                    <span className="text-fg-muted ml-2">{spec.description ?? "—"}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </details>

        {/* Read-only block render — shows reflexes/abilities/tools as
            Blockly blocks, lazy-loaded so the hero page stays light. */}
        {hero?.manifest && (
          <details className="mt-6 group">
            <summary className="text-xs uppercase tracking-wider text-fg-muted cursor-pointer hover:text-amber">
              blocks (visual)
            </summary>
            <div className="mt-3">
              <HeroBlocksRO
                yaml={yaml.dump({ hero: hero.manifest })}
                height={420}
              />
            </div>
          </details>
        )}

        {/* Inspector — Phase 5. Shows the hero's user-defined tools with
            stats and a per-tick "why didn't my tool fire?" deep-link. */}
        <div className="mt-6">
          <ToolListPanel heroId={id} />
        </div>
      </aside>

      <section className="border-l border-border pl-6 min-h-[60vh]">
        <div className="flex items-baseline justify-between mb-3">
          <h2 className="text-sm uppercase tracking-wider text-fg-muted">recent activity</h2>
          <div className="flex items-center gap-3">
            {parseFailureCount > 0 && (
              <span
                className="text-xs text-rose-400 font-mono"
                title="LLM output that didn't parse cleanly. Click an entry below for the raw output."
              >
                ⚠ {parseFailureCount} parse {parseFailureCount === 1 ? "failure" : "failures"}
              </span>
            )}
            <span className={`text-xs ${status === "open" ? "text-emerald-400" : status === "connecting" ? "text-amber" : "text-rose-400"}`}>● {status}</span>
          </div>
        </div>
        {heroLines.length === 0 ? (
          <p className="text-sm text-fg-muted italic">
            Idle. Activity will appear here as the hero acts.
          </p>
        ) : (
          <ol
            ref={feedRef}
            className="space-y-2 max-h-[75vh] overflow-y-auto pr-2"
          >
            {heroLines.map((e, i) => {
              const debug = e.data?.payload?.debug;
              const isParseFailure =
                e.kind === "tick" && e.data?.kind === "parse_failure";
              return (
                <li
                  key={`${e.ts}-${i}`}
                  className={`text-sm leading-relaxed ${
                    isParseFailure
                      ? "border-l-2 border-rose-500 pl-2 -ml-2"
                      : ""
                  }`}
                >
                  <span className="text-xs text-amber-dim mr-2 font-mono">t{e.data?.tick_id}</span>
                  {e.kind === "narrator" ? (
                    <span>{e.data?.text}</span>
                  ) : isParseFailure ? (
                    <span>
                      <span className="text-rose-400 font-medium">parse failure</span>
                      <span className="text-fg-muted"> · {e.data?.payload?.reason ?? "unknown"}</span>
                      {e.data?.payload?.error && (
                        <span className="text-fg-muted"> · {String(e.data.payload.error)}</span>
                      )}
                      {e.data?.payload?.raw_output && (
                        <details className="mt-1 ml-6 text-xs font-mono text-rose-300/70">
                          <summary className="cursor-pointer text-rose-400/80 hover:text-rose-300">
                            raw output
                          </summary>
                          <pre className="mt-1 whitespace-pre-wrap break-all">
                            {String(e.data.payload.raw_output).slice(0, 500)}
                          </pre>
                        </details>
                      )}
                    </span>
                  ) : (
                    <span className="text-fg-muted">
                      {e.data?.kind} · {JSON.stringify(e.data?.payload?.outcome ?? e.data?.payload).slice(0, 100)}
                    </span>
                  )}
                  {debug && !isParseFailure && (
                    <div className="mt-1 ml-6 text-xs font-mono text-amber-dim">
                      ↪ reflex #{debug.reflex_index}
                      {debug.when && (
                        <span className="text-fg-muted"> · when {String(debug.when)}</span>
                      )}
                      {debug.via === "invoke_llm" && (
                        <span className="text-amber"> · invoke_llm</span>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </section>
    </div>
  );
}
