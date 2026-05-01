"""Faction Tide — the weekly calendar heartbeat.

Every `TIDE_PERIOD_TICKS`, we tally the faction reputation gained by all
alive heroes during the window and crown the leading faction. The leader
"claims" a contested zone (today: Lantern Road) — a banner on the home page
shows current control and the countdown to the next tide.

Tides accumulate by sniffing journal milestones tagged `["faction", <name>]`
which `_grant_rep` already emits at threshold crossings. We additionally
infer per-hero rep change by snapshotting the world's faction_rep at the
start of each window and diffing at the end.

State lives in two append-only Event rows:
  • `world.tide.opened`    — written when a new window begins
  • `world.tide.closed`    — written when the window resolves; payload includes
                             the winning faction, totals, and the claimed zone
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Event, Hero

log = logging.getLogger("world.tide")


TIDE_PERIOD_TICKS = 7000              # ~12h real-time at 6s/tick
CONTESTED_ZONE = "lantern_road"       # the zone the winning faction "claims"
TRACKED_FACTIONS = ("wardens", "council", "embered")


def _last_tide(db: Session, kind: str) -> Event | None:
    return db.scalar(
        select(Event).where(Event.kind == kind).order_by(Event.id.desc()).limit(1)
    )


def _snapshot_faction_rep(db: Session) -> dict[str, int]:
    """Sum every hero's current rep per faction. The diff between two
    snapshots = total movement during the window."""
    out: dict[str, int] = {f: 0 for f in TRACKED_FACTIONS}
    for h in db.scalars(select(Hero)):
        rep = h.faction_rep or {}
        for f in TRACKED_FACTIONS:
            out[f] += int(rep.get(f, 0) or 0)
    return out


def tick_faction_tide(db: Session, current_tick: int) -> None:
    """Schedule entry. Idempotent — the windowing keys off the last
    `world.tide.opened` event, so restarts don't double-fire."""
    last_open = _last_tide(db, "world.tide.opened")
    if last_open is None:
        # Bootstrap: open the very first tide window.
        db.add(Event(
            tick_id=current_tick, hero_id=None, zone=None,
            kind="world.tide.opened",
            payload={
                "snapshot": _snapshot_faction_rep(db),
                "ends_at_tick": current_tick + TIDE_PERIOD_TICKS,
            },
        ))
        log.info("tide bootstrapped at t%d", current_tick)
        return

    opened_at = int(last_open.tick_id)
    payload = last_open.payload or {}
    ends_at = int(payload.get("ends_at_tick") or (opened_at + TIDE_PERIOD_TICKS))
    if current_tick < ends_at:
        return

    # Window is up — close it.
    snapshot_now = _snapshot_faction_rep(db)
    snapshot_then = payload.get("snapshot") or {}
    deltas = {
        f: snapshot_now.get(f, 0) - int(snapshot_then.get(f, 0) or 0)
        for f in TRACKED_FACTIONS
    }
    # Winner: largest positive delta. Ties broken alphabetically (deterministic).
    winner = max(TRACKED_FACTIONS, key=lambda f: (deltas.get(f, 0), -ord(f[0])))
    if deltas.get(winner, 0) <= 0:
        # Nobody gained ground — the zone goes uncontrolled.
        winner = None  # type: ignore[assignment]

    db.add(Event(
        tick_id=current_tick, hero_id=None, zone=CONTESTED_ZONE,
        kind="world.tide.closed",
        payload={
            "winner": winner, "deltas": deltas, "claimed_zone": CONTESTED_ZONE,
            "opened_at_tick": opened_at,
        },
    ))
    # Open the next window immediately so the heartbeat is continuous.
    db.add(Event(
        tick_id=current_tick, hero_id=None, zone=None,
        kind="world.tide.opened",
        payload={
            "snapshot": snapshot_now,
            "ends_at_tick": current_tick + TIDE_PERIOD_TICKS,
        },
    ))
    log.info("tide closed: winner=%s deltas=%s", winner, deltas)


def current_tide_status(db: Session, current_tick: int) -> dict:
    """Read-only — used by /events/current."""
    last_open = _last_tide(db, "world.tide.opened")
    last_close = _last_tide(db, "world.tide.closed")
    if last_open is None:
        return {"active": False, "reason": "not_yet_started"}
    payload = last_open.payload or {}
    snapshot_then = payload.get("snapshot") or {}
    snapshot_now = _snapshot_faction_rep(db)
    leading_deltas = {
        f: snapshot_now.get(f, 0) - int(snapshot_then.get(f, 0) or 0)
        for f in TRACKED_FACTIONS
    }
    leader = max(TRACKED_FACTIONS, key=lambda f: leading_deltas.get(f, 0))
    if leading_deltas.get(leader, 0) <= 0:
        leader = None  # type: ignore[assignment]

    last_winner = None
    if last_close is not None:
        last_winner = (last_close.payload or {}).get("winner")

    ends_at = int(payload.get("ends_at_tick") or (last_open.tick_id + TIDE_PERIOD_TICKS))
    return {
        "active": True,
        "opened_at_tick": last_open.tick_id,
        "ends_at_tick": ends_at,
        "ticks_remaining": max(0, ends_at - current_tick),
        "leading_faction": leader,
        "leading_deltas": leading_deltas,
        "contested_zone": CONTESTED_ZONE,
        "last_winner": last_winner,
    }
