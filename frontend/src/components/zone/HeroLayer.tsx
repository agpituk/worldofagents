"use client";

import type { Occupant } from "@/lib/api";
import { DIVISION_RADIUS, FACTION_COLOR, HERO_NEUTRAL, LIFESPAN_RING_TICKS } from "./constants";

type Props = {
  occupants: Occupant[];
  tx: (x: number) => number;
  ty: (y: number) => number;
};

// heroes — glyph state mirrors the world's accumulated investment.
// Color = leading faction; size = division; gold halo = >1d alive;
// quest indicator = active main-quest step; tombstone = dead.
export default function HeroLayer({ occupants, tx, ty }: Props) {
  return (
    <>
      {occupants.map((o: Occupant) => {
        const dead = o.status === "dead";
        const r = DIVISION_RADIUS[o.division] ?? DIVISION_RADIUS.featherweight;
        const fill =
          dead ? "#3a3a3a" : (o.leading_faction && FACTION_COLOR[o.leading_faction]) || HERO_NEUTRAL;
        const showRing = !dead && o.ticks_alive >= LIFESPAN_RING_TICKS;
        const cx = tx(o.pos[0]);
        const cy = ty(o.pos[1]);
        return (
          <g key={o.id}>
            {showRing && (
              <circle
                cx={cx}
                cy={cy}
                r={r + 4}
                fill="none"
                stroke="#f0a800"
                strokeWidth={1.5}
                opacity={0.7}
              />
            )}
            {dead ? (
              <text
                x={cx}
                y={cy + 5}
                fontSize={16}
                textAnchor="middle"
                fill="#7a7a7a"
                pointerEvents="none"
              >
                ✕
              </text>
            ) : (
              <>
                <circle
                  cx={cx}
                  cy={cy}
                  r={r}
                  fill={fill}
                  stroke="rgba(0,0,0,0.7)"
                  strokeWidth={1.5}
                />
                {o.has_active_quest && (
                  <circle
                    cx={cx + r - 1}
                    cy={cy - r + 1}
                    r={2.5}
                    fill="#f0a800"
                    stroke="rgba(0,0,0,0.9)"
                    strokeWidth={0.5}
                  />
                )}
              </>
            )}
            <title>
              {o.name} · {o.division} · {o.hp} hp
              {o.leading_faction ? ` · ${o.leading_faction}` : ""}
              {dead ? ` · DEAD` : ` · alive ${o.ticks_alive}t`}
              {o.has_active_quest ? " · quest active" : ""}
            </title>
          </g>
        );
      })}
    </>
  );
}
