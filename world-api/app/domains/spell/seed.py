"""Seed the spell book.

Phase 2 of the build-diversity roadmap expanded the surface from 3
spells (firebolt / frost_lance / mend) to a wider set covering damage
single-target / damage AoE-ish / heal-utility / buff / debuff /
mobility / summon / detection. Each spell declares an `effect_kind`
that picks the resolver in `app.core.actions`:

  damage_or_heal — the v0.6 path (firebolt, frost_lance, mend)
  apply_status   — write a Status row on the target
  dispel         — strip negative statuses
  move_self      — blink to a target tile
  move_target    — push a hero
  summon_npc     — spawn a temporary mob next to caster
  reveal         — strip stealth from heroes in range
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.models import Spell

log = logging.getLogger("world.spell.seed")

SEED_SPELLS = [
    # ── Damage / single-target ──────────────────────────────────────────
    {
        "slug": "firebolt",
        "name": "Firebolt",
        "description": "A small dart of focused flame. Cheap, reliable.",
        "school": "fire",
        "target_kind": "enemy",
        "mana_cost": 5,
        "range": 4,
        "damage_dice": "1d6",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 0,
        "effect_kind": "damage_or_heal",
        "payload": {},
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
        "effect_kind": "damage_or_heal",
        "payload": {},
    },
    {
        "slug": "shock_arc",
        "name": "Shock Arc",
        "description": "A short whip of lightning at melee range — quick, no aim.",
        "school": "storm",
        "target_kind": "enemy",
        "mana_cost": 4,
        "range": 1,
        "damage_dice": "1d8",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 2,
        "effect_kind": "damage_or_heal",
        "payload": {},
    },
    # ── Heal / utility ──────────────────────────────────────────────────
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
        "effect_kind": "damage_or_heal",
        "payload": {},
    },
    {
        "slug": "purge_poison",
        "name": "Purge Poison",
        "description": "Strip bleeds, poisons, and lingering hexes from a hero.",
        "school": "heal",
        "target_kind": "hero",
        "mana_cost": 6,
        "range": 3,
        "damage_dice": "0d0",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 4,
        "effect_kind": "dispel",
        "payload": {"slugs": ["bleed", "blind", "fear", "slow", "sleep"]},
    },
    {
        "slug": "regrowth",
        "name": "Regrowth",
        "description": "A creeping bloom that heals a hero a little each tick.",
        "school": "heal",
        "target_kind": "hero",
        "mana_cost": 6,
        "range": 3,
        "damage_dice": "0d0",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 3,
        "effect_kind": "apply_status",
        "payload": {"status": "regrowth", "duration_ticks": 8},
    },
    # ── Buffs ───────────────────────────────────────────────────────────
    {
        "slug": "stoneskin",
        "name": "Stoneskin",
        "description": "Hardens flesh against blows. +AC for several ticks.",
        "school": "stone",
        "target_kind": "self",
        "mana_cost": 7,
        "range": 0,
        "damage_dice": "0d0",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 4,
        "effect_kind": "apply_status",
        "payload": {"status": "stoneskin", "duration_ticks": 12},
    },
    {
        "slug": "bless",
        "name": "Bless",
        "description": "An ally fights with steadier hands. +1 to hit.",
        "school": "heal",
        "target_kind": "hero",
        "mana_cost": 5,
        "range": 3,
        "damage_dice": "0d0",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 2,
        "effect_kind": "apply_status",
        "payload": {"status": "bless", "duration_ticks": 15},
    },
    # ── Debuff / control ────────────────────────────────────────────────
    {
        "slug": "blind",
        "name": "Blind",
        "description": "A flash of grit and light. Target swings wide for a while.",
        "school": "shadow",
        "target_kind": "enemy",
        "mana_cost": 6,
        "range": 3,
        "damage_dice": "0d0",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 3,
        "effect_kind": "apply_status",
        "payload": {"status": "blind", "duration_ticks": 6},
    },
    {
        "slug": "fear",
        "name": "Fear",
        "description": "Whispers of dread. Target's resolve cracks.",
        "school": "shadow",
        "target_kind": "enemy",
        "mana_cost": 6,
        "range": 3,
        "damage_dice": "0d0",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 3,
        "effect_kind": "apply_status",
        "payload": {"status": "fear", "duration_ticks": 8},
    },
    # ── Mobility ────────────────────────────────────────────────────────
    {
        "slug": "blink",
        "name": "Blink",
        "description": "A short displacement. Choose any tile within range.",
        "school": "arcane",
        "target_kind": "enemy",  # target is [x, y]
        "mana_cost": 5,
        "range": 4,
        "damage_dice": "0d0",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 5,
        "effect_kind": "move_self",
        "payload": {},
    },
    {
        "slug": "gust",
        "name": "Gust",
        "description": "A blast of wind that shoves a target back.",
        "school": "storm",
        "target_kind": "enemy",
        "mana_cost": 4,
        "range": 3,
        "damage_dice": "0d0",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 2,
        "effect_kind": "move_target",
        "payload": {"push_tiles": 2},
    },
    # ── Summon ──────────────────────────────────────────────────────────
    {
        "slug": "summon_wisp",
        "name": "Summon Wisp",
        "description": "A weak, glowing scout that follows you. Distracts foes.",
        "school": "arcane",
        "target_kind": "self",
        "mana_cost": 8,
        "range": 0,
        "damage_dice": "0d0",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 4,
        "effect_kind": "summon_npc",
        "payload": {"mob": "wisp", "name": "Glimmering Wisp", "hp": 1},
    },
    # ── Detection ───────────────────────────────────────────────────────
    {
        "slug": "reveal",
        "name": "Reveal",
        "description": "A pulse of bright sight. Strips stealth from nearby heroes.",
        "school": "arcane",
        "target_kind": "self",
        "mana_cost": 5,
        "range": 4,
        "damage_dice": "0d0",
        "heal_dice": "0d0",
        "skill_required": "magic",
        "skill_min": 3,
        "effect_kind": "reveal",
        "payload": {},
    },
]


def seed_spells(db: Session) -> None:
    for s in SEED_SPELLS:
        existing = db.get(Spell, s["slug"])
        if existing is None:
            db.add(Spell(**s))
            log.info("seeded spell: %s", s["slug"])
        else:
            # Refresh effect_kind + payload on existing rows so the
            # roadmap's expanded spells take effect after re-seed.
            existing.effect_kind = s["effect_kind"]
            existing.payload = s["payload"]
    db.commit()
