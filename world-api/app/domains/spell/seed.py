"""Seed the spell book."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.models import Spell

log = logging.getLogger("world.spell.seed")

SEED_SPELLS = [
    {
        "slug": "firebolt",
        "name": "Firebolt",
        "description": "A small dart of focused flame. Cheap, reliable.",
        "school": "fire",
        "target_kind": "enemy",   # any hostile NPC or hero in PvP zone
        "mana_cost": 5,
        "range": 4,
        "damage_dice": "1d6",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 0,
    },
    {
        "slug": "mend",
        "name": "Mend",
        "description": "Knit flesh. Restores hp.",
        "school": "heal",
        "target_kind": "self",
        "mana_cost": 4,
        "range": 0,
        "damage_dice": "0d0",
        "heal_dice": "1d6",
        "skill_required": "magic",
        "skill_min": 0,
    },
    {
        "slug": "frost_lance",
        "name": "Frost Lance",
        "description": "A crackling spear of ice. More damage, more mana.",
        "school": "frost",
        "target_kind": "enemy",
        "mana_cost": 8,
        "range": 5,
        "damage_dice": "1d10",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 5,
    },
]


def seed_spells(db: Session) -> None:
    for s in SEED_SPELLS:
        if db.get(Spell, s["slug"]) is None:
            db.add(Spell(**s))
            log.info("seeded spell: %s", s["slug"])
    db.commit()
