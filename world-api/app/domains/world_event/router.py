"""GET /events/current — what's happening in the world right now.

Used by the home page banner. Currently surfaces wyrm state; future calendar
events plug in here without route churn.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Hero, JournalEntry, Recipe, Tick
from app.domains.world_event.wyrm import current_wyrm_status

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/current")
def current_events(db: Annotated[Session, Depends(get_db)]):
    current_tick = int(db.scalar(select(func.max(Tick.id))) or 0)
    from app.domains.world_event.faction_tide import current_tide_status
    return {
        "current_tick": current_tick,
        "wyrm": current_wyrm_status(db, current_tick),
        "tide": current_tide_status(db, current_tick),
    }


@router.get("/discoveries")
def discoveries(db: Annotated[Session, Depends(get_db)], limit: int = 50):
    """Notable discoveries — first-time hidden recipe crafts across the
    world. One entry per recipe (the first hero who found it stays as
    the canonical discoverer). Used by the home page feed and is the
    "wait you can do that?" surface."""
    # `tags` is JSON (not JSONB) so we can't push the filter to SQL — pull
    # recent milestone rows and filter in Python. Cheap because the journal
    # is small and discovery entries are rare.
    rows = list(
        db.scalars(
            select(JournalEntry)
            .where(JournalEntry.kind == "milestone")
            .order_by(JournalEntry.id.asc())
        )
    )
    seen: dict[str, dict] = {}
    for r in rows:
        tags = list(r.tags or [])
        if "discovery" not in tags:
            continue
        # The recipe slug is the non-meta tag — see _resolve_craft.
        recipe_slug = next((t for t in tags if t not in ("milestone", "discovery")), None)
        if not recipe_slug or recipe_slug in seen:
            continue
        hero = db.get(Hero, r.hero_id)
        recipe = db.get(Recipe, recipe_slug)
        seen[recipe_slug] = {
            "recipe_slug": recipe_slug,
            "recipe_name": recipe.name if recipe else recipe_slug,
            "discoverer_hero_id": str(r.hero_id),
            "discoverer_name": hero.name if hero else "unknown",
            "tick_id": r.tick_id,
            "text": r.text,
        }
    out = list(seen.values())
    out.sort(key=lambda d: -int(d["tick_id"] or 0))
    return out[:limit]
