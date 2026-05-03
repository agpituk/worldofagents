"""Inventory + journaling action verbs.

Covers: journal_write (with rate limit), store/withdraw via banker NPC,
buy_house. Equipment swaps live in `equipment.py`; trade with merchants
lives in `trade.py`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.actions._helpers import (
    _add_to_inventory,
    _consume_from_inventory,
    _current_tick,
    _hero_gold,
    _inventory_stack,
    _inventory_total,
    _journal_milestone,
    _set_hero_gold,
)
from app.core.actions._result import ResolutionResult
from app.core.models import Building, Hero, Item, JournalEntry, NPC


JOURNAL_WRITE_PER_TICK_LIMIT = 4


def _resolve_journal_write(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """The hero records their own thought into their journal.

    P2-4: capped at JOURNAL_WRITE_PER_TICK_LIMIT player entries per tick.
    Without this a misbehaving manifest can spam the table forever; the
    archival job belongs in a separate change but the rate limit closes
    the spam vector immediately.
    """
    text = (action.get("text") or "").strip()
    if not text:
        return ResolutionResult(False, {"verb": "journal_write", "error": "empty text"})
    text = text[:600]
    tags = action.get("tags") or []
    if not isinstance(tags, list):
        return ResolutionResult(False, {"verb": "journal_write", "error": "tags must be a list"})
    tags = [str(t)[:32] for t in tags][:8]
    tick_id = _current_tick(db)

    db.flush()  # make sure earlier writes within this tick are visible to count
    existing_this_tick = db.scalar(
        select(func.count(JournalEntry.id)).where(
            JournalEntry.hero_id == hero.id,
            JournalEntry.tick_id == tick_id,
            JournalEntry.kind == "player",
        )
    ) or 0
    if existing_this_tick >= JOURNAL_WRITE_PER_TICK_LIMIT:
        return ResolutionResult(
            False,
            {
                "verb": "journal_write",
                "error": f"rate limit: max {JOURNAL_WRITE_PER_TICK_LIMIT} player entries per tick",
                "reason": "journal_rate_limit",
                "limit": JOURNAL_WRITE_PER_TICK_LIMIT,
            },
        )

    db.add(JournalEntry(hero_id=hero.id, tick_id=tick_id, kind="player", text=text, tags=tags))
    # Push to the retriever (no-op for SqlRetriever; cq.propose for CqRetriever).
    from app.core.retriever import get_retriever
    get_retriever().record(db, hero_id=hero.id, text=text, tags=tags, tick_id=tick_id, kind="player")
    return ResolutionResult(True, {"verb": "journal_write", "text": text, "tags": tags})


def _adjacent_banker(db: Session, hero: Hero) -> NPC | None:
    """Return an adjacent peaceful NPC of kind='banker' if any."""
    return next(
        (
            n for n in db.scalars(select(NPC).where(NPC.zone == hero.zone, NPC.kind == "banker"))
            if abs(n.pos_x - hero.pos_x) + abs(n.pos_y - hero.pos_y) <= 1
        ),
        None,
    )


def _resolve_store(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Move N of `slug` from inventory to the hero's personal stash. Must be
    adjacent to a banker NPC (the only access point in v0.9)."""
    target_slug = str(action.get("slug") or "")
    qty = max(1, int(action.get("qty", 1) or 1))
    if not target_slug:
        return ResolutionResult(False, {"verb": "store", "error": "missing slug"})
    if _adjacent_banker(db, hero) is None:
        return ResolutionResult(False, {"verb": "store", "error": "must be adjacent to a banker"})

    have = _inventory_total(db, hero, target_slug)
    if have < qty:
        return ResolutionResult(False, {"verb": "store", "error": f"have {have}× {target_slug}, need {qty}"})

    template = _inventory_stack(db, hero, target_slug)
    if template is None:
        return ResolutionResult(False, {"verb": "store", "error": "inventory item missing"})
    name, kind, props, description = template.name, template.kind, dict(template.props or {}), template.description
    _consume_from_inventory(db, hero, target_slug, qty)

    existing_stash = db.scalar(
        select(Item).where(Item.stash_owner_hero_id == hero.id, Item.slug == target_slug)
    )
    if existing_stash is not None:
        existing_stash.quantity = int(existing_stash.quantity or 1) + qty
    else:
        db.add(Item(
            id=uuid.uuid4(),
            slug=target_slug, name=name, kind=kind, props=props, description=description,
            owner_hero_id=None, zone=None, pos_x=None, pos_y=None,
            stash_owner_hero_id=hero.id, quantity=qty,
        ))
    return ResolutionResult(True, {"verb": "store", "slug": target_slug, "qty": qty})


def _resolve_withdraw(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Pull N of `slug` from stash back into inventory. Banker required."""
    target_slug = str(action.get("slug") or "")
    qty = max(1, int(action.get("qty", 1) or 1))
    if not target_slug:
        return ResolutionResult(False, {"verb": "withdraw", "error": "missing slug"})
    if _adjacent_banker(db, hero) is None:
        return ResolutionResult(False, {"verb": "withdraw", "error": "must be adjacent to a banker"})

    stash = db.scalar(
        select(Item).where(Item.stash_owner_hero_id == hero.id, Item.slug == target_slug)
    )
    if stash is None or int(stash.quantity or 1) < qty:
        avail = int(stash.quantity or 0) if stash else 0
        return ResolutionResult(False, {"verb": "withdraw", "error": f"have {avail}× {target_slug} in stash, need {qty}"})

    name, kind, props, description = stash.name, stash.kind, dict(stash.props or {}), stash.description
    stash.quantity = int(stash.quantity or 1) - qty
    if stash.quantity <= 0:
        db.delete(stash)
    _add_to_inventory(
        db, hero,
        slug=target_slug, name=name, kind=kind, props=props, description=description, qty=qty,
    )
    return ResolutionResult(True, {"verb": "withdraw", "slug": target_slug, "qty": qty})


def _resolve_buy_house(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Buy a building. Must be adjacent to it. Pays gold, becomes owner."""
    slug = str(action.get("slug") or "")
    if not slug:
        return ResolutionResult(False, {"verb": "buy_house", "error": "missing slug"})
    b = db.get(Building, slug)
    if b is None or b.zone != hero.zone:
        return ResolutionResult(False, {"verb": "buy_house", "error": "building not here"})
    if b.owner_hero_id is not None:
        owner_match = b.owner_hero_id == hero.id
        return ResolutionResult(False, {"verb": "buy_house", "error": "already owned" + (" by you" if owner_match else "")})
    in_or_near = (
        b.pos_x - 1 <= hero.pos_x <= b.pos_x + b.width
        and b.pos_y - 1 <= hero.pos_y <= b.pos_y + b.height
    )
    if not in_or_near:
        return ResolutionResult(False, {"verb": "buy_house", "error": "not adjacent to the building"})

    gold = _hero_gold(hero)
    if gold < b.gold_cost:
        return ResolutionResult(False, {"verb": "buy_house", "error": f"insufficient gold ({gold} < {b.gold_cost})"})

    _set_hero_gold(db, hero, gold - b.gold_cost, source="buy_house")
    b.owner_hero_id = hero.id
    _journal_milestone(
        db, hero,
        text=f"Bought {b.name} in {b.zone.replace('_', ' ')}. A roof of my own.",
        tags=["milestone", "house_purchased", b.slug],
    )
    return ResolutionResult(
        True,
        {"verb": "buy_house", "slug": b.slug, "name": b.name, "paid": b.gold_cost, "gold_remaining": _hero_gold(hero)},
    )
