"""FIX_PLAN P2-5: shape-check action arguments before dispatch.

Done-when: `{"do":"attack","target":42}` (where target should be a slug)
yields a structured validation error visible on the hero page. The
"visible on the hero page" half lives in tick.py emitting a
parse_failure event with reason='bad_action_shape', covered separately
in test_parse_failure_shape_emission.
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


# --- the headline FIX_PLAN done-when --------------------------------------


def test_attack_with_int_target_rejected_with_structured_error(db):
    hero = _hero(db)
    result = resolve(db, hero, {"do": "attack", "target": 42})
    assert result.ok is False
    assert result.outcome["reason"] == "bad_action_shape"
    assert "target" in result.outcome["error"]
    assert "str" in result.outcome["error"]  # error names the expected type
    assert "int" in result.outcome["error"]  # and the wrong one received


# --- coverage across the verb schema map ----------------------------------


@pytest.mark.parametrize("action,reason_field", [
    ({"do": "attack"}, "target"),
    ({"do": "attack_hero"}, "target"),
    ({"do": "move"}, "target"),
    ({"do": "move", "target": "northeast"}, "target"),  # str instead of list
    ({"do": "travel"}, "zone"),
    ({"do": "say"}, "message"),
    ({"do": "give"}, "target"),
    ({"do": "give", "target": "marek"}, "item"),
    ({"do": "buy", "target": "marek", "item": "scroll", "qty": "two"}, "qty"),
    ({"do": "cast"}, "spell"),
    ({"do": "accept_offer", "offer_id": 1234}, "offer_id"),
])
def test_bad_shape_caught(db, action, reason_field):
    hero = _hero(db)
    result = resolve(db, hero, action)
    assert result.ok is False, f"action {action!r} should have been rejected"
    assert result.outcome["reason"] == "bad_action_shape"
    assert reason_field in result.outcome["error"]


# --- the schema doesn't false-positive on legal actions -------------------


@pytest.mark.parametrize("action", [
    {"do": "wait"},
    {"do": "look"},
    {"do": "defend"},
    {"do": "say", "message": "hi"},
    {"do": "buy", "target": "marek", "item": "scroll"},  # qty optional
    {"do": "cast", "spell": "firebolt"},                  # target optional
    {"do": "move", "target": [3, 4]},
    {"do": "move", "target": (3, 4)},                     # tuple ok too
])
def test_well_shaped_actions_pass_validation(db, action):
    """The validator must not change the dispatch path for valid actions —
    if any of these now fail at the validator step, the validator is
    overreaching."""
    hero = _hero(db)
    result = resolve(db, hero, action)
    # We don't care if downstream rejects (e.g. buying from a non-existent
    # NPC) — only that the failure isn't from the shape validator itself.
    if not result.ok:
        assert result.outcome.get("reason") != "bad_action_shape"


def test_unknown_verb_still_falls_through_to_unknown_verb(db):
    """Unknown verbs hit the dispatcher's unknown_verb branch, not the
    shape validator. (Schema map only covers known verbs.)"""
    hero = _hero(db)
    result = resolve(db, hero, {"do": "yodel", "target": "moon"})
    assert result.ok is False
    assert result.outcome["reason"] == "unknown_verb"
