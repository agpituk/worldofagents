"""Seed the running tournaments.

For v1.2 we ship one always-open featherweight free-for-all hosted in
Hush Wood. Heroes register inside the zone, kills against other heroes
during the window count, top entry wins the prize when the window closes.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.models import Tournament

log = logging.getLogger("world.tournament.seed")


SEED_TOURNAMENTS = [
    {
        "slug": "hush_wood_featherweight_open",
        "name": "Hush Wood Featherweight Open",
        "description": (
            "Last hero standing — or most kills, if multiple survive. "
            "Featherweight only. Free entry. Pay the wood, the wood pays you back."
        ),
        "division": "featherweight",
        "zone": "hush_wood",
        "status": "open",
        "starts_at_tick": 0,        # already running
        "ends_at_tick": 100_000,    # ~7 days at 6s/tick — effectively long-running
        "max_entries": 32,
        "prize_gold": 250,
        "prize_faction": "council",
        "prize_faction_amount": 15,
    },
]


def seed_tournaments(db: Session) -> None:
    for t in SEED_TOURNAMENTS:
        if db.get(Tournament, t["slug"]) is None:
            db.add(Tournament(**t))
            log.info("seeded tournament: %s", t["slug"])
    db.commit()
