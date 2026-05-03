"use client";

import { ARCHETYPES, type Archetype } from "../templates/templates";

const STAT_KEYS = ["str", "dex", "con", "int", "wis", "cha"] as const;

function StatSparkline({ build }: { build: Archetype["build"] }) {
  return (
    <div className="flex items-end gap-0.5 h-8" aria-hidden>
      {STAT_KEYS.map((k) => {
        const v = build[k];
        const pct = Math.max(0, Math.min(100, ((v - 5) / 20) * 100));
        return (
          <div
            key={k}
            className="w-2 bg-amber-dim/60"
            style={{ height: `${pct}%` }}
            title={`${k.toUpperCase()} ${v}`}
          />
        );
      })}
    </div>
  );
}

function intensityColor(level: Archetype["llmIntensity"]): string {
  switch (level) {
    case "low":
      return "text-emerald-400 border-emerald-700/40";
    case "medium":
      return "text-amber border-amber-700/40";
    case "high":
      return "text-rose-300 border-rose-700/40";
  }
}

type Props = {
  onSelect: (archetype: Archetype) => void;
  layout?: "grid" | "row";
};

export default function TemplatePicker({ onSelect, layout = "grid" }: Props) {
  const containerCls =
    layout === "row"
      ? "flex gap-3 overflow-x-auto"
      : "grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3";

  return (
    <div className={containerCls}>
      {ARCHETYPES.map((a) => (
        <button
          key={a.key}
          onClick={() => onSelect(a)}
          className="text-left border border-border bg-bg-card hover:border-amber-dim hover:bg-bg-card/80 p-3 transition-colors min-w-[14rem]"
          data-testid={`template-card-${a.key}`}
        >
          <div className="flex items-baseline justify-between mb-1">
            <h4 className="text-sm font-display text-amber">{a.name}</h4>
            <span
              className={`text-[10px] uppercase tracking-wider border px-1.5 py-0.5 ${intensityColor(
                a.llmIntensity,
              )}`}
            >
              llm {a.llmIntensity}
            </span>
          </div>
          <p className="text-xs text-fg/80 leading-snug min-h-[2.5rem]">
            {a.pitch}
          </p>
          <div className="mt-2 flex items-center gap-2">
            <StatSparkline build={a.build} />
            <span className="text-[10px] font-mono text-fg-muted">
              {STAT_KEYS.map((k) => a.build[k]).join("/")}
            </span>
          </div>
        </button>
      ))}
    </div>
  );
}
