"""Economy / commerce action verbs."""

from __future__ import annotations

from typing import Any


def buy(target: str, item: str, qty: int = 1) -> dict[str, Any]:
    """Buy an item from an adjacent merchant NPC.

    The merchant must be at manhattan ≤ 1, must have `merchant_stock` listing
    the item, and you must have enough gold (memory.gold). Each merchant has
    different `buy_price` per item; you pay buy_price × qty.

    Args:
        target: Slug of the merchant NPC (e.g., "marek", "ghada").
        item: Slug of the item to buy (must appear in their stock).
        qty: How many to buy. Default 1.
    """
    return {"do": "buy", "target": target, "item": item, "qty": qty}


def sell(target: str, item: str, qty: int = 1) -> dict[str, Any]:
    """Sell an item from your inventory to an adjacent merchant.

    The merchant must be at manhattan ≤ 1, must have `merchant_stock` listing
    the item, and you must have enough of the item. Each merchant has
    different `sell_price`; you receive sell_price × qty in gold.

    Args:
        target: Slug of the merchant NPC.
        item: Slug of the item to sell (must be in your inventory).
        qty: How many to sell. Default 1.
    """
    return {"do": "sell", "target": target, "item": item, "qty": qty}


def buy_house(slug: str) -> dict[str, Any]:
    """Buy an unowned building. Pays gold from `memory.gold`. Sets you as the
    building's owner; the world records a milestone in your journal.

    You must be standing on or adjacent to the building's footprint.

    Args:
        slug: Slug of the building (e.g. "humble_cottage_marketsq").
    """
    return {"do": "buy_house", "slug": slug}
