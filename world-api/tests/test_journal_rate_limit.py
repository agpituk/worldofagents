"""FIX_PLAN P2-4: cap journal_write at JOURNAL_WRITE_PER_TICK_LIMIT
player entries per tick.

The archival policy half (move entries older than 10k ticks into a cold
table) is a separate change. The rate limit alone closes the spam
vector — a misbehaving manifest can no longer DoS the journal table by
calling journal_write every primitive step of a composite.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.actions import (
    JOURNAL_WRITE_PER_TICK_LIMIT,
    resolve,
)
from app.core.database import Base
from app.core.models import JournalEntry, Hero, Tick, Zone


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        # Seed the tick counter so _current_tick has something to read.
        s.add(Tick(notes="seed"))
        yield s


def _hero(db: Session) -> Hero:
    if db.get(Zone, "z") is None:
        db.add(Zone(slug="z", name="Z", kind="sanctuary",
                    width=10, height=10, capacity_soft=10, description="", connections=[]))
    h = Hero(
        id=uuid.uuid4(), name="t", author="t", division="featherweight",
        bio="", str_=10, dex=10, con=10, int_=10, wis=10, cha=10,
        hp=30, status="alive", zone="z", pos_x=5, pos_y=5,
        manifest={}, memory={}, skills={}, equipped={},
        mana_max=10, mana_current=10, known_spells=[], faction_rep={},
        auth_token=f"t-{uuid.uuid4()}", born_at_tick=0,
    )
    db.add(h); db.flush()
    return h


def test_writes_under_limit_succeed(db):
    hero = _hero(db)
    for i in range(JOURNAL_WRITE_PER_TICK_LIMIT):
        result = resolve(db, hero, {"do": "journal_write", "text": f"entry {i}"})
        assert result.ok is True, f"entry {i} should have succeeded: {result.outcome}"


def test_write_over_limit_rejected_with_structured_reason(db):
    """The headline P2-4 case: the (limit+1)th journal_write in one tick
    fails with a structured rate-limit reason rather than the entry
    landing silently."""
    hero = _hero(db)
    for i in range(JOURNAL_WRITE_PER_TICK_LIMIT):
        resolve(db, hero, {"do": "journal_write", "text": f"entry {i}"})
    overflow = resolve(db, hero, {"do": "journal_write", "text": "one too many"})
    assert overflow.ok is False
    assert overflow.outcome["reason"] == "journal_rate_limit"
    assert overflow.outcome["limit"] == JOURNAL_WRITE_PER_TICK_LIMIT


def test_overflow_entry_not_persisted(db):
    """No row should land for the rejected attempt — otherwise the rate
    limit is just a warning sticker."""
    hero = _hero(db)
    for i in range(JOURNAL_WRITE_PER_TICK_LIMIT + 5):
        resolve(db, hero, {"do": "journal_write", "text": f"entry {i}"})
    rows = list(db.scalars(
        select(JournalEntry).where(
            JournalEntry.hero_id == hero.id, JournalEntry.kind == "player",
        )
    ))
    assert len(rows) == JOURNAL_WRITE_PER_TICK_LIMIT


def test_limit_resets_at_next_tick(db):
    """Rate limit is per-tick, not lifetime — a hero who used their
    allowance this tick can write again next tick."""
    hero = _hero(db)
    for _ in range(JOURNAL_WRITE_PER_TICK_LIMIT):
        resolve(db, hero, {"do": "journal_write", "text": "x"})
    # Advance the tick.
    db.add(Tick(notes="next"))
    db.flush()
    fresh = resolve(db, hero, {"do": "journal_write", "text": "new tick"})
    assert fresh.ok is True


def test_milestone_entries_do_not_count_against_player_limit(db):
    """The cap is on the player's `kind=player` writes — system milestones
    must not consume the budget or a busy hero can lose their voice."""
    hero = _hero(db)
    # Stuff a tick with milestones (these don't go through journal_write).
    for i in range(50):
        db.add(JournalEntry(
            hero_id=hero.id, tick_id=1, kind="milestone",
            text=f"milestone {i}", tags=[],
        ))
    db.flush()
    # Hero can still spend their full per-tick player budget.
    for i in range(JOURNAL_WRITE_PER_TICK_LIMIT):
        result = resolve(db, hero, {"do": "journal_write", "text": f"entry {i}"})
        assert result.ok is True
