"""Combat-related action verbs."""

from __future__ import annotations

from typing import Any


def attack(target: str) -> dict[str, Any]:
    """Strike a hostile mob in melee.

    USE THIS whenever a hostile is at manhattan distance <= 1 from your
    position. Hostile mobs WILL hit you back every tick you don't kill them,
    so attacking is almost always better than waiting or moving when an enemy
    is in melee range.

    IMPORTANT: If a hostile is on your tile (manhattan 0) or adjacent
    (manhattan 1), CALL ATTACK. Do NOT call move when a hostile is already
    adjacent — moving wastes the tick AND lets the mob hit you for free.
    Pick the target slug from `visible_npcs` where hostility == "hostile".

    Args:
        target: The slug of the hostile NPC to attack (e.g., "rat_a", "rat_b").
            Must appear in `visible_npcs` with hostility == "hostile" and
            be at manhattan distance <= 1 from your position.
    """
    return {"do": "attack", "target": target}


def attack_hero(target: str) -> dict[str, Any]:
    """PvP — strike another HERO in melee.

    Use to attack another player's hero. Forbidden in sanctuary zones —
    only frontier, dungeon, and arena zones allow PvP. The target must be
    at manhattan distance <= 1, alive, and in the same zone as you.

    IMPORTANT: pass the target's NAME (e.g., "Bromir the Stalwart"), not
    their hero_id. Names are unique. Heroes appear in `visible_heroes` —
    pick one whose `manhattan_to_you` <= 1.

    Args:
        target: The full name of the hero to attack (e.g., "Bromir the Stalwart").
            Must appear in `visible_heroes` with `in_melee_range == true`.
    """
    return {"do": "attack_hero", "target": target}


def defend() -> dict[str, Any]:
    """Brace for the rest of this tick. +5 to your AC against incoming attacks.

    Use when you expect to be hit but can't yet attack back — for example,
    surrounded by multiple enemies, or low HP and waiting one tick to flee.
    Does no damage.
    """
    return {"do": "defend"}


def flee() -> dict[str, Any]:
    """Step away from the nearest hostile.

    Use ONLY when HP is critically low (≤ 8 typically) and you cannot win the
    next exchange. Otherwise, attacking is almost always the better play.
    """
    return {"do": "flee"}
