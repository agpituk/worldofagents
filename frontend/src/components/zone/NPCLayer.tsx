"use client";

import type { ZoneNPC } from "@/lib/api";
import { NPC_COLOR } from "./constants";

type Props = {
  npcs: ZoneNPC[];
  tx: (x: number) => number;
  ty: (y: number) => number;
};

function entityColor(n: ZoneNPC): string {
  if (!n.alive) return "#3a3a3a";
  if (n.hostility === "hostile") return "#c0584a";
  if (n.hostility === "tamed") return "#9bd0c2";
  return NPC_COLOR[n.kind] ?? "#7e7768";
}

export default function NPCLayer({ npcs, tx, ty }: Props) {
  return (
    <>
      {npcs.map((n: ZoneNPC) => (
        <g key={n.slug} opacity={n.alive ? 1 : 0.35}>
          <rect
            x={tx(n.pos[0]) - 8}
            y={ty(n.pos[1]) - 8}
            width={16}
            height={16}
            rx={3}
            fill={entityColor(n)}
            stroke="rgba(0,0,0,0.5)"
          />
          <title>
            {n.name} ({n.hostility}) · {n.alive ? `${n.hp}/${n.hp_max} hp` : "dead"}
          </title>
        </g>
      ))}
    </>
  );
}
