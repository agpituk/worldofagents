"""Movement action verbs."""

from __future__ import annotations

from typing import Any


def move(target: list[int]) -> dict[str, Any]:
    """Walk to a tile in your CURRENT zone.

    Use this to close distance on a target who is visible but NOT adjacent
    (manhattan > 1). Cannot move outside zone bounds. Cannot leave the zone
    — use `travel` for inter-zone movement.

    IMPORTANT: Do NOT call move if a hostile NPC is at manhattan <= 1 from you
    — call `attack` instead. Do NOT call move to leave a zone — call `travel`.

    Args:
        target: Two-element [x, y] coordinates of the destination tile.
            Must be within the current zone's size (zone_info.size).
    """
    return {"do": "move", "target": target}


def travel(zone: str) -> dict[str, Any]:
    """Walk to an ADJACENT zone.

    Use when the entity you need is in another zone. The destination must be
    in `zone_info.connections` of your current zone. Travel takes one tick
    and drops you at the centre of the destination zone.

    Args:
        zone: The slug of an adjacent zone. MUST appear in
            zone_info.connections (e.g., if you're in market_square and
            connections == ["cracked_tankard", "watchmans_bastion", ...],
            you can travel to any of those).
    """
    return {"do": "travel", "zone": zone}
