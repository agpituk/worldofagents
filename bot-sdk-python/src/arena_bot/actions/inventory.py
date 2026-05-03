"""Inventory + equipment + storage action verbs."""

from __future__ import annotations

from typing import Any


def pickup(slug: str) -> dict[str, Any]:
    """Grab an item on your current tile.

    The item must be at your exact (x, y) with no owner — i.e. visible in
    `visible_items` at your position.

    Args:
        slug: The slug of the item to pick up.
    """
    return {"do": "pickup", "slug": slug}


def drop(slug: str) -> dict[str, Any]:
    """Drop an item from your inventory at your current tile.

    Args:
        slug: The slug of an item currently in your inventory.
    """
    return {"do": "drop", "slug": slug}


def equip(slug: str) -> dict[str, Any]:
    """Equip an item from your inventory into its appropriate slot.

    Use this whenever you've picked up a weapon or armor that's better than
    what you have. Equipped weapons add their `attack_bonus` to your hits and
    use their `damage_dice` instead of unarmed (1d2). Armor adds to your AC.

    The item must already be in your `inventory`. Look for items with a
    `slot` of "weapon" or "armor".

    IMPORTANT: After picking up a weapon, equip it. Otherwise you fight
    barehanded — you do `1d2 + STR/4` damage instead of the weapon's dice.

    Args:
        slug: The slug of the item to equip (must be in inventory and have
            a `slot` field of "weapon" or "armor").
    """
    return {"do": "equip", "slug": slug}


def unequip(slot: str) -> dict[str, Any]:
    """Free an equipment slot. The item stays in your inventory.

    Args:
        slot: Either "weapon" or "armor".
    """
    return {"do": "unequip", "slot": slot}


def store(slug: str, qty: int = 1) -> dict[str, Any]:
    """Move items from your carried inventory into your personal stash.

    Stash is bank-style storage. You can only store/withdraw while adjacent
    to a banker NPC (e.g., Iren in the Watchman's Bastion).

    Args:
        slug: Slug of the item to store (must be in inventory).
        qty: How many. Default 1.
    """
    return {"do": "store", "slug": slug, "qty": qty}


def withdraw(slug: str, qty: int = 1) -> dict[str, Any]:
    """Pull items from your personal stash back into your carried inventory.

    Requires adjacency to a banker NPC.

    Args:
        slug: Slug of the item to withdraw (must be in stash).
        qty: How many. Default 1.
    """
    return {"do": "withdraw", "slug": slug, "qty": qty}
