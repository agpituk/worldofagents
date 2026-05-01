"use client";

import type { Occupant, ZoneBuilding, ZoneDetail, ZoneNPC, ZoneResource } from "@/lib/api";
import type { StreamEvent } from "@/lib/use-zone-stream";
import { useEffect, useState } from "react";

const TILE = 28;  // px

type FloatingDamage = { id: number; x: number; y: number; text: string; color: string; born: number };

// Tile-level impact flash — shimmers a tile when an attack lands there.
type ImpactFlash = { id: number; tx: number; ty: number; color: string; born: number };

// Zone-kind biome backgrounds. SVG <pattern> defs let each zone feel like a
// place. Sanctuary = light stone, frontier = mottled grass, dungeon = dark
// stone, arena = sand. Cheap and stays on-brand (no pixel art).
const BIOME = {
  sanctuary: { fill: "#1a1d21", accent: "#2c2f33", pattern: "stone" },
  frontier: { fill: "#1a1f1c", accent: "#243028", pattern: "grass" },
  dungeon: { fill: "#15131a", accent: "#221a26", pattern: "stone" },
  arena: { fill: "#1f1c17", accent: "#2c281f", pattern: "sand" },
} as const;

const NPC_COLOR: Record<string, string> = {
  innkeeper: "#7ec8a4",
  guard: "#5fa8d3",
  banker: "#c9a35f",
  trainer: "#9b7acb",
  fence: "#d77a8e",
  oracle: "#cfa6e6",
  forge_workstation: "#d99060",
  mob: "#c0584a",
};

// Hero glyph styling — colored by leading faction, sized by division,
// gold ring once they cross 1 day alive, ✕ tombstone when dead.
const FACTION_COLOR: Record<string, string> = {
  wardens: "#5fa8d3",   // blue
  council: "#7ec8a4",   // green
  embered: "#c0584a",   // red
};
const HERO_NEUTRAL = "#f0a800";  // amber — no faction allegiance yet
const DIVISION_RADIUS: Record<string, number> = {
  featherweight: 7,
  middleweight: 9,
  heavyweight: 11,
};
// 1 "world day" for the lifespan ring threshold = ~24h real-time (14400 ticks
// at 6s/tick). Crossing it shows a gold halo around the glyph.
const LIFESPAN_RING_TICKS = 14400;

// Resource node glyphs — single-character indicators at the tile center.
const RESOURCE_GLYPH: Record<string, string> = {
  ore_vein: "⛏",
  log_pile: "🪵",
  herb_patch: "✿",
};

const BUILDING_FILL = "rgba(160, 122, 24, 0.18)";
const BUILDING_FILL_OWNED = "rgba(176, 64, 48, 0.30)";
const BUILDING_STROKE = "rgba(240, 168, 0, 0.6)";

function entityColor(n: ZoneNPC): string {
  if (!n.alive) return "#3a3a3a";
  if (n.hostility === "hostile") return "#c0584a";
  if (n.hostility === "tamed") return "#9bd0c2";
  return NPC_COLOR[n.kind] ?? "#7e7768";
}

export function ZoneMap({ zone, events }: { zone: ZoneDetail; events?: StreamEvent[] }) {
  const w = zone.width * TILE;
  const h = zone.height * TILE;

  const tx = (x: number) => x * TILE + TILE / 2;
  const ty = (y: number) => y * TILE + TILE / 2;

  // Collect floating damage labels + tile-level impact flashes from recent
  // combat events. Floats live ~1.5s, flashes ~350ms.
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

  const biome = BIOME[zone.kind as keyof typeof BIOME] ?? BIOME.sanctuary;
  const patternId = `biome-${zone.slug}`;

  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      className="border border-border"
      style={{ maxWidth: "100%", height: "auto" }}
    >
      {/* Biome pattern — paints zone identity. Sanctuary stone is a calm
          square grid; frontier grass adds dot speckle; dungeon adds darker
          mottling; arena uses a subtle radial gradient. */}
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
      <rect width={w} height={h} fill={`url(#${patternId})`} />

      {/* tile grid — faint, drawn over the biome */}
      <g stroke="rgba(255,255,255,0.05)">
        {Array.from({ length: zone.width + 1 }).map((_, x) => (
          <line key={`v${x}`} x1={x * TILE} y1={0} x2={x * TILE} y2={h} />
        ))}
        {Array.from({ length: zone.height + 1 }).map((_, y) => (
          <line key={`h${y}`} x1={0} y1={y * TILE} x2={w} y2={y * TILE} />
        ))}
      </g>

      {/* impact flashes — drawn early so they live behind glyphs */}
      {flashes.map((f) => {
        const age = (Date.now() - f.born) / 350;
        const opacity = Math.max(0, 0.6 * (1 - age));
        return (
          <rect
            key={f.id}
            x={f.tx * TILE}
            y={f.ty * TILE}
            width={TILE}
            height={TILE}
            fill={f.color}
            opacity={opacity}
            pointerEvents="none"
          />
        );
      })}

      {/* buildings — drawn beneath everything */}
      {(zone.buildings ?? []).map((b: ZoneBuilding) => (
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

      {/* resource nodes — glyph overlay at tile center, dimmed when depleted */}
      {(zone.resource_nodes ?? []).map((r: ZoneResource) => {
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

      {/* NPCs */}
      {(zone.npcs ?? []).map((n: ZoneNPC) => (
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

      {/* heroes — glyph state mirrors the world's accumulated investment.
          Color = leading faction; size = division; gold halo = >1d alive;
          quest indicator = active main-quest step; tombstone = dead. */}
      {zone.occupants.map((o: Occupant) => {
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

      {/* floating damage numbers */}
      {floats.map((f) => {
        const age = (Date.now() - f.born) / 1500;
        const opacity = Math.max(0, 1 - age);
        const drift = age * -16;
        return (
          <text
            key={f.id}
            x={f.x}
            y={f.y + drift}
            fill={f.color}
            fontSize={11}
            fontFamily="ui-monospace, monospace"
            fontWeight="bold"
            textAnchor="middle"
            opacity={opacity}
            pointerEvents="none"
          >
            {f.text}
          </text>
        );
      })}
    </svg>
  );
}
