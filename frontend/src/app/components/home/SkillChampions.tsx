"use client";

import Link from "next/link";
import { SkillLeaderboards } from "@/lib/api";

export default function SkillChampions({ skillBoards }: { skillBoards: SkillLeaderboards | null }) {
  if (!skillBoards) return null;
  const populated = Object.entries(skillBoards.boards).filter(
    ([, rows]) => rows.length > 0,
  );
  if (populated.length === 0) return null;
  return (
    <section>
      <h2 className="text-sm uppercase tracking-wider text-fg-muted mb-3">
        skill champions · top {skillBoards.top} by xp
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {populated.map(([skillName, rows]) => (
          <div key={skillName} className="border border-border bg-bg-card">
            <div className="px-3 py-2 border-b border-border text-xs uppercase tracking-wider text-amber">
              {skillName.replace(/_/g, " ")}
            </div>
            <ol className="divide-y divide-border">
              {rows.map((r, i) => (
                <li key={r.id}>
                  <Link
                    href={`/heroes/${r.id}`}
                    className="flex items-center justify-between px-3 py-1.5 text-xs hover:bg-amber-dim/5"
                  >
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-fg-muted font-mono w-4 text-right">{i + 1}.</span>
                      <span className={`truncate ${r.status === "dead" ? "text-rose-300 line-through" : ""}`}>
                        {r.name}
                      </span>
                      {r.rank && (
                        <span className="text-[9px] uppercase tracking-wider text-amber/70">
                          {r.rank}
                        </span>
                      )}
                    </div>
                    <span className="text-amber font-mono">lvl {r.level}</span>
                  </Link>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </section>
  );
}
