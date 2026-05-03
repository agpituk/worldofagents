"""Movement action verbs (move, travel)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.actions._helpers import _journal_milestone, _move_speed
from app.core.actions._result import ResolutionResult
from app.core.models import Hero, Zone


def _resolve_travel(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target = action.get("zone")
    if not isinstance(target, str):
        return ResolutionResult(False, {"verb": "travel", "error": "zone must be a string"})
    current = db.get(Zone, hero.zone)
    if current is None:
        return ResolutionResult(False, {"verb": "travel", "error": f"unknown current zone {hero.zone}"})
    connections = current.connections or []
    if target not in connections:
        return ResolutionResult(
            False,
            {"verb": "travel", "error": f"{target} is not adjacent to {hero.zone}", "connections": connections},
        )
    dest = db.get(Zone, target)
    if dest is None:
        return ResolutionResult(False, {"verb": "travel", "error": f"unknown destination zone {target}"})

    old_zone = hero.zone
    hero.zone = target
    hero.pos_x = dest.width // 2
    hero.pos_y = dest.height // 2
    _journal_milestone(
        db, hero,
        text=f"First time in {dest.name}. {dest.description[:140]}",
        tags=["milestone", "first_visit", target],
    )
    return ResolutionResult(
        True,
        {"verb": "travel", "from": old_zone, "to": target, "arrived_at": [hero.pos_x, hero.pos_y]},
    )


def _resolve_move(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target = action.get("target")
    if not (isinstance(target, list) and len(target) == 2):
        return ResolutionResult(False, {"verb": "move", "error": "target must be [x, y]"})
    try:
        tx, ty = int(target[0]), int(target[1])
    except (TypeError, ValueError):
        return ResolutionResult(False, {"verb": "move", "error": "target must be ints"})

    zone = db.get(Zone, hero.zone)
    if zone is None:
        return ResolutionResult(False, {"verb": "move", "error": f"unknown zone {hero.zone}"})
    if not (0 <= tx < zone.width and 0 <= ty < zone.height):
        return ResolutionResult(
            False,
            {"verb": "move", "error": "target out of zone bounds", "bounds": [zone.width, zone.height]},
        )

    speed = _move_speed(hero)
    dx, dy = tx - hero.pos_x, ty - hero.pos_y
    if abs(dx) + abs(dy) > speed:
        remaining = speed
        if abs(dx) >= abs(dy):
            step_x = max(-remaining, min(remaining, dx))
            remaining -= abs(step_x)
            step_y = max(-remaining, min(remaining, dy))
        else:
            step_y = max(-remaining, min(remaining, dy))
            remaining -= abs(step_y)
            step_x = max(-remaining, min(remaining, dx))
        tx, ty = hero.pos_x + step_x, hero.pos_y + step_y

    old = (hero.pos_x, hero.pos_y)
    hero.pos_x, hero.pos_y = tx, ty
    return ResolutionResult(True, {"verb": "move", "from": list(old), "to": [tx, ty]})
