"""Seed quest templates."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.models import QuestTemplate

log = logging.getLogger("world.quest.seed")

SEED_QUESTS = [
    {
        "slug": "rats_in_the_cisterns",
        "name": "Rats in the Cisterns",
        "description": (
            "The Cisterns under the Underspill have been overrun. Three of those "
            "plague-stained rats need to stop being a problem. Bring me their tails — "
            "or just their absence — and I'll pay."
        ),
        "kind": "kill_count",
        "target": "rat_a",   # in v0.7 each kill_count quest tracks one specific slug; v0.8 adds set semantics
        "count_required": 1,
        "reward_gold": 50,
        "reward_faction": "council",
        "reward_faction_amount": 10,
        "offered_by": "ghada",
    },
]


def seed_quests(db: Session) -> None:
    for q in SEED_QUESTS:
        if db.get(QuestTemplate, q["slug"]) is None:
            db.add(QuestTemplate(**q))
            log.info("seeded quest template: %s", q["slug"])
    db.commit()
