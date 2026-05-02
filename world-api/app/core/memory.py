"""Typed accessors + audit emission for hero.memory.

P2-3: hero.memory is schemaless JSON, mutated ad-hoc throughout the
codebase. The first key-shape change breaks in-flight heroes silently.
This module provides:

  • MemoryV1 — TypedDict pinning the shape we ship today.
  • get_memory(hero) → MemoryV1.
  • update_memory(db, hero, source=..., **changes) — shallow merge into
    hero.memory, emit a memory.mutated event, do the SQLAlchemy
    JSON-rebind dance correctly.
  • replace_memory(db, hero, source=..., new_memory=...) — full-blob
    rewrite (rare; main_quest's title award uses this shape).
  • migrate_memory_forward(db, hero) — bumps memory_schema_version
    through registered migrators.

P3-1 piggybacks: every helper write emits a memory.mutated Event with
{source, diff: {key: {before, after}}}. Spectator UIs can render
"hero gained 50 gold (gather → memory.gold 100→150)".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import Event, Tick

if TYPE_CHECKING:
    from app.core.models import Hero

CURRENT_MEMORY_VERSION = 1


class MemoryV1(TypedDict, total=False):
    """The shape the codebase mutates today. `total=False` so heroes
    that haven't accumulated all keys yet still type-check; readers
    must use .get() / default-coalesce."""

    initial: dict[str, Any]
    npcs: dict[str, Any]            # {slug: {"state": str, ...}}
    recall_tags: list[str]
    gold: int
    title: str
    inventory_seen: list[Any]
    discovered_recipes: list[str]
    stash: list[Any]
    main_quest: dict[str, Any]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def get_memory(hero: "Hero") -> MemoryV1:
    """Return the hero's memory blob coerced to a dict.

    Always safe to call (returns {} when memory is None or non-dict).
    Use .get() on the result for individual keys — TypedDict total=False
    means every read can fail-soft to None."""
    data = hero.memory if isinstance(hero.memory, dict) else {}
    return data  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Writes — all paths emit a memory.mutated event for audit
# ---------------------------------------------------------------------------


def _current_tick(db: Session) -> int:
    """Local copy of actions._current_tick so we don't import-cycle."""
    return int(db.scalar(select(func.max(Tick.id))) or 0)


def _emit_mutation(
    db: Session, hero: "Hero", source: str, diff: dict[str, Any], shape: str = "merge"
) -> None:
    db.add(Event(
        tick_id=_current_tick(db),
        hero_id=hero.id,
        zone=hero.zone,
        kind="memory.mutated",
        payload={"source": source, "shape": shape, "diff": diff},
    ))


def update_memory(
    db: Session, hero: "Hero", *, source: str, **changes: Any
) -> None:
    """Shallow merge `changes` into hero.memory.

    For nested keys (e.g. memory['npcs'][slug]['state']), the caller is
    responsible for assembling the new top-level value. The helper only
    promises shallow-merge semantics + audit emission + correct
    SQLAlchemy JSON rebind.
    """
    before = dict(hero.memory) if isinstance(hero.memory, dict) else {}
    after = {**before, **changes}
    diff = {
        k: {"before": before.get(k), "after": after.get(k)}
        for k in changes
        if before.get(k) != after.get(k)
    }
    hero.memory = after
    if diff:  # don't audit no-op writes
        _emit_mutation(db, hero, source, diff)


def replace_memory(
    db: Session, hero: "Hero", *, source: str, new_memory: dict[str, Any]
) -> None:
    """Full-blob rewrite. Audit shape is shape='replace' so a
    spectator UI can distinguish "this whole structure changed" from
    a key-set."""
    before = dict(hero.memory) if isinstance(hero.memory, dict) else {}
    after = dict(new_memory)
    if before == after:
        return
    diff = {"_replaced": {"before": before, "after": after}}
    hero.memory = after
    _emit_mutation(db, hero, source, diff, shape="replace")


# ---------------------------------------------------------------------------
# Forward migrations
# ---------------------------------------------------------------------------


_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def register_migration(
    from_version: int,
) -> Callable[[Callable[[dict[str, Any]], dict[str, Any]]], Callable[[dict[str, Any]], dict[str, Any]]]:
    """Decorator: register a migrator that turns vN memory into v(N+1).

    Example:
        @register_migration(1)
        def _v1_to_v2(memory):
            memory["new_key"] = "default"
            return memory
    """

    def _decorator(fn: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[dict[str, Any]], dict[str, Any]]:
        _MIGRATIONS[from_version] = fn
        return fn

    return _decorator


def migrate_memory_forward(db: Session, hero: "Hero") -> bool:
    """Bring hero.memory up to CURRENT_MEMORY_VERSION by running every
    registered migrator. Returns True if any migration ran. No-op when
    already current. Each step gets its own memory.mutated event so the
    upgrade is auditable per-hero."""
    ran = False
    while hero.memory_schema_version < CURRENT_MEMORY_VERSION:
        v = hero.memory_schema_version
        migrator = _MIGRATIONS.get(v)
        if migrator is None:
            # No migrator from v to v+1 → bump silently. This lets us
            # bump CURRENT_MEMORY_VERSION before all heroes need a real
            # transformation (forward-compat).
            hero.memory_schema_version = v + 1
            continue
        before = dict(hero.memory) if isinstance(hero.memory, dict) else {}
        after = migrator(dict(before))
        hero.memory = after
        hero.memory_schema_version = v + 1
        _emit_mutation(
            db, hero, source=f"migration_v{v}_to_v{v + 1}",
            diff={"_replaced": {"before": before, "after": after}},
            shape="migration",
        )
        ran = True
    return ran
