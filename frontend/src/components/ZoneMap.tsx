"use client";

import type { ZoneDetail } from "@/lib/api";
import type { StreamEvent } from "@/lib/use-zone-stream";
import BiomeBackground from "./zone/BiomeBackground";
import BuildingLayer from "./zone/BuildingLayer";
import FloatingDamageLayer from "./zone/FloatingDamageLayer";
import HeroLayer from "./zone/HeroLayer";
import ImpactFlashLayer from "./zone/ImpactFlashLayer";
import NPCLayer from "./zone/NPCLayer";
import ResourceLayer from "./zone/ResourceLayer";
import { TILE } from "./zone/constants";
import { useCombatFloats } from "./zone/useCombatFloats";

export function ZoneMap({ zone, events }: { zone: ZoneDetail; events?: StreamEvent[] }) {
  const w = zone.width * TILE;
  const h = zone.height * TILE;

  const tx = (x: number) => x * TILE + TILE / 2;
  const ty = (y: number) => y * TILE + TILE / 2;

  const { floats, flashes } = useCombatFloats(zone, events);

  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      className="border border-border"
      style={{ maxWidth: "100%", height: "auto" }}
    >
      <BiomeBackground zone={zone} width={w} height={h} />
      {/* impact flashes — drawn early so they live behind glyphs */}
      <ImpactFlashLayer flashes={flashes} />
      {/* buildings — drawn beneath everything else gameplay-wise */}
      <BuildingLayer buildings={zone.buildings ?? []} />
      {/* resource nodes — glyph overlay at tile center, dimmed when depleted */}
      <ResourceLayer resources={zone.resource_nodes ?? []} tx={tx} ty={ty} />
      <NPCLayer npcs={zone.npcs ?? []} tx={tx} ty={ty} />
      <HeroLayer occupants={zone.occupants} tx={tx} ty={ty} />
      <FloatingDamageLayer floats={floats} />
    </svg>
  );
}
