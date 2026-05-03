"""Status effects — apply / read / per-tick decay.

A Status row carries a slug + payload + expiry. Multiple slugs can be
active on a single hero at once. The cast handler writes statuses;
the attack/AC/cast handlers read them via `_active_statuses`; the
tick engine prunes expired rows and applies per-tick payloads
(bleed deals damage, regrowth heals).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actions._helpers import _current_tick
from app.core.dice import roll
from app.core.models import Hero, Status


# Statuses that read each other to compute combat modifiers. Lookup is
# constant-time so we keep this as a flat dict.
#
#   to_hit_bonus     — added to the d20 attack roll for the affected hero.
#   ac_bonus         — added to the affected hero's AC when targeted.
#   stealth          — true while active; reveal effects strip it.
_STATUS_DEFS: dict[str, dict[str, Any]] = {
    "bless":     {"to_hit_bonus": 1},
    "blind":     {"to_hit_bonus": -3},
    "stoneskin": {"ac_bonus": 4},
    "haste":     {},  # cosmetic for now (no per-tick speed); LLM-visible
    "slow":      {},  # cosmetic for now
    "fear":      {"to_hit_bonus": -2},
    "sleep":     {"to_hit_bonus": -10, "ac_bonus": -5},  # roughly auto-fail
    "bleed":     {"per_tick_damage_dice": "1d3"},
    "regrowth":  {"per_tick_heal_dice": "1d3"},
    "stealth":   {"stealth": True},
    "tracking":  {},  # adds a perception line "tracked by <X>"
}


def _apply_status(
    db: Session, target: Hero, *, slug: str, duration_ticks: int,
    source_hero_id: uuid.UUID | None, payload: dict[str, Any] | None = None,
) -> Status:
    """Add or refresh a status on `target`. If a row with the same slug
    already exists, extend its `expires_at_tick` to whichever is later
    (refresh) and merge payload — this keeps reapplied buffs from
    stacking infinitely while letting a longer cast override a shorter
    one."""
    current = _current_tick(db)
    new_expiry = current + max(1, int(duration_ticks))
    existing = db.scalar(
        select(Status).where(Status.hero_id == target.id, Status.slug == slug)
    )
    if existing is not None:
        if existing.expires_at_tick < new_expiry:
            existing.expires_at_tick = new_expiry
        if payload:
            merged = dict(existing.payload or {})
            merged.update(payload)
            existing.payload = merged
        existing.source_hero_id = source_hero_id
        return existing
    s = Status(
        id=uuid.uuid4(),
        hero_id=target.id,
        slug=slug,
        payload=dict(payload or {}),
        applied_at_tick=current,
        expires_at_tick=new_expiry,
        source_hero_id=source_hero_id,
    )
    db.add(s)
    return s


def _active_statuses(db: Session, target: Hero) -> list[Status]:
    """All not-yet-expired statuses on `target`. Note: pruning happens
    in `tick_statuses`; readers should still filter by expires>now in
    case a query lands mid-tick (statuses may be ≤current_tick but
    haven't been pruned yet)."""
    current = _current_tick(db)
    return list(
        db.scalars(
            select(Status).where(
                Status.hero_id == target.id,
                Status.expires_at_tick > current,
            )
        )
    )


def _status_modifier(db: Session, target: Hero, *, kind: str) -> int:
    """Sum the named modifier across all active statuses on `target`.
    `kind` is one of `to_hit_bonus`, `ac_bonus`. Unknown kinds return 0
    so callers can read fearlessly."""
    total = 0
    for s in _active_statuses(db, target):
        defn = _STATUS_DEFS.get(s.slug, {})
        # Payload override beats the default — a powerful caster's
        # bless can write payload={"to_hit_bonus": 2} and we honor it.
        v = (s.payload or {}).get(kind, defn.get(kind, 0))
        if isinstance(v, int):
            total += v
    return total


def tick_statuses(db: Session, current_tick: int) -> None:
    """Apply per-tick payloads (bleed/regrowth) and prune expired rows.

    Called from the world tick once per beat, before action resolution
    so per-tick damage shows up in the same beat the model sees the
    status. Damage from bleed lands on the target's hp directly; we
    skip kill paths for now — bleed-out is a v2.x concern."""
    rows = list(db.scalars(select(Status)))
    for s in rows:
        if s.expires_at_tick <= current_tick:
            db.delete(s)
            continue
        defn = _STATUS_DEFS.get(s.slug, {})
        bleed = (s.payload or {}).get("per_tick_damage_dice") or defn.get("per_tick_damage_dice")
        heal = (s.payload or {}).get("per_tick_heal_dice") or defn.get("per_tick_heal_dice")
        if bleed or heal:
            target = db.get(Hero, s.hero_id)
            if target is None or target.status != "alive":
                continue
            if bleed:
                target.hp = max(0, target.hp - roll(str(bleed)))
            if heal:
                target.hp = min(20 + target.con, target.hp + roll(str(heal)))


def _serialize_status(s: Status) -> dict[str, Any]:
    """Compact form for perception: every active status is surfaced so
    the LLM can decide what to do about it (eg. cast purge_poison if a
    bleed is active)."""
    return {
        "slug": s.slug,
        "expires_at_tick": int(s.expires_at_tick),
        "payload": dict(s.payload or {}),
    }
