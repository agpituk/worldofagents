"""Equipment slot swaps — equip / unequip from inventory."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actions._result import ResolutionResult
from app.core.models import Hero, Item


def _resolve_equip(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("slug")
    if not target_slug:
        return ResolutionResult(False, {"verb": "equip", "error": "missing slug"})
    item = next(
        (i for i in db.scalars(select(Item).where(Item.owner_hero_id == hero.id)) if i.slug == target_slug),
        None,
    )
    if item is None:
        return ResolutionResult(False, {"verb": "equip", "error": f"no '{target_slug}' in inventory"})
    slot = (item.props or {}).get("slot")
    if slot not in ("weapon", "armor"):
        return ResolutionResult(False, {"verb": "equip", "error": f"item is not equippable (slot={slot!r})"})

    eq = dict(hero.equipped) if isinstance(hero.equipped, dict) else {}
    previous = eq.get(slot)
    eq[slot] = item.slug
    hero.equipped = eq
    return ResolutionResult(
        True, {"verb": "equip", "slot": slot, "slug": item.slug, "replaced": previous}
    )


def _resolve_unequip(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    slot = action.get("slot")
    if slot not in ("weapon", "armor"):
        return ResolutionResult(False, {"verb": "unequip", "error": "slot must be 'weapon' or 'armor'"})
    eq = dict(hero.equipped) if isinstance(hero.equipped, dict) else {}
    prev = eq.get(slot)
    if not prev:
        return ResolutionResult(False, {"verb": "unequip", "error": f"slot {slot} is empty"})
    eq[slot] = None
    hero.equipped = eq
    return ResolutionResult(True, {"verb": "unequip", "slot": slot, "removed": prev})
