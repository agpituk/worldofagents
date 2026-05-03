"use client";

import type { ZoneBuilding } from "@/lib/api";
import { BUILDING_FILL, BUILDING_FILL_OWNED, BUILDING_STROKE, TILE } from "./constants";

export default function BuildingLayer({ buildings }: { buildings: ZoneBuilding[] }) {
  return (
    <>
      {buildings.map((b: ZoneBuilding) => (
        <g key={b.slug}>
          <rect
            x={b.pos[0] * TILE + 1}
            y={b.pos[1] * TILE + 1}
            width={b.width * TILE - 2}
            height={b.height * TILE - 2}
            fill={b.owner_hero_id ? BUILDING_FILL_OWNED : BUILDING_FILL}
            stroke={BUILDING_STROKE}
            strokeWidth={1}
          />
          <text
            x={b.pos[0] * TILE + 4}
            y={b.pos[1] * TILE + 12}
            fontSize={9}
            fill="rgba(240, 168, 0, 0.7)"
            fontFamily="ui-serif, Georgia, serif"
          >
            {b.name}
          </text>
        </g>
      ))}
    </>
  );
}
