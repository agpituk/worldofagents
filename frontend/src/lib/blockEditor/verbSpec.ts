// Canonical verb spec — drives the action-block kinds.
//
// Hand-curated against `bot-sdk-python/src/arena_bot/actions.py:684-697`
// (DEFAULT_TOOLS) — see IMPL_PLAN.md §2.1 for the divergence between
// the GRAMMAR.md idealized table and the actual signatures.
//
// `clampable` mirrors `world-api/app/domains/manifest_validate/clamp_table.py`.
// A build script can refresh this from `GET /admin/verb-catalog` if the
// backend table changes; the manual seed keeps the editor self-contained
// and offline-buildable.

import { VerbSpec } from "./types";

export const VERB_SPECS: VerbSpec[] = [
  // --- Combat ---
  {
    verb: "attack",
    category: "combat",
    description: "Strike a hostile mob in melee (manhattan ≤ 1).",
    params: [{ name: "target", type: "slug", description: "Hostile NPC slug." }],
    clampable: ["target"],
  },
  {
    verb: "attack_hero",
    category: "combat",
    description: "PvP — strike another hero in melee. Frontier zones only.",
    params: [{ name: "target", type: "string", description: "Hero name." }],
    clampable: ["target"],
  },
  {
    verb: "defend",
    category: "combat",
    description: "+5 AC against incoming attacks this tick.",
    params: [],
    clampable: [],
  },
  {
    verb: "flee",
    category: "combat",
    description: "Step away from the nearest hostile.",
    params: [],
    clampable: [],
  },
  // --- Movement ---
  {
    verb: "move",
    category: "movement",
    description: "Walk to a tile in your current zone.",
    params: [{ name: "target", type: "tile", description: "[x, y] target tile." }],
    clampable: ["target"],
  },
  {
    verb: "travel",
    category: "movement",
    description: "Walk to an adjacent zone.",
    params: [{ name: "zone", type: "slug", description: "Zone slug." }],
    clampable: ["zone"],
  },
  // --- Social ---
  {
    verb: "say",
    category: "social",
    description: "Speak aloud; adjacent NPCs (≤1) react.",
    params: [{ name: "message", type: "string", description: "Up to 400 chars." }],
    clampable: ["message"],
  },
  // --- Items ---
  {
    verb: "give",
    category: "items",
    description: "Hand an item to an adjacent NPC.",
    params: [
      { name: "target", type: "slug", description: "NPC slug." },
      { name: "item", type: "slug", description: "Item slug from inventory." },
    ],
    clampable: ["target", "item"],
  },
  {
    verb: "pickup",
    category: "items",
    description: "Grab an item on your tile.",
    params: [{ name: "slug", type: "slug" }],
    clampable: ["slug"],
  },
  {
    verb: "drop",
    category: "items",
    description: "Drop an item from inventory.",
    params: [{ name: "slug", type: "slug" }],
    clampable: ["slug"],
  },
  {
    verb: "equip",
    category: "items",
    description: "Equip an item from inventory.",
    params: [{ name: "slug", type: "slug" }],
    clampable: ["slug"],
  },
  {
    verb: "unequip",
    category: "items",
    description: "Free an equipment slot.",
    params: [{ name: "slot", type: "string", description: "weapon | armor" }],
    clampable: ["slot"],
  },
  // --- Economy ---
  {
    verb: "gather",
    category: "economy",
    description: "Gather a resource node on your tile (auto-resolved).",
    params: [],
    clampable: [],
  },
  {
    verb: "fish",
    category: "economy",
    description: "Fish from a fishing hole on your tile.",
    params: [],
    clampable: [],
  },
  {
    verb: "craft",
    category: "economy",
    description: "Craft a recipe at an adjacent workstation.",
    params: [{ name: "recipe", type: "slug" }],
    clampable: ["recipe"],
  },
  {
    verb: "buy",
    category: "economy",
    description: "Buy from an adjacent merchant.",
    params: [
      { name: "target", type: "slug", description: "Merchant NPC slug." },
      { name: "item", type: "slug" },
      { name: "qty", type: "int", optional: true, description: "Default 1." },
    ],
    clampable: ["target", "item", "qty"],
  },
  {
    verb: "sell",
    category: "economy",
    description: "Sell to an adjacent merchant.",
    params: [
      { name: "target", type: "slug" },
      { name: "item", type: "slug" },
      { name: "qty", type: "int", optional: true },
    ],
    clampable: ["target", "item", "qty"],
  },
  {
    verb: "store",
    category: "economy",
    description: "Move items into your stash (banker required).",
    params: [
      { name: "slug", type: "slug" },
      { name: "qty", type: "int", optional: true },
    ],
    clampable: ["slug", "qty"],
  },
  {
    verb: "withdraw",
    category: "economy",
    description: "Pull items from your stash.",
    params: [
      { name: "slug", type: "slug" },
      { name: "qty", type: "int", optional: true },
    ],
    clampable: ["slug", "qty"],
  },
  {
    verb: "buy_house",
    category: "economy",
    description: "Buy an unowned building.",
    params: [{ name: "slug", type: "slug" }],
    clampable: ["slug"],
  },
  // --- Magic ---
  {
    verb: "cast",
    category: "magic",
    description: "Cast a spell from known_spells.",
    params: [
      { name: "spell", type: "slug" },
      { name: "target", type: "slug", optional: true },
    ],
    clampable: ["spell", "target"],
  },
  {
    verb: "learn",
    category: "magic",
    description: "Consume a scroll to learn its spell.",
    params: [{ name: "scroll", type: "slug" }],
    clampable: ["scroll"],
  },
  // --- Quest / identity ---
  {
    verb: "tame",
    category: "special",
    description: "Tame a tameable mob.",
    params: [{ name: "target", type: "slug" }],
    clampable: ["target"],
  },
  {
    verb: "accept_quest",
    category: "quest",
    description: "Accept a quest from an adjacent NPC.",
    params: [{ name: "target", type: "slug" }],
    clampable: ["target"],
  },
  {
    verb: "claim_reward",
    category: "quest",
    description: "Turn in a completed quest.",
    params: [{ name: "quest", type: "slug" }],
    clampable: ["quest"],
  },
  {
    verb: "steal",
    category: "economy",
    description: "Attempt to steal from a merchant.",
    params: [
      { name: "target", type: "slug" },
      { name: "item", type: "slug" },
    ],
    clampable: ["target", "item"],
  },
  // --- Memory ---
  {
    verb: "journal_write",
    category: "memory",
    description: "Record a thought into your journal.",
    params: [
      { name: "text", type: "string" },
      { name: "tags", type: "list_string", optional: true },
    ],
    clampable: ["text", "tags"],
  },
  {
    verb: "recall",
    category: "memory",
    description: "Search your journal.",
    params: [
      { name: "query", type: "string", optional: true },
      { name: "tags", type: "list_string", optional: true },
      { name: "limit", type: "int", optional: true },
    ],
    clampable: ["query", "tags", "limit"],
  },
  // --- Trade offers ---
  {
    verb: "offer",
    category: "trade",
    description: "Make a trade offer to an adjacent hero.",
    params: [
      { name: "target", type: "slug" },
      { name: "offered_gold", type: "int", optional: true },
      { name: "wanted_gold", type: "int", optional: true },
    ],
    clampable: ["target", "offered_gold", "wanted_gold"],
  },
  {
    verb: "accept_offer",
    category: "trade",
    description: "Accept a pending trade offer.",
    params: [{ name: "offer_id", type: "string" }],
    clampable: ["offer_id"],
  },
  {
    verb: "reject_offer",
    category: "trade",
    description: "Reject a pending trade offer.",
    params: [{ name: "offer_id", type: "string" }],
    clampable: ["offer_id"],
  },
  // --- Tournaments / bounties / contracts ---
  {
    verb: "register_tournament",
    category: "trade",
    description: "Enter a tournament you are inside.",
    params: [{ name: "slug", type: "slug" }],
    clampable: ["slug"],
  },
  {
    verb: "post_bounty",
    category: "trade",
    description: "Place a public hit on a hero.",
    params: [
      { name: "target", type: "slug" },
      { name: "gold", type: "int" },
      { name: "reason", type: "string", optional: true },
    ],
    clampable: ["target", "gold"],
  },
  {
    verb: "post_contract",
    category: "trade",
    description: "Post a contract to the labor market.",
    params: [
      { name: "kind", type: "string" },
      { name: "reward", type: "int" },
      { name: "target", type: "slug", optional: true },
      { name: "zone", type: "slug", optional: true },
      { name: "ttl", type: "int", optional: true },
      { name: "reason", type: "string", optional: true },
    ],
    clampable: ["kind", "reward", "target", "zone", "ttl"],
  },
  {
    verb: "claim_contract",
    category: "trade",
    description: "Claim a contract that needs an explicit claimer.",
    params: [{ name: "contract_id", type: "string" }],
    clampable: ["contract_id"],
  },
  {
    verb: "cancel_contract",
    category: "trade",
    description: "Cancel a contract you posted.",
    params: [{ name: "contract_id", type: "string" }],
    clampable: ["contract_id"],
  },
  // --- Special / introspection ---
  {
    verb: "examine",
    category: "special",
    description: "Inspect an NPC or item.",
    params: [{ name: "target", type: "slug" }],
    clampable: ["target"],
  },
  {
    verb: "look",
    category: "special",
    description: "Refresh perception. Rarely needed.",
    params: [],
    clampable: [],
  },
  {
    verb: "wait",
    category: "special",
    description: "Skip this tick.",
    params: [],
    clampable: [],
  },
  {
    verb: "leave_sandbox",
    category: "special",
    description: "Step out of the sandbox tutorial early.",
    params: [],
    clampable: [],
  },
  // --- Meta / convenience verbs.
  // `invoke_llm` is a meta-verb the runtime expands into a tool-calling
  // LLM round (catch-all reflex). The rest are SDK convenience aliases
  // that resolve at runtime to a primitive based on perception (see
  // `bot-sdk-python/src/arena_bot/reflexes.py:resolve_action`). Listing
  // them here gives them friendly blocks in the editor instead of
  // falling through to the generic `raw_action` fallback.
  {
    verb: "invoke_llm",
    category: "special",
    description: "Escalate to the LLM. Use as the catch-all reflex; the model picks the next action with full perception + tools.",
    params: [],
    clampable: [],
  },
  {
    verb: "attack_nearest_hostile",
    category: "combat",
    description: "Attack whichever hostile is closest. Resolves to attack(target=<slug>) at runtime.",
    params: [],
    clampable: [],
  },
  {
    verb: "move_to_nearest_hostile",
    category: "movement",
    description: "Step toward the nearest hostile. Resolves to move(target=<tile>) at runtime.",
    params: [],
    clampable: [],
  },
  {
    verb: "attack_nearest_hero",
    category: "combat",
    description: "PvP — attack whichever hero is closest (frontier zones only).",
    params: [],
    clampable: [],
  },
  {
    verb: "move_to_nearest_hero",
    category: "movement",
    description: "Step toward the nearest hero. Resolves to move(target=<tile>) at runtime.",
    params: [],
    clampable: [],
  },
  {
    verb: "move_to_npc",
    category: "movement",
    description: "Step toward a named NPC. Resolves to move(target=<tile>) at runtime.",
    params: [{ name: "slug", type: "slug", description: "NPC slug to approach." }],
    clampable: [],
  },
];

export const VERB_BY_NAME: Record<string, VerbSpec> = Object.fromEntries(
  VERB_SPECS.map((v) => [v.verb, v]),
);

// Reflex-helper functions exposed to the expression DSL — see
// `bot-sdk-python/src/arena_bot/reflexes.py:build_context`.
export const REFLEX_HELPERS: { name: string; arity: number; description: string }[] = [
  { name: "adjacent_to", arity: 1, description: "Within manhattan 1 of a named NPC." },
  { name: "visible", arity: 1, description: "NPC slug is in perception." },
  { name: "in_inventory", arity: 1, description: "Item slug is in inventory." },
  { name: "enemy_in_range", arity: 0, description: "Any hostile within manhattan 1." },
  { name: "hostile_visible", arity: 0, description: "Any hostile visible at all." },
  { name: "any_hero_adjacent", arity: 0, description: "Another hero is at manhattan ≤ 1." },
  { name: "any_hero_visible", arity: 0, description: "Another hero is in perception." },
  { name: "in_pvp_zone", arity: 0, description: "Current zone allows PvP." },
  { name: "weapon_equipped", arity: 0, description: "Has a weapon equipped." },
  { name: "armor_equipped", arity: 0, description: "Has armor equipped." },
  { name: "item_at_my_tile", arity: 1, description: "Item kind ('weapon', 'armor', 'resource') is on this tile." },
  { name: "connection", arity: 1, description: "Slug is an adjacent zone of the current zone." },
];

// Hero-state scalars from build_context. Names only — typed as Number
// in slot constraints for the simple scalars; var_ref blocks are
// loose-typed for flexibility.
export const HERO_SCALARS: string[] = [
  "hp",
  "gold",
  "zone",
  "pos_x",
  "pos_y",
  "mana_current",
  "mana_max",
  "tick_id",
];

// Override-only helpers from GRAMMAR.md §1.2.
export const OVERRIDE_HELPERS: { name: string; arity: number; description: string }[] = [
  { name: "min", arity: 2, description: "Smaller of two values." },
  { name: "max", arity: 2, description: "Larger of two values." },
  { name: "clamp", arity: 3, description: "clamp(x, lo, hi)." },
  { name: "floor", arity: 1, description: "Round down." },
  { name: "ceil", arity: 1, description: "Round up." },
  { name: "abs", arity: 1, description: "Absolute value." },
  { name: "len", arity: 1, description: "Length of a string or list." },
];
