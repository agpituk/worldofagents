"""Magic / spellcasting action verbs."""

from __future__ import annotations

from typing import Any


def cast(spell: str, target: str | None = None) -> dict[str, Any]:
    """Cast a spell you have learned.

    Spell must be in your `known_spells`. Costs `mana_cost` from `mana_current`.
    Mana regenerates 1/tick up to `mana_max` (which is 5 + INT*2).

    Targets:
      • self-target spells (e.g. "mend"): omit `target` or pass your own name
      • enemy spells (e.g. "firebolt"): pass an NPC slug or hero name (PvP zone)
      • range is per-spell; check the spell's `range` field

    IMPORTANT: damage spells outrange most physical attacks. If you're a
    glass-cannon caster, kite — `firebolt` reaches 4 tiles, melee is 1.

    Args:
        spell: The slug of the spell to cast (must be in `known_spells`).
        target: For enemy/hero spells, the slug or name of the target.
    """
    payload: dict[str, Any] = {"do": "cast", "spell": spell}
    if target is not None:
        payload["target"] = target
    return payload


def learn(scroll: str) -> dict[str, Any]:
    """Consume a scroll from inventory to learn the spell it teaches.

    The scroll item must be in your inventory and have a `teaches` prop
    naming a spell. After learning, the scroll is consumed and the spell
    appears in your `known_spells` list.

    Args:
        scroll: The slug of the scroll item (e.g. "scroll_firebolt").
    """
    return {"do": "learn", "scroll": scroll}
