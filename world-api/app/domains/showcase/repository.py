"""Showcase repository — atomic query helpers for the showcase domain.

Holds only DB access. Business logic, scoring, and orchestration live
in `service.py`. Cross-domain reads (Hero, Event) stay here because the
showcase aggregations join across them — moving those to other domain
repositories would create cross-domain calls that are explicitly
disallowed by the architecture rules.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import Event, Hero, HeroTool, ToolCopy, ToolDefinition


# --- ToolDefinition ---------------------------------------------------------


def get_definition(db: Session, tool_id_value: str) -> ToolDefinition | None:
    return db.get(ToolDefinition, tool_id_value)


def list_definitions(db: Session) -> list[ToolDefinition]:
    return list(db.scalars(
        select(ToolDefinition).order_by(ToolDefinition.first_seen_at.desc())
    ))


def first_definition_by_name(db: Session, name: str) -> ToolDefinition | None:
    return db.execute(
        select(ToolDefinition)
        .where(ToolDefinition.name == name)
        .order_by(ToolDefinition.first_seen_at.asc())
        .limit(1)
    ).scalar_one_or_none()


def add_definition(db: Session, defn: ToolDefinition) -> None:
    db.add(defn)


# --- HeroTool ---------------------------------------------------------------


def get_hero_tool(db: Session, hero_id: uuid.UUID, tool_id_value: str) -> HeroTool | None:
    return db.execute(
        select(HeroTool).where(
            HeroTool.hero_id == hero_id,
            HeroTool.tool_id == tool_id_value,
        )
    ).scalar_one_or_none()


def list_users_of_tool(db: Session, tool_id_value: str) -> list[HeroTool]:
    return list(db.scalars(
        select(HeroTool).where(HeroTool.tool_id == tool_id_value)
    ))


def list_hero_tools_for_hero(db: Session, hero_id: uuid.UUID) -> list[HeroTool]:
    return list(db.scalars(select(HeroTool).where(HeroTool.hero_id == hero_id)))


def list_all_hero_tools(db: Session) -> list[HeroTool]:
    return list(db.scalars(select(HeroTool)))


def add_hero_tool(db: Session, ht: HeroTool) -> None:
    db.add(ht)


# --- ToolCopy ---------------------------------------------------------------


def count_copies(db: Session, tool_id_value: str) -> int:
    return db.execute(
        select(func.count(ToolCopy.copy_id))
        .where(ToolCopy.source_tool_id == tool_id_value)
    ).scalar_one() or 0


def copies_grouped(db: Session) -> dict[str, int]:
    return dict(db.execute(
        select(ToolCopy.source_tool_id, func.count(ToolCopy.copy_id))
        .group_by(ToolCopy.source_tool_id)
    ).all())


def most_copied_tool_ids(db: Session, limit: int) -> list[tuple[str, int]]:
    rows = db.execute(
        select(
            ToolCopy.source_tool_id,
            func.count(ToolCopy.copy_id).label("n"),
        )
        .group_by(ToolCopy.source_tool_id)
        .order_by(func.count(ToolCopy.copy_id).desc())
        .limit(limit)
    ).all()
    return [(tid, int(count)) for tid, count in rows]


def add_copy(db: Session, source_tool_id: str, copied_by_hero: uuid.UUID) -> None:
    db.add(ToolCopy(source_tool_id=source_tool_id, copied_by_hero=copied_by_hero))


# --- Hero -------------------------------------------------------------------


def list_alive_heroes(db: Session) -> list[Hero]:
    return list(db.scalars(select(Hero).where(Hero.status == "alive")))


def list_all_heroes(db: Session) -> list[Hero]:
    return list(db.scalars(select(Hero)))


def get_hero_by_id(db: Session, hero_id: uuid.UUID) -> Hero | None:
    return db.get(Hero, hero_id)


def get_hero_by_name(db: Session, name: str) -> Hero | None:
    return db.scalar(select(Hero).where(Hero.name == name))


def get_heroes_by_ids(db: Session, ids: Iterable[uuid.UUID]) -> list[Hero]:
    ids_list = list(ids)
    if not ids_list:
        return []
    return list(db.scalars(select(Hero).where(Hero.id.in_(ids_list))))


# --- Event ------------------------------------------------------------------


def recent_action_events(db: Session, limit: int = 2000) -> list[Event]:
    return list(db.scalars(
        select(Event)
        .where(Event.kind == "action.resolved")
        .order_by(Event.tick_id.desc())
        .limit(limit)
    ))


def aggregate_tool_call_counts(db: Session, limit: int = 2000) -> Counter[str]:
    """Walk the last N action.resolved rows and count tool.expanded
    events per tool name. Lives in repository because it's a pure DB
    walk; the scoring that consumes the counts is in service."""
    counts: Counter[str] = Counter()
    for ev in recent_action_events(db, limit=limit):
        debug = (ev.payload or {}).get("debug") or {}
        for entry in debug.get("tool_events") or []:
            if entry.get("event") != "tool.expanded":
                continue
            tname = (entry.get("payload") or {}).get("tool")
            if isinstance(tname, str):
                counts[tname] += 1
    return counts
