"use client";

import { useMemo } from "react";
import yaml from "js-yaml";

const STATS = ["str", "dex", "con", "int", "wis", "cha"] as const;
type Stat = (typeof STATS)[number];

const STAT_INFO: Record<Stat, { label: string; effect: string }> = {
  str: { label: "STR", effect: "Melee damage and weight you can carry." },
  dex: { label: "DEX", effect: "Initiative, ranged accuracy, stealth." },
  con: { label: "CON", effect: "HP pool and status resistance." },
  int: { label: "INT", effect: "Tokens-per-thinking-tick budget." },
  wis: { label: "WIS", effect: "Memory KV size + perception radius." },
  cha: { label: "CHA", effect: "Trade and social outcomes." },
};

const MIN = 5;
const MAX = 25;
const TOTAL = 100;

export type Build = Record<Stat, number>;

export function parseBuild(yamlText: string): Build | null {
  try {
    const doc: any = yaml.load(yamlText);
    if (!doc || typeof doc !== "object") return null;
    const inner =
      doc.hero && typeof doc.hero === "object" ? doc.hero : doc;
    const build = inner?.build;
    if (!build || typeof build !== "object") return null;
    const out: Partial<Build> = {};
    for (const k of STATS) {
      const v = build[k];
      if (typeof v !== "number" || !Number.isFinite(v)) return null;
      out[k] = v;
    }
    return out as Build;
  } catch {
    return null;
  }
}

// Surgical line-level edit: keeps comments, indentation, and any other
// formatting in the YAML intact. We only touch the matched key's number.
export function setStatInYaml(
  yamlText: string,
  stat: Stat,
  value: number,
): string {
  const re = new RegExp(`^(\\s+)${stat}\\s*:\\s*-?\\d+`, "m");
  if (!re.test(yamlText)) return yamlText;
  return yamlText.replace(re, `$1${stat}: ${value}`);
}

type Props = {
  value: string;
  onChange: (next: string) => void;
};

export default function BuildPanel({ value, onChange }: Props) {
  const build = useMemo(() => parseBuild(value), [value]);

  if (!build) {
    return (
      <div className="border border-border bg-bg-card p-4 text-xs text-fg-muted">
        stats unavailable while YAML is invalid
      </div>
    );
  }

  const total = STATS.reduce((s, k) => s + build[k], 0);
  const remaining = TOTAL - total;
  const tone =
    total > TOTAL
      ? "text-rose-400"
      : total === TOTAL
      ? "text-amber"
      : "text-emerald-400";

  function update(stat: Stat, raw: number) {
    const clamped = Math.max(MIN, Math.min(MAX, Math.round(raw)));
    onChange(setStatInYaml(value, stat, clamped));
  }

  return (
    <div className="border border-border bg-bg-card p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="text-xs uppercase tracking-wider text-fg-muted">
          stat allocation
        </h3>
        <div
          className={`text-sm font-mono ${tone}`}
          aria-live="polite"
          data-testid="points-remaining"
        >
          {total}/{TOTAL}{" "}
          {remaining < 0
            ? `(over by ${-remaining})`
            : remaining === 0
            ? "(maxed)"
            : `(${remaining} left)`}
        </div>
      </div>
      <div className="space-y-2">
        {STATS.map((stat) => {
          const v = build[stat];
          const out = v < MIN || v > MAX;
          return (
            <div
              key={stat}
              className="grid grid-cols-[2.5rem_4rem_1fr] lg:grid-cols-[2.5rem_4rem_1fr_minmax(10rem,18rem)] gap-3 items-center"
            >
              <div className="text-sm font-display text-amber">
                {STAT_INFO[stat].label}
              </div>
              <input
                type="number"
                min={MIN}
                max={MAX}
                value={v}
                onChange={(e) => update(stat, Number(e.target.value))}
                className={`bg-bg border ${
                  out ? "border-rose-500" : "border-border"
                } px-2 py-1 text-sm font-mono w-16`}
                aria-label={`${STAT_INFO[stat].label} value`}
              />
              <input
                type="range"
                min={MIN}
                max={MAX}
                value={v}
                onChange={(e) => update(stat, Number(e.target.value))}
                className="w-full"
                aria-label={`${STAT_INFO[stat].label} slider`}
              />
              <span className="text-[10px] text-fg-muted hidden lg:inline">
                {STAT_INFO[stat].effect}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-3 text-[10px] text-fg-muted">
        Each stat 5–25. Total ≤ 100 (point buy). Server rejects over-budget
        manifests.
      </div>
    </div>
  );
}
