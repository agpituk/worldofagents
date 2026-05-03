"""Sandbox tutorial — opt-out + auto-eviction.

Phase 8 of the build-diversity roadmap. New heroes spawn into a
no-PvP / no-permadeath zone called the Anteroom for ~50 ticks.
`leave_sandbox` is the manual opt-out; `_evict_expired_sandbox_heroes`
is the tick-loop sweeper for "I forgot I was in here" cases.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actions._helpers import _current_tick, _journal_milestone
from app.core.actions._result import ResolutionResult
from app.core.models import Hero, Zone


def _resolve_leave_sandbox(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Manual opt-out from the sandbox tutorial. Drops the hero's
    `protected_until_tick` to now and travels them to market_square.
    No-op (with an informative message) when already past the window."""
    current = _current_tick(db)
    if int(hero.protected_until_tick or 0) <= current:
        return ResolutionResult(
            False,
            {"verb": "leave_sandbox", "error": "no active protection — you're already in the open world"},
        )
    hero.protected_until_tick = current
    if hero.zone == "sandbox":
        target = db.get(Zone, "market_square")
        old_zone = hero.zone
        hero.zone = "market_square"
        if target is not None:
            hero.pos_x = target.width // 2
            hero.pos_y = target.height // 2
        _journal_milestone(
            db, hero,
            text="Stepped out of the Anteroom into Threshold proper.",
            tags=["milestone", "sandbox_exit"],
            dedupe=False,
        )
        return ResolutionResult(
            True,
            {"verb": "leave_sandbox", "from": old_zone, "to": "market_square", "now_at_risk": True},
        )
    return ResolutionResult(
        True,
        {"verb": "leave_sandbox", "from": hero.zone, "to": hero.zone, "now_at_risk": True},
    )


def _evict_expired_sandbox_heroes(db: Session, current_tick: int) -> int:
    """Auto-eviction. Heroes whose protection window has lapsed and who
    are still loitering in the sandbox zone get bumped to market_square.
    Called once per tick. Returns the count evicted so the spectator
    stream can log it."""
    candidates = list(
        db.scalars(
            select(Hero).where(
                Hero.status == "alive",
                Hero.zone == "sandbox",
                Hero.protected_until_tick <= current_tick,
            )
        )
    )
    if not candidates:
        return 0
    target = db.get(Zone, "market_square")
    for h in candidates:
        h.zone = "market_square"
        if target is not None:
            h.pos_x = target.width // 2
            h.pos_y = target.height // 2
        _journal_milestone(
            db, h,
            text="The Anteroom door clicked behind me. The world is real now.",
            tags=["milestone", "sandbox_exit", "auto_evicted"],
            dedupe=False,
        )
    return len(candidates)
