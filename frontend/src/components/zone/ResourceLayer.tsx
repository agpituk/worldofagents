"use client";

import type { ZoneResource } from "@/lib/api";
import { RESOURCE_GLYPH } from "./constants";

type Props = {
  resources: ZoneResource[];
  tx: (x: number) => number;
  ty: (y: number) => number;
};

export default function ResourceLayer({ resources, tx, ty }: Props) {
  return (
    <>
      {resources.map((r: ZoneResource) => {
        const depleted = r.depleted_until_tick && r.depleted_until_tick > 0;
        const glyph = RESOURCE_GLYPH[r.kind] ?? "✦";
        return (
          <g key={r.slug} opacity={depleted ? 0.35 : 1}>
            <circle
              cx={tx(r.pos[0])}
              cy={ty(r.pos[1])}
              r={9}
              fill="rgba(20, 30, 24, 0.6)"
              stroke="rgba(140, 180, 130, 0.5)"
              strokeWidth={1}
            />
            <text
              x={tx(r.pos[0])}
              y={ty(r.pos[1]) + 4}
              fontSize={12}
              textAnchor="middle"
              pointerEvents="none"
            >
              {glyph}
            </text>
            <title>
              {r.name} ({r.kind} → {r.yield_item_slug}){depleted ? ` · depleted` : ""}
            </title>
          </g>
        );
      })}
    </>
  );
}
