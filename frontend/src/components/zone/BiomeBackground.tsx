"use client";

import type { ZoneDetail } from "@/lib/api";
import { BIOME, TILE } from "./constants";

type Props = {
  zone: ZoneDetail;
  width: number;
  height: number;
};

// Biome pattern — paints zone identity. Sanctuary stone is a calm
// square grid; frontier grass adds dot speckle; dungeon adds darker
// mottling; arena uses a subtle radial gradient.
export default function BiomeBackground({ zone, width, height }: Props) {
  const biome = BIOME[zone.kind as keyof typeof BIOME] ?? BIOME.sanctuary;
  const patternId = `biome-${zone.slug}`;
  return (
    <>
      <defs>
        <pattern id={patternId} x={0} y={0} width={TILE * 2} height={TILE * 2} patternUnits="userSpaceOnUse">
          <rect width={TILE * 2} height={TILE * 2} fill={biome.fill} />
          {biome.pattern === "stone" && (
            <>
              <rect x={0} y={0} width={TILE} height={TILE} fill={biome.accent} opacity={0.4} />
              <rect x={TILE} y={TILE} width={TILE} height={TILE} fill={biome.accent} opacity={0.4} />
            </>
          )}
          {biome.pattern === "grass" && (
            <>
              <circle cx={TILE / 2} cy={TILE / 3} r={1.4} fill={biome.accent} />
              <circle cx={TILE * 1.6} cy={TILE * 1.2} r={1.2} fill={biome.accent} />
              <circle cx={TILE * 0.3} cy={TILE * 1.7} r={1.1} fill={biome.accent} />
              <circle cx={TILE * 1.2} cy={TILE * 0.7} r={1.6} fill={biome.accent} opacity={0.7} />
            </>
          )}
          {biome.pattern === "sand" && (
            <>
              <circle cx={TILE} cy={TILE} r={TILE * 0.9} fill={biome.accent} opacity={0.35} />
            </>
          )}
        </pattern>
      </defs>

      {/* biome bg */}
      <rect width={width} height={height} fill={`url(#${patternId})`} />

      {/* tile grid — faint, drawn over the biome */}
      <g stroke="rgba(255,255,255,0.05)">
        {Array.from({ length: zone.width + 1 }).map((_, x) => (
          <line key={`v${x}`} x1={x * TILE} y1={0} x2={x * TILE} y2={height} />
        ))}
        {Array.from({ length: zone.height + 1 }).map((_, y) => (
          <line key={`h${y}`} x1={0} y1={y * TILE} x2={width} y2={y * TILE} />
        ))}
      </g>
    </>
  );
}
