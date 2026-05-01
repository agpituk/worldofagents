"""Seed resource nodes and crafting recipes."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.models import NPC, Recipe, ResourceNode

log = logging.getLogger("world.resource_node.seed")


SEED_NODES = [
    {
        "slug": "iron_ore_vein_1",
        "name": "Iron Ore Vein",
        "kind": "ore_vein",
        "zone": "hush_wood",
        "pos_x": 3, "pos_y": 3,
        "yield_item_slug": "iron_ore",
        "yield_item_name": "Iron Ore",
        "yield_item_kind": "material",
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
        "respawn_after_ticks": 20,
    },
    {
        "slug": "moonbloom_patch",
        "name": "Moonbloom Patch",
        "kind": "herb_patch",
        "zone": "hush_wood",
        "pos_x": 6, "pos_y": 2,
        "yield_item_slug": "moonbloom",
        "yield_item_name": "Moonbloom",
        "yield_item_kind": "herb",
        "respawn_after_ticks": 30,
    },
    {
        "slug": "oak_log_pile",
        "name": "Fallen Oak",
        "kind": "log_pile",
        "zone": "lantern_road",
        "pos_x": 5, "pos_y": 3,
        "yield_item_slug": "oak_log",
        "yield_item_name": "Oak Log",
        "yield_item_kind": "material",
        "respawn_after_ticks": 25,
    },
]


SEED_RECIPES = [
    {
        "slug": "iron_sword_recipe",
        "name": "Iron Sword",
        "output_slug": "iron_sword",
        "output_name": "Iron Sword",
        "output_kind": "weapon",
        "output_description": "A simple iron blade. Honest steel, no enchantment.",
        "output_props": {"slot": "weapon", "damage_dice": "1d8", "attack_bonus": 1},
        "inputs": [{"slug": "iron_ore", "count": 2}, {"slug": "oak_log", "count": 1}],
        "skill_required": "crafting",
        "skill_min": 0,
        "workstation_kind": "forge_workstation",
    },
    {
        "slug": "leather_jerkin_recipe",
        "name": "Leather Jerkin",
        "output_slug": "leather_jerkin",
        "output_name": "Leather Jerkin",
        "output_kind": "armor",
        "output_description": "Cured hide stitched onto a linen liner.",
        "output_props": {"slot": "armor", "ac_bonus": 2},
        "inputs": [{"slug": "oak_log", "count": 1}],  # placeholder until we add hides
        "skill_required": "crafting",
        "skill_min": 1,
        "workstation_kind": "forge_workstation",
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
        "skill_required": "crafting",
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
        "skill_required": "crafting",
        "skill_min": 0,
        "workstation_kind": "forge_workstation",
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
