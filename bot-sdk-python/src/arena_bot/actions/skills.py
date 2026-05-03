"""Skill-grinding action verbs (gather/fish/craft/steal/tame)."""

from __future__ import annotations

from typing import Any


def gather() -> dict[str, Any]:
    """Gather a non-fish resource (ore, herb, log) from a node on your tile.

    Use when `visible_resources` contains a non-fishing-hole entry whose
    `pos` matches yours. Each gather yields one raw material into your
    inventory and grants +1 XP in the node's `skill_required`
    (`mining` / `herbalism` / `lumberjacking`). Nodes deplete after use
    and respawn after a fixed number of ticks.

    For fishing holes, use `fish()` instead.

    Args:
        (none) — the node at your tile is gathered automatically.
    """
    return {"do": "gather"}


def fish() -> dict[str, Any]:
    """Fish from a fishing hole on your current tile.

    Use when `visible_resources` contains a `fishing_hole` entry whose
    `pos` matches yours. Each fish yields one raw fish and grants +1 XP
    in `fishing`. Holes deplete and respawn like other nodes.

    Args:
        (none) — the fishing hole at your tile is fished automatically.
    """
    return {"do": "fish"}


def craft(recipe: str) -> dict[str, Any]:
    """Craft a known recipe at an adjacent workstation.

    Look up `recipe` in the public recipe list. You must:
      • be adjacent (manhattan ≤ 1) to a workstation NPC of the recipe's
        `workstation_kind` (e.g., a `forge_workstation` for smithing,
        `alchemy_workstation` for alchemy, `loom_workstation` for
        tailoring, etc.)
      • have all `inputs` in your inventory (correct slug + count)
      • meet the `skill_min` for the recipe's `skill_required`

    On success, the inputs are consumed from your inventory and the output
    item is created and placed in your inventory. +2 XP in the recipe's
    `skill_required` (e.g. `smithing`, `alchemy`, `cooking`, `carpentry`,
    `tailoring`, `scribe`, `tinkering`).

    Args:
        recipe: The slug of the recipe to craft (e.g., "iron_sword_recipe").
    """
    return {"do": "craft", "recipe": recipe}


def steal(target: str, item: str) -> dict[str, Any]:
    """Attempt to steal an item from an adjacent merchant's stock.

    Roll: d20 + DEX/4 + stealth/4 vs DC 15. Natural 20 always succeeds.
    Natural 1 always fails. On success, one unit moves to your inventory
    with no gold paid; +2 stealth XP. On failure, the NPC notices and
    flags you in their memory — they may refuse to trade with you later.

    IMPORTANT: stealing from a peaceful NPC is theft. There's no take-backs.
    Use only when you can afford the consequences (you can't afford the
    item legitimately, OR you want to grow stealth XP, OR you're a thief
    archetype committing to that lifestyle).

    Args:
        target: Slug of the merchant NPC to steal from.
        item: Slug of the item to steal (must appear in their stock).
    """
    return {"do": "steal", "target": target, "item": item}


def tame(target: str) -> dict[str, Any]:
    """Attempt to tame an adjacent tameable mob into a pet.

    Roll: d20 + CHA/4 + WIS/4 vs DC 12. Natural 1 fails outright. Natural 20
    always succeeds. On success, the mob's hostility flips to "tamed" and it
    becomes your pet — it auto-follows you and attacks hostiles in your zone.

    The target must be in `visible_npcs` with `tameable == true`,
    `tamed_by_hero_id == null`, and `manhattan_to_you <= 1`.

    Args:
        target: Slug of the mob to tame (e.g. "rat_b").
    """
    return {"do": "tame", "target": target}
