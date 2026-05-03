"""Social / world-poke action verbs (say, examine, pickup, drop, give).

`give` lives here because it's the in-character delivery action; it
also auto-fulfills delivery / caravan contracts on a successful give,
which is why it imports `_payout_contract` from contracts.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actions._helpers import _current_tick, _inventory_stack
from app.core.actions._result import ResolutionResult
from app.core.actions.contracts import _payout_contract
from app.core.hero_budgets import look_radius
from app.core.models import Contract, Hero, Item, NPC


def _resolve_say(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    message = action.get("message", "")
    if not isinstance(message, str) or not message.strip():
        return ResolutionResult(False, {"verb": "say", "error": "empty message"})
    message = message.strip()[:280]   # cap length

    nearby_npcs = [
        n for n in db.scalars(select(NPC).where(NPC.zone == hero.zone))
        if abs(n.pos_x - hero.pos_x) + abs(n.pos_y - hero.pos_y) <= 1
    ]

    return ResolutionResult(
        True,
        {
            "verb": "say",
            "message": message,
            "heard_by_npcs": [n.slug for n in nearby_npcs],
        },
    )


def _resolve_examine(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target = action.get("target")
    if not target:
        return ResolutionResult(False, {"verb": "examine", "error": "missing target"})

    radius = look_radius(hero)
    npc = db.get(NPC, str(target)) if isinstance(target, str) else None
    if npc and npc.zone == hero.zone and abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) <= radius:
        return ResolutionResult(
            True,
            {
                "verb": "examine",
                "kind": "npc",
                "slug": npc.slug,
                "name": npc.name,
                "description": npc.description,
            },
        )

    try:
        item = db.get(Item, uuid.UUID(str(target)))
    except (ValueError, AttributeError):
        item = None
    if item:
        if item.owner_hero_id == hero.id:
            return ResolutionResult(True, {"verb": "examine", "kind": "item", "name": item.name, "description": item.description, "where": "inventory"})
        if item.zone == hero.zone and item.pos_x is not None and abs(item.pos_x - hero.pos_x) + abs(item.pos_y - hero.pos_y) <= radius:
            return ResolutionResult(True, {"verb": "examine", "kind": "item", "name": item.name, "description": item.description, "where": "ground"})

    return ResolutionResult(False, {"verb": "examine", "error": "target not visible", "target": str(target)})


def _resolve_pickup(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("slug")
    # P1-3: lock candidate ground items so two heroes hitting the same
    # tile in the same tick can't both grab the same stack.
    items_here = list(
        db.scalars(
            select(Item).where(
                Item.zone == hero.zone,
                Item.pos_x == hero.pos_x,
                Item.pos_y == hero.pos_y,
                Item.owner_hero_id.is_(None),
            ).with_for_update()
        )
    )
    if not items_here:
        return ResolutionResult(False, {"verb": "pickup", "error": "no items at this tile"})

    ground = next((i for i in items_here if i.slug == target_slug), items_here[0])
    if ground.owner_hero_id is not None:
        return ResolutionResult(False, {"verb": "pickup", "error": "item already taken"})
    qty = int(ground.quantity or 1)

    existing = _inventory_stack(db, hero, ground.slug)
    if existing is not None:
        existing.quantity = int(existing.quantity or 1) + qty
        db.delete(ground)
    else:
        ground.owner_hero_id = hero.id
        ground.zone = None
        ground.pos_x = None
        ground.pos_y = None
    return ResolutionResult(
        True, {"verb": "pickup", "slug": ground.slug, "name": ground.name, "qty": qty}
    )


def _resolve_drop(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("slug")
    qty_to_drop = int(action.get("qty", 1) or 1)
    item = _inventory_stack(db, hero, target_slug)
    if item is None:
        return ResolutionResult(False, {"verb": "drop", "error": f"no '{target_slug}' in inventory"})

    have = int(item.quantity or 1)
    qty_to_drop = max(1, min(qty_to_drop, have))

    ground_existing = db.scalar(
        select(Item).where(
            Item.zone == hero.zone,
            Item.pos_x == hero.pos_x,
            Item.pos_y == hero.pos_y,
            Item.owner_hero_id.is_(None),
            Item.slug == target_slug,
        )
    )

    if qty_to_drop == have:
        eq = dict(hero.equipped) if isinstance(hero.equipped, dict) else {}
        for slot, slug in list(eq.items()):
            if slug == item.slug:
                eq[slot] = None
        hero.equipped = eq
        if ground_existing is not None:
            ground_existing.quantity = int(ground_existing.quantity or 1) + have
            db.delete(item)
        else:
            item.owner_hero_id = None
            item.zone = hero.zone
            item.pos_x = hero.pos_x
            item.pos_y = hero.pos_y
    else:
        item.quantity = have - qty_to_drop
        if ground_existing is not None:
            ground_existing.quantity = int(ground_existing.quantity or 1) + qty_to_drop
        else:
            db.add(Item(
                id=uuid.uuid4(),
                slug=item.slug, name=item.name, kind=item.kind,
                description=item.description, props=dict(item.props or {}),
                owner_hero_id=None,
                zone=hero.zone, pos_x=hero.pos_x, pos_y=hero.pos_y,
                quantity=qty_to_drop,
            ))
    return ResolutionResult(
        True, {"verb": "drop", "slug": target_slug, "qty": qty_to_drop, "at": [hero.pos_x, hero.pos_y]}
    )


def _resolve_give(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("target")
    item_slug = action.get("item") or action.get("slug")
    if not target_slug or not item_slug:
        return ResolutionResult(False, {"verb": "give", "error": "need target + item"})

    item = next(
        (i for i in db.scalars(select(Item).where(Item.owner_hero_id == hero.id)) if i.slug == item_slug),
        None,
    )
    if item is None:
        return ResolutionResult(False, {"verb": "give", "error": f"no '{item_slug}' in inventory"})

    npc = db.get(NPC, str(target_slug))
    if npc is None or npc.zone != hero.zone or abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "give", "error": "target NPC not adjacent"})

    item.owner_hero_id = None
    item.zone = None
    item.pos_x = None
    item.pos_y = None
    new_props = dict(item.props or {})
    new_props["held_by_npc"] = npc.slug
    item.props = new_props

    # Phase 4: delivery + caravan contract auto-fulfill.
    delivery_payouts: list[dict[str, Any]] = []
    current_tick = _current_tick(db)
    delivery_contracts = list(
        db.scalars(
            select(Contract).where(
                Contract.kind.in_(["delivery", "caravan"]),
                Contract.status == "claimed",
                Contract.claimed_by_hero_id == hero.id,
                Contract.zone_scope == hero.zone,
            )
        )
    )
    for c in delivery_contracts:
        terms = dict(c.terms or {})
        if terms.get("item") != item.slug:
            continue
        if terms.get("dest_npc") != npc.slug:
            continue
        if c.expires_at_tick is not None and current_tick >= c.expires_at_tick:
            c.status = "expired"
            continue
        paid = _payout_contract(db, c, hero, current_tick)
        delivery_payouts.append({
            "contract_id": str(c.id),
            "kind": c.kind,
            "gold": paid,
            "poster": c.poster_name,
        })

    outcome: dict[str, Any] = {"verb": "give", "to": npc.slug, "item": item.slug}
    if delivery_payouts:
        outcome["contracts_fulfilled"] = delivery_payouts
    return ResolutionResult(True, outcome)
