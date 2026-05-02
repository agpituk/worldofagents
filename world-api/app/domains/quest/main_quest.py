"""The main quest arc — every new hero's starter story.

The Warden's Recruit chain plants identity on Day 1: it gives the hero a
reason to walk into Lantern Road, a reason to gather iron, and a reason to
visit Captain Ghada at the bastion. On completion of step 2, the hero earns
the title "Warden's Recruit" — a cosmetic badge persisted in `hero.memory`
and rendered on the public hero page.

Implementation: each step is a regular `QuestTemplate` row using the existing
kill_count / gather_count machinery. The first step is auto-granted on
registration; subsequent steps are auto-granted when the previous step is
claimed (via `advance_main_quest`, called from `_resolve_claim_reward`).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Hero, Quest, QuestTemplate

log = logging.getLogger("world.quest.main")


# Ordered chain. Each row matches QuestTemplate columns. `next_slug` is the
# template to auto-grant on claim (None = end of chain). `award_title` is the
# cosmetic title written to hero.memory["title"] on this step's claim.
MAIN_QUEST_CHAIN = [
    {
        "slug": "recruit_step_1_blood",
        "name": "The Recruit's First Blood",
        "description": (
            "Captain Ghada won't speak to a stranger. Prove the world is in "
            "a state worth speaking about — bring her the body of an Embered "
            "cultist. They prowl the Lantern Road. Take the road north."
        ),
        "kind": "kill_count",
        "target": "embered_cultist_a",
        "count_required": 1,
        "reward_gold": 60,
        "reward_faction": "council",
        "reward_faction_amount": 3,
        "offered_by": "ghada",
        "next_slug": "recruit_step_2_supply",
        "award_title": None,
    },
    {
        "slug": "recruit_step_2_supply",
        "name": "Supply the Bastion",
        "description": (
            "The Watchman's forge runs on iron. Bring two ore to the Captain "
            "and she'll vouch for you with the Council. There's a vein near "
            "Hush Wood — pick a swing."
        ),
        "kind": "gather_count",
        "target": "iron_ore",
        "count_required": 2,
        "reward_gold": 120,
        "reward_faction": "council",
        "reward_faction_amount": 7,
        "offered_by": "ghada",
        "next_slug": None,
        "award_title": "Warden's Recruit",
    },
]


def seed_main_quest(db: Session) -> None:
    """Idempotently seed the main quest chain into QuestTemplate."""
    for row in MAIN_QUEST_CHAIN:
        # Strip our chain-only fields before inserting; QuestTemplate doesn't
        # know about next_slug / award_title.
        if db.get(QuestTemplate, row["slug"]) is None:
            tpl_row = {k: v for k, v in row.items() if k not in ("next_slug", "award_title")}
            db.add(QuestTemplate(**tpl_row))
            log.info("seeded main-quest step: %s", row["slug"])
    db.commit()


def auto_grant_first_quest(db: Session, hero: Hero) -> None:
    """Called from HeroService.register. Grants the hero step 1 of the
    main quest immediately — no NPC visit required to start the story."""
    first = MAIN_QUEST_CHAIN[0]
    db.add(Quest(
        id=uuid.uuid4(),
        hero_id=hero.id,
        template_slug=first["slug"],
        status="active",
        count_done=0,
    ))


def advance_main_quest(db: Session, hero: Hero, claimed_slug: str) -> dict | None:
    """Called from `_resolve_claim_reward` whenever a quest is claimed. If the
    claimed quest is part of the main chain:
      • grant the next step (if any),
      • award the title (if this step has one).
    Returns a dict describing what was awarded, or None if this wasn't a
    main-quest step. The caller folds this into the action's outcome so the
    spectator stream sees the milestone."""
    step = next((s for s in MAIN_QUEST_CHAIN if s["slug"] == claimed_slug), None)
    if step is None:
        return None

    awarded: dict = {"main_quest_step": claimed_slug}

    if step["award_title"]:
        from app.core.memory import update_memory

        mem = hero.memory if isinstance(hero.memory, dict) else {}
        titles = list(mem.get("titles") or [])
        if step["award_title"] not in titles:
            titles.append(step["award_title"])
        update_memory(
            db, hero,
            source=f"main_quest_step:{step['slug']}",
            titles=titles,
            # Convenience pointer to the *latest* title for UI rendering.
            title=step["award_title"],
        )
        awarded["title"] = step["award_title"]

    next_slug = step.get("next_slug")
    if next_slug:
        # Don't double-grant if the hero already has it (shouldn't happen but
        # defensive against bug-driven double-claims).
        existing = db.scalar(
            select(Quest).where(
                Quest.hero_id == hero.id, Quest.template_slug == next_slug
            )
        )
        if existing is None:
            db.add(Quest(
                id=uuid.uuid4(),
                hero_id=hero.id,
                template_slug=next_slug,
                status="active",
                count_done=0,
            ))
            awarded["next_quest"] = next_slug

    return awarded
