"""FIX_PLAN P2-3 + P3-1: typed memory helpers + audit events.

Pins:
  • update_memory does a shallow merge, emits a memory.mutated event
    with {source, diff: {key: {before, after}}}, and skips no-op writes.
  • replace_memory emits with shape='replace', also skipping no-ops.
  • The migration helper bumps memory_schema_version through registered
    migrators and emits one event per step.
  • Existing call sites (gold updates via _set_hero_gold, npc state
    via _set_hero_state) flow through the helper end-to-end.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.actions import _hero_gold, _set_hero_gold
from app.core.database import Base
from app.core.memory import (
    CURRENT_MEMORY_VERSION,
    get_memory,
    migrate_memory_forward,
    register_migration,
    replace_memory,
    update_memory,
)
from app.core.models import Event, Hero, Tick, Zone


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Tick(notes="seed"))
        yield s


def _hero(db: Session, *, memory: dict | None = None) -> Hero:
    if db.get(Zone, "z") is None:
        db.add(Zone(slug="z", name="Z", kind="sanctuary",
                    width=10, height=10, capacity_soft=10, description="", connections=[]))
    h = Hero(
        id=uuid.uuid4(), name=f"h-{uuid.uuid4().hex[:6]}", author="t", division="featherweight",
        bio="", str_=10, dex=10, con=10, int_=10, wis=10, cha=10,
        hp=30, status="alive", zone="z", pos_x=5, pos_y=5,
        manifest={}, memory=memory or {}, skills={}, equipped={},
        mana_max=10, mana_current=10, known_spells=[], faction_rep={},
        auth_token=f"t-{uuid.uuid4()}", born_at_tick=0,
    )
    db.add(h); db.flush()
    return h


# --- get_memory -----------------------------------------------------------


def test_get_memory_safe_on_none(db):
    """A hero whose JSON column momentarily reads as non-dict still works."""
    h = _hero(db)
    h.memory = None  # type: ignore[assignment]
    assert get_memory(h) == {}


# --- update_memory --------------------------------------------------------


def test_update_memory_shallow_merge(db):
    h = _hero(db, memory={"gold": 10, "title": "Newcomer"})
    update_memory(db, h, source="test", gold=20)
    assert h.memory == {"gold": 20, "title": "Newcomer"}


def test_update_memory_emits_event_with_diff(db):
    h = _hero(db, memory={"gold": 10})
    update_memory(db, h, source="bounty_claim", gold=110)
    db.flush()
    events = list(db.scalars(
        select(Event).where(Event.kind == "memory.mutated", Event.hero_id == h.id)
    ))
    assert len(events) == 1
    payload = events[0].payload
    assert payload["source"] == "bounty_claim"
    assert payload["shape"] == "merge"
    assert payload["diff"] == {"gold": {"before": 10, "after": 110}}


def test_update_memory_skips_noop_writes(db):
    """Writing the same value back must not generate an audit event —
    otherwise every per-tick rebuild floods the table."""
    h = _hero(db, memory={"gold": 10})
    update_memory(db, h, source="noop", gold=10)
    db.flush()
    events = list(db.scalars(
        select(Event).where(Event.kind == "memory.mutated", Event.hero_id == h.id)
    ))
    assert events == []


def test_update_memory_diff_only_lists_changed_keys(db):
    """Multiple kwargs should produce a diff that only includes the
    actually-different keys."""
    h = _hero(db, memory={"gold": 10, "title": "x"})
    update_memory(db, h, source="multi", gold=10, title="y")  # gold unchanged
    db.flush()
    e = db.scalar(select(Event).where(Event.kind == "memory.mutated"))
    assert e is not None
    assert set(e.payload["diff"].keys()) == {"title"}


# --- replace_memory --------------------------------------------------------


def test_replace_memory_emits_full_diff(db):
    h = _hero(db, memory={"gold": 10})
    replace_memory(db, h, source="reset", new_memory={"gold": 0, "fresh": True})
    db.flush()
    e = db.scalar(select(Event).where(Event.kind == "memory.mutated"))
    assert e is not None
    assert e.payload["shape"] == "replace"
    assert e.payload["diff"]["_replaced"]["before"] == {"gold": 10}
    assert e.payload["diff"]["_replaced"]["after"] == {"gold": 0, "fresh": True}


# --- end-to-end through _set_hero_gold ------------------------------------


def test_set_hero_gold_emits_audit(db):
    h = _hero(db, memory={"gold": 100})
    _set_hero_gold(db, h, 150, source="trade_accept")
    assert _hero_gold(h) == 150
    db.flush()
    e = db.scalar(select(Event).where(Event.kind == "memory.mutated"))
    assert e is not None
    assert e.payload["source"] == "trade_accept"
    assert e.payload["diff"]["gold"]["after"] == 150


def test_set_hero_gold_floors_at_zero_and_audits(db):
    """Gold can never go negative — the helper clamps and the audit
    reflects the clamped value, not the requested one."""
    h = _hero(db, memory={"gold": 5})
    _set_hero_gold(db, h, -100, source="overdraft_protection")
    assert _hero_gold(h) == 0
    db.flush()
    e = db.scalar(select(Event).where(Event.kind == "memory.mutated"))
    assert e is not None
    assert e.payload["diff"]["gold"]["after"] == 0


# --- migration -------------------------------------------------------------


def test_migrate_no_op_when_already_current(db):
    h = _hero(db)
    h.memory_schema_version = CURRENT_MEMORY_VERSION
    db.flush()
    assert migrate_memory_forward(db, h) is False


def test_migrate_runs_registered_migrators(db, monkeypatch):
    """Stage a migrator that adds a key, run it, assert version bumps
    and event lands."""
    @register_migration(0)  # v0 → v1 in this scenario
    def _v0_to_v1(memory: dict) -> dict:
        memory["migrated"] = True
        return memory

    h = _hero(db, memory={"old": "thing"})
    h.memory_schema_version = 0  # pretend this hero predates v1
    db.flush()
    ran = migrate_memory_forward(db, h)
    assert ran is True
    assert h.memory_schema_version == CURRENT_MEMORY_VERSION
    assert h.memory["migrated"] is True
    db.flush()
    e = db.scalar(select(Event).where(
        Event.kind == "memory.mutated",
        Event.payload["shape"].as_string() == "migration",
    ))
    assert e is not None
