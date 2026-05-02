"""Seed the world's zones — Threshold + nearby frontier."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.models import Zone

log = logging.getLogger("world.zone.seed")


SEED_ZONES: list[dict] = [
    # ── Threshold proper (sanctuaries) ───────────────────────────────────
    {
        "slug": "market_square",
        "name": "Market Square",
        "kind": "sanctuary",
        "width": 10, "height": 10, "capacity_soft": 40,
        "description": (
            "The middle terrace of Threshold. Stalls, gossip, the Cracked One muttering "
            "names of heroes who haven't yet arrived. New heroes spawn here."
        ),
        "connections": ["cracked_tankard", "watchmans_bastion", "embered_shrine", "lantern_road"],
    },
    {
        "slug": "cracked_tankard",
        "name": "The Cracked Tankard",
        "kind": "sanctuary",
        "width": 8, "height": 8, "capacity_soft": 30,
        "description": "Marek's tavern. Smoke, low ceilings, a fire that never quite goes out.",
        "connections": ["market_square"],
    },
    {
        "slug": "watchmans_bastion",
        "name": "Watchman's Bastion",
        "kind": "sanctuary",
        "width": 8, "height": 8, "capacity_soft": 25,
        "description": "Upper Vault guard post. Bounty board, hire hall, Captain Ghada's office.",
        "connections": ["market_square", "codex_hall"],
    },
    {
        "slug": "codex_hall",
        "name": "Codex Hall",
        "kind": "sanctuary",
        "width": 10, "height": 10, "capacity_soft": 20,
        "description": "Library and Warden chapter house. Magistra Vela's domain.",
        "connections": ["watchmans_bastion"],
    },
    {
        "slug": "embered_shrine",
        "name": "The Embered Shrine",
        "kind": "sanctuary",
        "width": 6, "height": 6, "capacity_soft": 15,
        "description": "Underspill heretical shrine. Brother Jossen teaches dangerous things here.",
        "connections": ["market_square", "old_cisterns"],
    },
    # ── Frontier ────────────────────────────────────────────────────────
    {
        "slug": "lantern_road",
        "name": "The Lantern Road",
        "kind": "frontier",
        "width": 14, "height": 6, "capacity_soft": 15,
        "description": "Mid-danger road north of Threshold. Bandits have grown bold.",
        "connections": ["market_square", "hush_wood", "tideway_docks"],
    },
    {
        "slug": "hush_wood",
        "name": "Hush Wood",
        "kind": "frontier",
        "width": 12, "height": 12, "capacity_soft": 15,
        "description": "Old forest. Herbs, low-mid mobs, the occasional druid.",
        "connections": ["lantern_road"],
    },
    {
        "slug": "tideway_docks",
        "name": "Tideway Docks",
        "kind": "frontier",
        "width": 12, "height": 8, "capacity_soft": 12,
        "description": (
            "Salt-bleached pier and deeper water beyond. Threshold's maritime "
            "edge — a reek of bait, rope, and brine. Fishers work the planks "
            "near shore; the brave wade out to the deep-water posts."
        ),
        "connections": ["lantern_road"],
    },
    # ── Dungeon ─────────────────────────────────────────────────────────
    {
        "slug": "old_cisterns",
        "name": "The Old Cisterns",
        "kind": "dungeon",
        "width": 8, "height": 8, "capacity_soft": 6,
        "description": "Underground beneath the Underspill. Tutorial dungeon — rats and worse.",
        "connections": ["embered_shrine"],
    },
]


def seed_zones(db: Session) -> None:
    for z in SEED_ZONES:
        existing = db.get(Zone, z["slug"])
        if existing is None:
            db.add(Zone(**z))
            log.info("seeded zone: %s", z["slug"])
        else:
            # Refresh connections in case the seed changed since first run.
            existing.connections = z["connections"]
    db.commit()
