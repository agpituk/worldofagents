"""FIX_PLAN P1-4: dead heroes cannot mutate the world.

The tick loop filters alive heroes when scheduling, but managed bots can
race a death write over WebSocket. Without this guard, a corpse keeps
acting until the next tick boundary — a player watching their hero die
can see it attack one more time, which is both a lore-break and a
combat-correctness bug if the action killed someone.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.actions import resolve
from app.core.database import Base
from app.core.models import Hero, Zone


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed_hero(db: Session, *, status: str = "alive") -> Hero:
    if db.get(Zone, "market_square") is None:
        db.add(Zone(slug="market_square", name="Market", kind="sanctuary",
                    width=20, height=20, capacity_soft=40, description="", connections=[]))
    h = Hero(
        id=uuid.uuid4(), name=f"hero-{status}", author="t", division="featherweight",
        bio="", str_=10, dex=10, con=10, int_=10, wis=10, cha=10,
        hp=30, status=status, zone="market_square", pos_x=5, pos_y=5,
        manifest={}, memory={}, skills={}, equipped={},
        mana_max=10, mana_current=10, known_spells=[],
        faction_rep={}, auth_token=f"tok-{uuid.uuid4()}", born_at_tick=0,
    )
    db.add(h)
    db.flush()
    return h


@pytest.mark.parametrize("verb", ["wait", "look", "move", "attack", "say"])
def test_dead_hero_cannot_act(db, verb):
    """Every verb path must be gated by the alive check, not just some."""
    hero = _seed_hero(db, status="dead")
    result = resolve(db, hero, {"do": verb})
    assert result.ok is False
    assert result.outcome.get("reason") == "dead"


def test_alive_hero_actions_still_resolve(db):
    """Sanity: the guard must not break the happy path."""
    hero = _seed_hero(db, status="alive")
    result = resolve(db, hero, {"do": "wait"})
    assert result.ok is True


def test_status_other_than_alive_or_dead_also_blocked(db):
    """A hero in any non-'alive' status (e.g. quarantined, banned) is
    treated as inactive by the dispatcher — the guard's invariant is
    `alive`, not `not dead`."""
    hero = _seed_hero(db, status="quarantined")
    result = resolve(db, hero, {"do": "wait"})
    assert result.ok is False
    assert result.outcome.get("reason") == "dead"
