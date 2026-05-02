"""Seed resource nodes and crafting recipes.

Phase 1 of the build-diversity roadmap split the single `crafting` skill
into a real skill tree. Gather verbs grant XP into the node's
`skill_required` (mining / herbalism / lumberjacking / fishing). Craft
verbs grant XP into the recipe's `skill_required` (smithing / cooking /
alchemy / carpentry / tailoring / scribe / tinkering). Each non-combat
specialist now has at least one node OR recipe that exercises their
skill — enough surface for a manifest to declare the build and grind it.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.models import NPC, Recipe, ResourceNode

log = logging.getLogger("world.resource_node.seed")


SEED_NODES = [
    # ── Mining ─────────────────────────────────────────────────────────
    {
        "slug": "iron_ore_vein_1",
        "name": "Iron Ore Vein",
        "kind": "ore_vein",
        "zone": "hush_wood",
        "pos_x": 3, "pos_y": 3,
        "yield_item_slug": "iron_ore",
        "yield_item_name": "Iron Ore",
        "yield_item_kind": "material",
        "skill_required": "mining",
        "respawn_after_ticks": 20,
    },
    {
        "slug": "iron_ore_vein_2",
        "name": "Iron Ore Vein",
        "kind": "ore_vein",
        "zone": "hush_wood",
        "pos_x": 9, "pos_y": 9,
        "yield_item_slug": "iron_ore",
        "yield_item_name": "Iron Ore",
        "yield_item_kind": "material",
        "skill_required": "mining",
        "respawn_after_ticks": 20,
    },
    {
        "slug": "copper_vein_1",
        "name": "Copper Vein",
        "kind": "ore_vein",
        "zone": "old_cisterns",
        "pos_x": 4, "pos_y": 6,
        "yield_item_slug": "copper_ore",
        "yield_item_name": "Copper Ore",
        "yield_item_kind": "material",
        "skill_required": "mining",
        "respawn_after_ticks": 25,
    },
    {
        "slug": "silver_vein_1",
        "name": "Silver Vein",
        "kind": "ore_vein",
        "zone": "old_cisterns",
        "pos_x": 8, "pos_y": 2,
        "yield_item_slug": "silver_ore",
        "yield_item_name": "Silver Ore",
        "yield_item_kind": "material",
        "skill_required": "mining",
        "respawn_after_ticks": 35,
    },
    # ── Herbalism ──────────────────────────────────────────────────────
    {
        "slug": "moonbloom_patch",
        "name": "Moonbloom Patch",
        "kind": "herb_patch",
        "zone": "hush_wood",
        "pos_x": 6, "pos_y": 2,
        "yield_item_slug": "moonbloom",
        "yield_item_name": "Moonbloom",
        "yield_item_kind": "herb",
        "skill_required": "herbalism",
        "respawn_after_ticks": 30,
    },
    {
        "slug": "bitterroot_patch",
        "name": "Bitterroot Patch",
        "kind": "herb_patch",
        "zone": "lantern_road",
        "pos_x": 7, "pos_y": 6,
        "yield_item_slug": "bitterroot",
        "yield_item_name": "Bitterroot",
        "yield_item_kind": "herb",
        "skill_required": "herbalism",
        "respawn_after_ticks": 30,
    },
    # ── Lumberjacking ──────────────────────────────────────────────────
    {
        "slug": "oak_log_pile",
        "name": "Fallen Oak",
        "kind": "log_pile",
        "zone": "lantern_road",
        "pos_x": 5, "pos_y": 3,
        "yield_item_slug": "oak_log",
        "yield_item_name": "Oak Log",
        "yield_item_kind": "material",
        "skill_required": "lumberjacking",
        "respawn_after_ticks": 25,
    },
    {
        "slug": "pine_grove_1",
        "name": "Pine Grove",
        "kind": "log_pile",
        "zone": "hush_wood",
        "pos_x": 2, "pos_y": 8,
        "yield_item_slug": "pine_log",
        "yield_item_name": "Pine Log",
        "yield_item_kind": "material",
        "skill_required": "lumberjacking",
        "respawn_after_ticks": 25,
    },
    # ── Fishing ────────────────────────────────────────────────────────
    {
        "slug": "lantern_creek",
        "name": "Lantern Creek",
        "kind": "fishing_hole",
        "zone": "lantern_road",
        "pos_x": 2, "pos_y": 8,
        "yield_item_slug": "raw_fish",
        "yield_item_name": "Raw Fish",
        "yield_item_kind": "food",
        "skill_required": "fishing",
        "respawn_after_ticks": 15,
    },
    {
        "slug": "cistern_pool",
        "name": "Cistern Pool",
        "kind": "fishing_hole",
        "zone": "old_cisterns",
        "pos_x": 6, "pos_y": 9,
        "yield_item_slug": "raw_fish",
        "yield_item_name": "Raw Fish",
        "yield_item_kind": "food",
        "skill_required": "fishing",
        "respawn_after_ticks": 15,
    },
    {
        "slug": "tideway_pier",
        "name": "Tideway Pier",
        "kind": "fishing_hole",
        "zone": "tideway_docks",
        "pos_x": 4, "pos_y": 4,
        "yield_item_slug": "raw_fish",
        "yield_item_name": "Raw Fish",
        "yield_item_kind": "food",
        "skill_required": "fishing",
        "respawn_after_ticks": 12,
    },
    {
        "slug": "tideway_deepwater",
        "name": "Tideway Deep Water",
        "kind": "fishing_hole",
        "zone": "tideway_docks",
        "pos_x": 9, "pos_y": 6,
        "yield_item_slug": "raw_fish",
        "yield_item_name": "Raw Fish",
        "yield_item_kind": "food",
        "skill_required": "fishing",
        "respawn_after_ticks": 18,
    },
]


SEED_RECIPES = [
    # ── Smithing ───────────────────────────────────────────────────────
    {
        "slug": "iron_sword_recipe",
        "name": "Iron Sword",
        "output_slug": "iron_sword",
        "output_name": "Iron Sword",
        "output_kind": "weapon",
        "output_description": "A simple iron blade. Honest steel, no enchantment.",
        "output_props": {"slot": "weapon", "damage_dice": "1d8", "attack_bonus": 1},
        "inputs": [{"slug": "iron_ore", "count": 2}, {"slug": "oak_log", "count": 1}],
        "skill_required": "smithing",
        "skill_min": 0,
        "workstation_kind": "forge_workstation",
    },
    # ── Tailoring ──────────────────────────────────────────────────────
    {
        "slug": "leather_jerkin_recipe",
        "name": "Leather Jerkin",
        "output_slug": "leather_jerkin",
        "output_name": "Leather Jerkin",
        "output_kind": "armor",
        "output_description": "Cured hide stitched onto a linen liner.",
        "output_props": {"slot": "armor", "ac_bonus": 2},
        "inputs": [{"slug": "oak_log", "count": 1}],  # placeholder until we add hides
        "skill_required": "tailoring",
        "skill_min": 1,
        "workstation_kind": "loom_workstation",
    },
    # ── Cooking ────────────────────────────────────────────────────────
    {
        "slug": "cooked_fish_recipe",
        "name": "Cooked Fish",
        "output_slug": "cooked_fish",
        "output_name": "Cooked Fish",
        "output_kind": "consumable",
        "output_description": "A simple grilled fish. Restores a little HP on eat.",
        "output_props": {"heal": 4, "consumable": True},
        "inputs": [{"slug": "raw_fish", "count": 1}],
        "skill_required": "cooking",
        "skill_min": 0,
        "workstation_kind": "cookfire_workstation",
    },
    # ── Alchemy ────────────────────────────────────────────────────────
    {
        "slug": "heal_potion_recipe",
        "name": "Heal Potion",
        "output_slug": "heal_potion",
        "output_name": "Heal Potion",
        "output_kind": "consumable",
        "output_description": "A bitter brew that knits flesh on the way down.",
        "output_props": {"heal": 10, "consumable": True},
        "inputs": [{"slug": "moonbloom", "count": 2}],
        "skill_required": "alchemy",
        "skill_min": 0,
        "workstation_kind": "alchemy_workstation",
    },
    # ── Carpentry ──────────────────────────────────────────────────────
    {
        "slug": "oak_bow_recipe",
        "name": "Oak Bow",
        "output_slug": "oak_bow",
        "output_name": "Oak Bow",
        "output_kind": "weapon",
        "output_description": "A short bow whittled from a single oak stave.",
        "output_props": {"slot": "weapon", "damage_dice": "1d6", "attack_bonus": 1},
        "inputs": [{"slug": "oak_log", "count": 2}],
        "skill_required": "carpentry",
        "skill_min": 0,
        "workstation_kind": "carpentry_workstation",
    },
    # ── Scribe ─────────────────────────────────────────────────────────
    {
        "slug": "scroll_firebolt_recipe",
        "name": "Scroll of Firebolt",
        "output_slug": "scroll_firebolt",
        "output_name": "Scroll of Firebolt",
        "output_kind": "scroll",
        "output_description": "A blank scroll inked with the firebolt sigil.",
        "output_props": {"teaches": "firebolt"},
        "inputs": [{"slug": "oak_log", "count": 1}, {"slug": "bitterroot", "count": 1}],
        "skill_required": "scribe",
        "skill_min": 0,
        "workstation_kind": "scribe_workstation",
    },
    # ── Tinkering ──────────────────────────────────────────────────────
    {
        "slug": "lockpick_recipe",
        "name": "Lockpick",
        "output_slug": "lockpick",
        "output_name": "Lockpick",
        "output_kind": "tool",
        "output_description": "A delicate iron pick. The kind of tool that earns its keep.",
        "output_props": {"tool": "lockpick"},
        "inputs": [{"slug": "iron_ore", "count": 1}],
        "skill_required": "tinkering",
        "skill_min": 0,
        "workstation_kind": "tinker_workstation",
    },
    # ────────── HIDDEN RECIPES ──────────
    # Excluded from /recipes. Heroes (their models) have to discover the
    # input set by trying things. The first hero to craft each gets a
    # "discovery" milestone and the recipe added to their memory.
    {
        "slug": "scaleforged_blade_recipe",
        "name": "Scaleforged Blade",
        "output_slug": "scaleforged_blade",
        "output_name": "Scaleforged Blade",
        "output_kind": "weapon",
        "output_description": (
            "A blade tempered against a Wyrm's scale. Holds an unsettling warmth."
        ),
        "output_props": {"slot": "weapon", "damage_dice": "2d6", "attack_bonus": 2},
        # Requires the unique drop from the Wyrm event.
        "inputs": [
            {"slug": "iron_sword", "count": 1},
            {"slug": "dragon_scale", "count": 1},
        ],
        "skill_required": "smithing",
        "skill_min": 2,
        "workstation_kind": "forge_workstation",
        "hidden": True,
    },
    {
        "slug": "tempered_charm_recipe",
        "name": "Tempered Charm",
        "output_slug": "tempered_charm",
        "output_name": "Tempered Charm",
        "output_kind": "trinket",
        "output_description": (
            "A small token, hammered from one ore and one log. Lucky in some way."
        ),
        "output_props": {"slot": "trinket", "luck_bonus": 1},
        # Easier discovery: every smith will eventually try this combination.
        "inputs": [
            {"slug": "iron_ore", "count": 1},
            {"slug": "oak_log", "count": 1},
        ],
        "skill_required": "tinkering",
        "skill_min": 0,
        "workstation_kind": "tinker_workstation",
        "hidden": True,
    },
]


SEED_WORKSTATION_NPCS = [
    {
        "slug": "forge",
        "name": "Threshold Forge",
        "kind": "forge_workstation",
        "zone": "market_square",
        "pos_x": 8, "pos_y": 8,
        "description": "An open-air smithing forge in the eastern corner of the Market Square. Stand adjacent to craft.",
        "hostility": "peaceful",
        "hp_max": 9999, "hp_current": 9999, "ac": 99,
    },
    {
        "slug": "alchemy_table",
        "name": "Alchemist's Table",
        "kind": "alchemy_workstation",
        "zone": "market_square",
        "pos_x": 7, "pos_y": 8,
        "description": "A scarred bench crowded with vials and a brass mortar. Stand adjacent to brew.",
        "hostility": "peaceful",
        "hp_max": 9999, "hp_current": 9999, "ac": 99,
    },
    {
        "slug": "cookfire",
        "name": "Public Cookfire",
        "kind": "cookfire_workstation",
        "zone": "market_square",
        "pos_x": 6, "pos_y": 8,
        "description": "A ring of stones over banked coals. Stand adjacent to cook.",
        "hostility": "peaceful",
        "hp_max": 9999, "hp_current": 9999, "ac": 99,
    },
    {
        "slug": "loom",
        "name": "Tailor's Loom",
        "kind": "loom_workstation",
        "zone": "market_square",
        "pos_x": 5, "pos_y": 8,
        "description": "A timber loom strung with linen warp. Stand adjacent to stitch.",
        "hostility": "peaceful",
        "hp_max": 9999, "hp_current": 9999, "ac": 99,
    },
    {
        "slug": "carpentry_bench",
        "name": "Carpentry Bench",
        "kind": "carpentry_workstation",
        "zone": "market_square",
        "pos_x": 4, "pos_y": 8,
        "description": "A heavy oak bench with vise and rasps. Stand adjacent to shape wood.",
        "hostility": "peaceful",
        "hp_max": 9999, "hp_current": 9999, "ac": 99,
    },
    {
        "slug": "scribe_desk",
        "name": "Scribe's Desk",
        "kind": "scribe_workstation",
        "zone": "codex_hall",
        "pos_x": 5, "pos_y": 5,
        "description": "A slanted desk in the Codex Hall. Inkwell, quills, blank vellum. Stand adjacent to inscribe.",
        "hostility": "peaceful",
        "hp_max": 9999, "hp_current": 9999, "ac": 99,
    },
    {
        "slug": "tinker_bench",
        "name": "Tinker's Bench",
        "kind": "tinker_workstation",
        "zone": "market_square",
        "pos_x": 3, "pos_y": 8,
        "description": "Springs, wire, files and lock plates. Stand adjacent to tinker.",
        "hostility": "peaceful",
        "hp_max": 9999, "hp_current": 9999, "ac": 99,
    },
]


def seed_world_economy(db: Session) -> None:
    for n in SEED_NODES:
        if db.get(ResourceNode, n["slug"]) is None:
            db.add(ResourceNode(**n))
            log.info("seeded node: %s @ %s", n["slug"], n["zone"])
    for r in SEED_RECIPES:
        if db.get(Recipe, r["slug"]) is None:
            db.add(Recipe(**r))
            log.info("seeded recipe: %s", r["slug"])
    for w in SEED_WORKSTATION_NPCS:
        if db.get(NPC, w["slug"]) is None:
            db.add(NPC(**w))
            log.info("seeded workstation NPC: %s @ %s", w["slug"], w["zone"])
    db.commit()
