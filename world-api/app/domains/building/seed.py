"""Seed buildings."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.models import Building

log = logging.getLogger("world.building.seed")

SEED_BUILDINGS = [
    {
        "slug": "humble_cottage_marketsq",
        "name": "Humble Cottage",
        "kind": "house",
        "zone": "market_square",
        "pos_x": 1, "pos_y": 7,
        "width": 2, "height": 2,
        "gold_cost": 200,
        "description": "Two rooms, a cold hearth, a window facing the Market Square. Cheap.",
    },
    {
        "slug": "warden_loft_codexhall",
        "name": "Warden Loft",
        "kind": "house",
        "zone": "codex_hall",
        "pos_x": 6, "pos_y": 6,
        "width": 2, "height": 2,
        "gold_cost": 600,
        "description": "Above the Codex Hall annex. Quiet. Smells of vellum and cold stone.",
    },
]


def seed_buildings(db: Session) -> None:
    for b in SEED_BUILDINGS:
        if db.get(Building, b["slug"]) is None:
            db.add(Building(**b))
            log.info("seeded building: %s @ %s", b["slug"], b["zone"])
    db.commit()
