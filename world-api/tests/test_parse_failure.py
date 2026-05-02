"""FIX_PLAN P0-3 done-when (server-side slice).

The bot's parse failure becomes a `parse_failure` event in the per-hero
event stream. The dispatcher's "unknown verb" path becomes the same
shape so a malformed model output and a model that hallucinates a verb
both surface uniformly in spectator UIs.

These tests cover the world-api half of the fix:

  • resolve(unknown verb) marks the result as ok=False with a structured
    reason="unknown_verb" outcome (used by tick.py to emit the event).
  • The router's parse_failure event-emission logic, exercised against
    a synthetic submission carrying debug.parse_error.

The bot SDK half of the fix lives in
bot-sdk-python/tests/test_parse_json_action.py.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.actions import resolve
from app.core.database import Base
from app.core.models import Event, Hero, Zone


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed_hero(db: Session) -> Hero:
    db.add(Zone(slug="market_square", name="Market", kind="sanctuary",
                width=20, height=20, capacity_soft=40, description="", connections=[]))
    h = Hero(
        id=uuid.uuid4(), name="t", author="t", division="featherweight",
        bio="", str_=10, dex=10, con=10, int_=10, wis=10, cha=10,
        hp=30, status="alive", zone="market_square", pos_x=5, pos_y=5,
        manifest={}, memory={}, skills={}, equipped={},
        mana_max=10, mana_current=10, known_spells=[],
        faction_rep={}, auth_token="tok", born_at_tick=0,
    )
    db.add(h)
    db.flush()
    return h


def test_unknown_verb_outcome_carries_reason(db):
    """tick.py reads result.outcome['reason'] to decide whether to emit a
    parse_failure event. If this contract drifts, that emission breaks."""
    hero = _seed_hero(db)
    result = resolve(db, hero, {"do": "yodel"})
    assert result.ok is False
    assert result.outcome.get("reason") == "unknown_verb"
    assert result.outcome.get("verb") == "yodel"


def test_known_verb_does_not_carry_unknown_verb_reason(db):
    """Sanity: a real verb's failure (e.g. wrong arg) shouldn't get
    misclassified as unknown_verb."""
    hero = _seed_hero(db)
    result = resolve(db, hero, {"do": "wait"})
    assert result.ok is True
    assert result.outcome.get("reason") != "unknown_verb"


def _emulate_tick_event_emission(db: Session, hero: Hero, action: dict, result) -> None:
    """The piece of tick.py that emits action.resolved + parse_failure on
    unknown_verb. Lifted here so the test pins the expected event shape
    independently of the scheduler."""
    db.add(Event(
        tick_id=1, hero_id=hero.id, zone=hero.zone,
        kind="action.resolved",
        payload={"action": action, "ok": result.ok, "outcome": result.outcome,
                 "kind": "llm", "debug": None},
    ))
    if not result.ok and result.outcome.get("reason") == "unknown_verb":
        db.add(Event(
            tick_id=1, hero_id=hero.id, zone=hero.zone,
            kind="parse_failure",
            payload={
                "reason": "unknown_verb",
                "raw_output": str(action)[:500],
                "fallback_action": {"do": "wait"},
            },
        ))


def test_unknown_verb_emits_parse_failure_event(db):
    hero = _seed_hero(db)
    action = {"do": "yodel", "target": "moon"}
    result = resolve(db, hero, action)
    _emulate_tick_event_emission(db, hero, action, result)
    db.flush()

    parse_failures = list(db.scalars(
        select(Event).where(Event.kind == "parse_failure", Event.hero_id == hero.id)
    ))
    assert len(parse_failures) == 1
    payload = parse_failures[0].payload
    assert payload["reason"] == "unknown_verb"
    assert "yodel" in payload["raw_output"]
    assert payload["fallback_action"] == {"do": "wait"}


# --- router-side parse_failure emission (bot-side parse error) ------------


def _emulate_router_parse_failure_emission(
    db: Session, hero: Hero, *, action: dict, debug: dict
) -> None:
    """The piece of hero/router.py:_handle_inbound that emits a
    parse_failure event when an inbound action submission carries
    debug.parse_error. Lifted out so we can test it without the
    WebSocket plumbing."""
    if isinstance(debug, dict) and debug.get("parse_error"):
        db.add(Event(
            tick_id=1, hero_id=hero.id, zone=None,
            kind="parse_failure",
            payload={
                "reason": str(debug.get("parse_error")),
                "raw_output": str(debug.get("raw_output", ""))[:500],
                "fallback_action": action,
            },
        ))


def test_bot_parse_error_in_debug_emits_parse_failure_event(db):
    """A model that emitted unparseable text → bot SDK fell back to wait
    and stamped debug.parse_error → router emits a parse_failure row
    that the spectator stream renders distinctly from the wait."""
    hero = _seed_hero(db)
    _emulate_router_parse_failure_emission(
        db, hero,
        action={"do": "wait"},
        debug={"parse_error": "no_json_found", "raw_output": "I'm thinking..."},
    )
    db.flush()

    parse_failures = list(db.scalars(
        select(Event).where(Event.kind == "parse_failure", Event.hero_id == hero.id)
    ))
    assert len(parse_failures) == 1
    payload = parse_failures[0].payload
    assert payload["reason"] == "no_json_found"
    assert "I'm thinking" in payload["raw_output"]
    assert payload["fallback_action"] == {"do": "wait"}


def test_no_parse_error_in_debug_emits_no_event(db):
    hero = _seed_hero(db)
    _emulate_router_parse_failure_emission(
        db, hero,
        action={"do": "attack", "target": "rat_a"},
        debug={"reflex_index": 2, "when": "hostile_visible"},  # normal reflex debug
    )
    db.flush()

    parse_failures = list(db.scalars(
        select(Event).where(Event.kind == "parse_failure")
    ))
    assert parse_failures == []
