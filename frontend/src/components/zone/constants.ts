// Shared visual constants for the zone map and its overlay layers.

export const TILE = 28; // px

// Zone-kind biome backgrounds. SVG <pattern> defs let each zone feel like a
// place. Sanctuary = light stone, frontier = mottled grass, dungeon = dark
// stone, arena = sand. Cheap and stays on-brand (no pixel art).
export const BIOME = {
  sanctuary: { fill: "#1a1d21", accent: "#2c2f33", pattern: "stone" },
  frontier: { fill: "#1a1f1c", accent: "#243028", pattern: "grass" },
  dungeon: { fill: "#15131a", accent: "#221a26", pattern: "stone" },
  arena: { fill: "#1f1c17", accent: "#2c281f", pattern: "sand" },
} as const;

export const NPC_COLOR: Record<string, string> = {
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
export const FACTION_COLOR: Record<string, string> = {
  wardens: "#5fa8d3", // blue
  council: "#7ec8a4", // green
  embered: "#c0584a", // red
};
export const HERO_NEUTRAL = "#f0a800"; // amber — no faction allegiance yet
export const DIVISION_RADIUS: Record<string, number> = {
  featherweight: 7,
  middleweight: 9,
  heavyweight: 11,
};
// 1 "world day" for the lifespan ring threshold = ~24h real-time (14400 ticks
// at 6s/tick). Crossing it shows a gold halo around the glyph.
export const LIFESPAN_RING_TICKS = 14400;

// Resource node glyphs — single-character indicators at the tile center.
export const RESOURCE_GLYPH: Record<string, string> = {
  ore_vein: "⛏",
  log_pile: "🪵",
  herb_patch: "✿",
};

export const BUILDING_FILL = "rgba(160, 122, 24, 0.18)";
export const BUILDING_FILL_OWNED = "rgba(176, 64, 48, 0.30)";
export const BUILDING_STROKE = "rgba(240, 168, 0, 0.6)";

export type FloatingDamage = {
  id: number;
  x: number;
  y: number;
  text: string;
  color: string;
  born: number;
};

// Tile-level impact flash — shimmers a tile when an attack lands there.
export type ImpactFlash = {
  id: number;
  tx: number;
  ty: number;
  color: string;
  born: number;
};
