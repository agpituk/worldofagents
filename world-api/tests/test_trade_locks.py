"""FIX_PLAN P1-3: shared-asset transfers re-check inside the critical
section.

These tests don't (and can't) prove SQLite-level row locking — SQLite
serialises all writes anyway. They prove the LOGIC is right: the
status/ownership check happens *after* the lock fetch, so a state
flip between fetch and write is caught and the second writer bails
with a structured error rather than handing out ghost items.

Once Postgres is the test database (P1-2/Postgres-fixture follow-up),
the same tests run against real concurrent transactions.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.actions import resolve
from app.core.database import Base
from app.core.models import Hero, Item, TradeOffer, Zone


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed(db: Session) -> tuple[Hero, Hero]:
    db.add(Zone(slug="z", name="Z", kind="sanctuary",
                width=10, height=10, capacity_soft=10, description="", connections=[]))
    a = Hero(
        id=uuid.uuid4(), name="alice", author="t", division="featherweight",
        bio="", str_=10, dex=10, con=10, int_=10, wis=10, cha=10,
        hp=30, status="alive", zone="z", pos_x=5, pos_y=5,
        manifest={}, memory={"gold": 100}, skills={}, equipped={},
        mana_max=10, mana_current=10, known_spells=[], faction_rep={},
        auth_token="ta", born_at_tick=0,
    )
    b = Hero(
        id=uuid.uuid4(), name="bob", author="t", division="featherweight",
        bio="", str_=10, dex=10, con=10, int_=10, wis=10, cha=10,
        hp=30, status="alive", zone="z", pos_x=5, pos_y=5,
        manifest={}, memory={"gold": 100}, skills={}, equipped={},
        mana_max=10, mana_current=10, known_spells=[], faction_rep={},
        auth_token="tb", born_at_tick=0,
    )
    db.add_all([a, b])
    db.flush()
    return a, b


# --- TradeOffer accept TOCTOU ----------------------------------------------


def test_accept_offer_twice_in_a_row_second_bails(db):
    """The headline P1-3 case: alice and bob each have 50 gold; alice
    offers bob 30 gold for nothing. Bob accepts. Bob accepts again. The
    second accept must NOT pay out — that's the ghost-item duplication
    the lock + recheck prevents."""
    alice, bob = _seed(db)
    offer = TradeOffer(
        id=uuid.uuid4(), from_hero_id=alice.id, to_hero_id=bob.id,
        offered_items=[], offered_gold=30, wanted_items=[], wanted_gold=0,
        status="pending", expires_at_tick=0,
    )
    db.add(offer)
    db.flush()

    first = resolve(db, bob, {"do": "accept_offer", "offer_id": str(offer.id)})
    assert first.ok is True, first.outcome
    second = resolve(db, bob, {"do": "accept_offer", "offer_id": str(offer.id)})
    assert second.ok is False
    assert "accepted" in second.outcome["error"]


def test_accept_offer_status_flipped_externally_is_caught(db):
    """Even if status flipped via a side channel between fetches the
    re-check inside the critical section bails."""
    alice, bob = _seed(db)
    offer = TradeOffer(
        id=uuid.uuid4(), from_hero_id=alice.id, to_hero_id=bob.id,
        offered_items=[], offered_gold=10, wanted_items=[], wanted_gold=0,
        status="pending", expires_at_tick=0,
    )
    db.add(offer)
    db.flush()

    # Flip status to expired before the accept hits the row.
    offer.status = "expired"
    db.flush()

    result = resolve(db, bob, {"do": "accept_offer", "offer_id": str(offer.id)})
    assert result.ok is False
    assert "expired" in result.outcome["error"]


# --- pickup TOCTOU ---------------------------------------------------------


def test_pickup_after_item_already_owned_is_caught(db):
    """If an item shows as ground-state in our query but was claimed by
    another transaction before our write, the re-check bails with a
    structured error rather than transferring ownership again."""
    alice, _bob = _seed(db)
    item = Item(
        id=uuid.uuid4(), slug="iron_ingot", name="Iron Ingot", kind="material",
        description="", props={}, owner_hero_id=None,
        zone="z", pos_x=5, pos_y=5, quantity=1,
    )
    db.add(item)
    db.flush()
    # Pretend another transaction won the race after our query selected
    # this row (in-test we mutate it directly; in prod the row lock
    # serialises, the re-check catches the rare residual case).
    item.owner_hero_id = uuid.uuid4()
    db.flush()

    # The query inside _resolve_pickup re-runs and sees no eligible
    # ground items — pickup bails cleanly.
    result = resolve(db, alice, {"do": "pickup", "slug": "iron_ingot"})
    assert result.ok is False
    assert "no items" in result.outcome["error"] or "already taken" in result.outcome["error"]
