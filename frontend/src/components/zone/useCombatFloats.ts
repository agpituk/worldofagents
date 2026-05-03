"use client";

import { useEffect, useState } from "react";
import type { ZoneDetail } from "@/lib/api";
import type { StreamEvent } from "@/lib/use-zone-stream";
import { FloatingDamage, ImpactFlash, TILE } from "./constants";

/**
 * Watches the latest tail of stream events for combat outcomes and surfaces
 * short-lived floating damage labels + tile flashes for the map to render.
 *
 * Floats live ~1.5s, flashes ~350ms; both are reaped on a 100ms timer.
 */
export function useCombatFloats(
  zone: ZoneDetail,
  events: StreamEvent[] | undefined,
): { floats: FloatingDamage[]; flashes: ImpactFlash[] } {
  const tx = (x: number) => x * TILE + TILE / 2;
  const ty = (y: number) => y * TILE + TILE / 2;

  const [floats, setFloats] = useState<FloatingDamage[]>([]);
  const [flashes, setFlashes] = useState<ImpactFlash[]>([]);

  useEffect(() => {
    if (!events || events.length === 0) return;
    const now = Date.now();
    const fresh: FloatingDamage[] = [];
    const freshFlashes: ImpactFlash[] = [];
    let nextId = now;

    function flashAt(px: number, py: number, color: string) {
      freshFlashes.push({ id: ++nextId, tx: px, ty: py, color, born: now });
    }

    for (const ev of events.slice(-12)) {
      if (ev.kind !== "tick") continue;
      const payload = ev.data?.payload || {};
      // mob.attack on a hero — show damage on hero's tile (lookup)
      if (ev.data?.kind === "mob.attack" && payload.hit && payload.damage) {
        const target = zone.occupants.find((o) => o.id === payload.target_hero_id);
        if (target) {
          fresh.push({
            id: ++nextId, x: tx(target.pos[0]), y: ty(target.pos[1]) - 12,
            text: `-${payload.damage}`, color: "#ff6f5e",
            born: now,
          });
          flashAt(target.pos[0], target.pos[1], "#ff6f5e");
        }
      }
      // hero attack outcome — show damage on the npc/hero tile
      if (ev.data?.kind === "action.resolved" && payload.outcome) {
        const o = payload.outcome;
        if (o.verb === "attack" && o.hit && o.damage) {
          const npc = (zone.npcs ?? []).find((n) => n.slug === o.target);
          if (npc) {
            fresh.push({
              id: ++nextId, x: tx(npc.pos[0]), y: ty(npc.pos[1]) - 12,
              text: `${o.crit ? "CRIT! " : ""}-${o.damage}`,
              color: o.crit ? "#ffd24a" : "#f0a800",
              born: now,
            });
            flashAt(npc.pos[0], npc.pos[1], o.crit ? "#ffd24a" : "#f0a800");
          }
        }
        if (o.verb === "attack_hero" && o.hit && o.damage) {
          const target = zone.occupants.find((occ) => occ.name === o.target);
          if (target) {
            fresh.push({
              id: ++nextId, x: tx(target.pos[0]), y: ty(target.pos[1]) - 12,
              text: `-${o.damage}`, color: "#ff6f5e",
              born: now,
            });
            flashAt(target.pos[0], target.pos[1], "#ff6f5e");
          }
        }
      }
    }
    if (fresh.length) {
      setFloats((prev) => [...prev.slice(-10), ...fresh]);
    }
    if (freshFlashes.length) {
      setFlashes((prev) => [...prev.slice(-10), ...freshFlashes]);
    }
  }, [events?.length]);

  // Reap expired floats + flashes every 100ms.
  useEffect(() => {
    const t = setInterval(() => {
      const now = Date.now();
      setFloats((prev) => prev.filter((f) => now - f.born < 1500));
      setFlashes((prev) => prev.filter((f) => now - f.born < 350));
    }, 100);
    return () => clearInterval(t);
  }, []);

  return { floats, flashes };
}
