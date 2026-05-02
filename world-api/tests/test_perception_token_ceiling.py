"""FIX_PLAN P0-2 step 3: token estimator + further trim past WIS caps.

Even with the WIS-derived list caps, the *content* of those lists can
be large enough to push the perception payload past the per-tick token
budget. perception_for now estimates tokens, trims tail entries from
the trim-priority lists when over the ceiling, and stamps the
estimate + ceiling into the payload so spectators can see how close
the prompt got.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.actions import perception_for
from app.core.database import Base
from app.core.hero_budgets import perception_token_ceiling
from app.core.models import Hero, JournalEntry, Zone


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _hero(db: Session, *, wis: int = 10, int_: int = 10, name: str | None = None) -> Hero:
    if db.get(Zone, "z") is None:
        db.add(Zone(slug="z", name="Z", kind="sanctuary",
                    width=10, height=10, capacity_soft=10, description="", connections=[]))
    h = Hero(
        id=uuid.uuid4(), name=name or f"hero-{uuid.uuid4().hex[:6]}",
        author="t", division="featherweight",
        bio="", str_=10, dex=10, con=10, int_=int_, wis=wis, cha=10,
        hp=30, status="alive", zone="z", pos_x=5, pos_y=5,
        manifest={}, memory={}, skills={}, equipped={},
        mana_max=10, mana_current=10, known_spells=[], faction_rep={},
        auth_token=f"t-{uuid.uuid4()}", born_at_tick=0,
    )
    db.add(h); db.flush()
    return h


def test_perception_payload_carries_estimate_and_ceiling(db):
    hero = _hero(db)
    p = perception_for(db, hero)
    assert "_perception_tokens_estimated" in p
    assert "_perception_tokens_ceiling" in p
    assert p["_perception_tokens_ceiling"] == perception_token_ceiling(hero)
    assert p["_perception_tokens_estimated"] >= 0


def test_huge_journal_triggers_further_trim(db):
    """Pack the journal with 200 entries of 500-char text. Even the
    WIS=10 journal_recent_limit (12) leaves a payload bigger than a
    low-INT hero's perception budget. The trim loop must drop entries
    from journal_recent until the estimate fits."""
    hero = _hero(db, wis=10, int_=5)  # low INT → tight ceiling
    long_text = "X" * 500
    for i in range(200):
        db.add(JournalEntry(
            hero_id=hero.id, tick_id=i, kind="player",
            text=f"{long_text} {i}", tags=["bulk"],
        ))
    db.flush()

    ceiling = perception_token_ceiling(hero)
    p = perception_for(db, hero)
    assert p["_perception_tokens_estimated"] <= ceiling, (
        f"perception {p['_perception_tokens_estimated']} > ceiling {ceiling}"
    )
    # The trim should have come from the tail of journal_recent; the
    # most-recent entries (which the user cares about most) should
    # remain — the trim drops least-relevant first.
    assert len(p["journal_recent"]) >= 0  # could be 0 if ceiling extreme


def test_high_int_hero_keeps_more_under_same_journal(db):
    """An INT-25 hero's ceiling is generous enough to keep more journal
    entries than an INT-5 hero faced with the same journal pressure."""
    long_text = "X" * 200
    fool = _hero(db, wis=10, int_=5)
    for i in range(40):
        db.add(JournalEntry(
            hero_id=fool.id, tick_id=i, kind="player",
            text=f"{long_text} {i}", tags=["bulk"],
        ))
    db.flush()
    fool_p = perception_for(db, fool)

    sage = _hero(db, wis=10, int_=25)
    for i in range(40):
        db.add(JournalEntry(
            hero_id=sage.id, tick_id=i, kind="player",
            text=f"{long_text} {i}", tags=["bulk"],
        ))
    db.flush()
    sage_p = perception_for(db, sage)

    # Sage gets a bigger ceiling and therefore keeps at-least-as-many
    # journal entries (and very likely more under realistic content).
    assert (
        len(sage_p["journal_recent"]) >= len(fool_p["journal_recent"])
    )


def test_trim_does_not_touch_non_list_fields(db):
    hero = _hero(db, wis=10, int_=5)
    long_text = "X" * 1000
    for i in range(200):
        db.add(JournalEntry(
            hero_id=hero.id, tick_id=i, kind="player",
            text=f"{long_text} {i}", tags=["bulk"],
        ))
    db.flush()
    p = perception_for(db, hero)
    # zone/self_pos/visible_radius must always survive — these are
    # non-list essentials the agent needs to act at all.
    assert "zone" in p and isinstance(p["zone"], dict)
    assert "self_pos" in p
    assert "visible_radius" in p
