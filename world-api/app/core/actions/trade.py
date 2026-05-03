"""Merchant buy / sell action verbs."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.actions._helpers import (
    _add_to_inventory,
    _consume_from_inventory,
    _effective_buy_price,
    _effective_sell_price,
    _hero_gold,
    _inventory_total,
    _set_hero_gold,
)
from app.core.actions._result import ResolutionResult
from app.core.models import Hero, NPC


def _resolve_buy(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("target")
    item_slug = action.get("item") or action.get("slug")
    qty = max(1, int(action.get("qty", 1) or 1))
    if not target_slug or not item_slug:
        return ResolutionResult(False, {"verb": "buy", "error": "need target + item"})

    npc = db.get(NPC, str(target_slug))
    if npc is None or npc.zone != hero.zone:
        return ResolutionResult(False, {"verb": "buy", "error": "merchant not in this zone"})
    if abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "buy", "error": "merchant not adjacent"})

    stock_list = list(npc.merchant_stock or [])
    idx = next((i for i, s in enumerate(stock_list) if s.get("slug") == item_slug), None)
    if idx is None or "buy_price" not in stock_list[idx]:
        return ResolutionResult(False, {"verb": "buy", "error": f"merchant doesn't sell '{item_slug}'"})
    entry = stock_list[idx]

    avail = entry.get("qty")
    if avail is not None and int(avail) < qty:
        return ResolutionResult(
            False, {"verb": "buy", "error": f"only {avail} in stock, need {qty}"}
        )

    unit_price = _effective_buy_price(entry)
    total_cost = unit_price * qty
    gold = _hero_gold(hero)
    if gold < total_cost:
        return ResolutionResult(
            False, {"verb": "buy", "error": f"insufficient gold ({gold} < {total_cost})"}
        )

    _set_hero_gold(db, hero, gold - total_cost, source="buy")
    _add_to_inventory(
        db, hero,
        slug=entry["slug"],
        name=entry.get("name", entry["slug"]),
        kind=entry.get("kind", "trinket"),
        props=entry.get("props", {}),
        description=entry.get("description", ""),
        qty=qty,
    )

    if avail is not None:
        new_entry = dict(entry)
        new_entry["qty"] = max(0, int(avail) - qty)
        stock_list[idx] = new_entry
        npc.merchant_stock = stock_list

    return ResolutionResult(
        True,
        {
            "verb": "buy", "from": npc.slug, "item": entry["slug"],
            "qty": qty, "unit_price": unit_price, "total": total_cost,
            "gold_remaining": _hero_gold(hero),
            "stock_remaining": stock_list[idx].get("qty"),
        },
    )


def _resolve_sell(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("target")
    item_slug = action.get("item") or action.get("slug")
    qty = max(1, int(action.get("qty", 1) or 1))
    if not target_slug or not item_slug:
        return ResolutionResult(False, {"verb": "sell", "error": "need target + item"})

    npc = db.get(NPC, str(target_slug))
    if npc is None or npc.zone != hero.zone:
        return ResolutionResult(False, {"verb": "sell", "error": "merchant not in this zone"})
    if abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "sell", "error": "merchant not adjacent"})

    stock_list = list(npc.merchant_stock or [])
    idx = next((i for i, s in enumerate(stock_list) if s.get("slug") == item_slug), None)
    if idx is None or "sell_price" not in stock_list[idx]:
        return ResolutionResult(False, {"verb": "sell", "error": f"merchant doesn't buy '{item_slug}'"})
    entry = stock_list[idx]

    have = _inventory_total(db, hero, item_slug)
    if have < qty:
        return ResolutionResult(False, {"verb": "sell", "error": f"have {have}× {item_slug}, need {qty}"})

    unit_price = _effective_sell_price(entry)
    payout = unit_price * qty
    _consume_from_inventory(db, hero, item_slug, qty)
    _set_hero_gold(db, hero, _hero_gold(hero) + payout, source="sell")

    if entry.get("qty") is not None:
        new_entry = dict(entry)
        new_entry["qty"] = int(entry["qty"]) + qty
        stock_list[idx] = new_entry
        npc.merchant_stock = stock_list

    return ResolutionResult(
        True,
        {
            "verb": "sell", "to": npc.slug, "item": item_slug,
            "qty": qty, "unit_price": unit_price, "total": payout,
            "gold_now": _hero_gold(hero),
            "stock_now": stock_list[idx].get("qty"),
        },
    )
