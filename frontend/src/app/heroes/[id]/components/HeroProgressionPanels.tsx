"use client";

// Sidebar progression panels for the hero page — spells, equipped,
// skills, reputation, quests, factions. Each section is conditional on
// having content; together they keep `page.tsx` under the 300-line cap
// without changing visible behaviour.

import type { Hero, Quest } from "@/lib/api";

type Props = {
  hero: Hero;
  quests: Quest[];
};

export default function HeroProgressionPanels({ hero, quests }: Props) {
  return (
    <>
      <SpellsPanel spells={hero.known_spells} />
      <EquippedPanel equipped={hero.equipped} />
      <SkillsPanel
        skillLevels={hero.skill_levels}
        skills={hero.skills}
        skillTitles={hero.skill_titles}
      />
      <ReputationPanel reputation={hero.reputation} />
      <QuestsPanel quests={quests} />
      <FactionsPanel factionRep={hero.faction_rep} />
    </>
  );
}

function SpellsPanel({ spells }: { spells?: string[] }) {
  if (!spells || spells.length === 0) return null;
  return (
    <div className="mt-6">
      <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">spells known</h2>
      <ul className="text-sm space-y-1">
        {spells.map((s) => (
          <li key={s} className="text-blue-300">✦ {s.replace(/_/g, " ")}</li>
        ))}
      </ul>
    </div>
  );
}

function EquippedPanel({ equipped }: { equipped?: Record<string, string | null> }) {
  if (!equipped || !Object.values(equipped).some(Boolean)) return null;
  return (
    <div className="mt-6">
      <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">equipped</h2>
      <ul className="text-sm space-y-1">
        {Object.entries(equipped).map(([slot, slug]) =>
          slug ? (
            <li key={slot}>
              <span className="text-fg-muted uppercase text-xs mr-2">{slot}</span>
              <span className="text-amber">{slug.replace(/_/g, " ")}</span>
            </li>
          ) : null,
        )}
      </ul>
    </div>
  );
}

function SkillsPanel({
  skillLevels,
  skills,
  skillTitles,
}: {
  skillLevels?: Record<string, number>;
  skills?: Record<string, number>;
  skillTitles?: Record<string, string>;
}) {
  if (!skillLevels || Object.keys(skillLevels).length === 0) return null;
  return (
    <div className="mt-6">
      <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">skills</h2>
      <ul className="text-sm space-y-1">
        {Object.entries(skillLevels).map(([name, lvl]) => {
          const rank = skillTitles?.[name];
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
                lvl {lvl}{" "}
                <span className="text-fg-muted text-xs">
                  ({skills?.[name] ?? 0} xp)
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ReputationPanel({
  reputation,
}: {
  reputation?: { kills?: number; pvp_kills?: number; dead?: boolean };
}) {
  if (!reputation) return null;
  if ((reputation.kills ?? 0) + (reputation.pvp_kills ?? 0) === 0) return null;
  return (
    <div className="mt-6">
      <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">reputation</h2>
      <ul className="text-sm space-y-1">
        <li className="flex justify-between">
          <span>kills</span>
          <span className="text-amber font-mono">{reputation.kills ?? 0}</span>
        </li>
        {(reputation.pvp_kills ?? 0) > 0 && (
          <li className="flex justify-between">
            <span>pvp kills</span>
            <span className="text-rose-400 font-mono">{reputation.pvp_kills}</span>
          </li>
        )}
      </ul>
    </div>
  );
}

function QuestsPanel({ quests }: { quests: Quest[] }) {
  if (quests.length === 0) return null;
  return (
    <div className="mt-6">
      <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">quests</h2>
      <ul className="text-sm space-y-2">
        {quests.map((q) => {
          const pct = Math.min(100, Math.round((q.count_done / q.count_required) * 100));
          const statusColour =
            q.status === "claimed"
              ? "text-fg-muted line-through"
              : q.status === "done"
              ? "text-emerald-400"
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
  );
}

function FactionsPanel({ factionRep }: { factionRep?: Record<string, number> }) {
  if (!factionRep || Object.keys(factionRep).length === 0) return null;
  return (
    <div className="mt-6">
      <h2 className="text-xs uppercase tracking-wider text-fg-muted mb-2">factions</h2>
      <ul className="text-sm space-y-1">
        {Object.entries(factionRep).map(([f, r]) => (
          <li key={f} className="flex justify-between">
            <span className="capitalize">{f}</span>
            <span
              className={`font-mono ${
                r! > 0 ? "text-emerald-400" : r! < 0 ? "text-rose-400" : "text-fg-muted"
              }`}
            >
              {r! > 0 ? "+" : ""}
              {r}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
