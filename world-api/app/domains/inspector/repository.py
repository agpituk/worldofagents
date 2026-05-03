"""Inspector queries over the Event table.

Read-only. The inspector domain owns these queries because the data
shape (`action.resolved` rows with `debug.tool_events` lists) is its
internal concern — other domains write the events through the tick
engine and don't care how the inspector slices them.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Event, Hero


def hero_manifest(db: Session, hid: uuid.UUID) -> dict[str, Any]:
    h = db.get(Hero, hid)
    return (h.manifest if h else None) or {}


def recent_resolved(db: Session, hid: uuid.UUID, *, limit: int) -> list[Event]:
    return list(db.scalars(
        select(Event).where(
            Event.hero_id == hid, Event.kind == "action.resolved",
        ).order_by(Event.tick_id.desc()).limit(limit)
    ))


def resolved_at_tick(db: Session, hid: uuid.UUID, tick: int) -> list[Event]:
    return list(db.scalars(
        select(Event).where(
            Event.hero_id == hid,
            Event.kind == "action.resolved",
            Event.tick_id == tick,
        )
    ))
