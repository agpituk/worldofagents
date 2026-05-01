"""Seed world items.

For v0.5 we drop a few starter items in sanctuaries so heroes can pick them
up and learn the equip/unequip loop. Once crafting lands in v0.5.1 most
items will be player-made.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Item

log = logging.getLogger("world.item.seed")

# Static starter items. Keyed by slug + zone+pos so we don't re-seed if they're
# picked up and dropped elsewhere — the (slug, zone, pos) tuple is the seed key.
SEED_ITEMS = [
    {
        "slug": "iron_sword",
        "name": "Iron Sword",
        "kind": "weapon",
        "description": "A simple iron blade. Honest steel, no enchantment.",
        "props": {"slot": "weapon", "damage_dice": "1d8", "attack_bonus": 1},
        "zone": "cracked_tankard",
        "pos_x": 2,
        "pos_y": 4,
    },
    {
        "slug": "leather_jerkin",
        "name": "Leather Jerkin",
        "kind": "armor",
        "description": "Cured hide stitched onto a linen liner. Smells faintly of tannin.",
        "props": {"slot": "armor", "ac_bonus": 2},
        "zone": "watchmans_bastion",
        "pos_x": 2,
        "pos_y": 4,
    },
]


def seed_items(db: Session) -> None:
    for spec in SEED_ITEMS:
        # Only seed if no copy of this slug exists anywhere in the world.
        existing = db.scalar(select(Item).where(Item.slug == spec["slug"]))
        if existing is not None:
            continue
        db.add(
            Item(
                id=uuid.uuid4(),
                slug=spec["slug"],
                name=spec["name"],
                kind=spec["kind"],
                description=spec["description"],
                props=spec["props"],
                owner_hero_id=None,
                zone=spec["zone"],
                pos_x=spec["pos_x"],
                pos_y=spec["pos_y"],
            )
        )
        log.info("seeded item: %s @ %s", spec["slug"], spec["zone"])
    db.commit()
