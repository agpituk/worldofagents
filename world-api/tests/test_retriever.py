"""FIX_PLAN P3-4: cover the retriever's fall-through behaviour.

retriever.py:99-208 has multiple fall-through paths (cq down →
SqlRetriever, cq-exchange HTTP error → SqlRetriever, _build_retriever
init failure → SqlRetriever). Without tests, a misconfigured cq
silently serves SQL results — the world *appears* to be running on cq
while actually using the SQL fallback. These tests pin both the happy
paths and the fallthroughs.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.models import Hero, JournalEntry, Zone
from app.core.retriever import (
    CqRetriever,
    SqlRetriever,
    _build_retriever,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _hero_with_journal(db: Session) -> Hero:
    if db.get(Zone, "z") is None:
        db.add(Zone(slug="z", name="Z", kind="sanctuary",
                    width=10, height=10, capacity_soft=10, description="", connections=[]))
    h = Hero(
        id=uuid.uuid4(), name="r", author="t", division="featherweight",
        bio="", str_=10, dex=10, con=10, int_=10, wis=10, cha=10,
        hp=30, status="alive", zone="z", pos_x=5, pos_y=5,
        manifest={}, memory={}, skills={}, equipped={},
        mana_max=10, mana_current=10, known_spells=[], faction_rep={},
        auth_token=f"tk-{uuid.uuid4()}", born_at_tick=0,
    )
    db.add(h)
    # Seed a small corpus.
    for i, (text, tags) in enumerate([
        ("Met Marek the smith near the forge.", ["marek", "smith"]),
        ("Killed a rat in the alley.", ["combat", "rat"]),
        ("Marek owes me a sword.", ["marek", "deal"]),
        ("Bought scroll of firebolt.", ["scroll"]),
    ]):
        db.add(JournalEntry(
            hero_id=h.id, tick_id=i, kind="player", text=text, tags=tags,
        ))
    db.flush()
    return h


# --- SqlRetriever happy path ----------------------------------------------


def test_sql_recall_returns_tag_matches(db):
    """Tag-tagged entries score the highest and surface in the limited
    result. Lower-scoring entries can also appear because of the
    recency boost (see test_sql_recall_recency_floor below for that
    quirk pinned), but tag matches dominate."""
    hero = _hero_with_journal(db)
    out = SqlRetriever().recall(db, hero_id=hero.id, tags=["marek"], limit=2)
    texts = {r["text"] for r in out}
    # The two top-scored results are the marek-tagged ones — score 7
    # (5 from tag match + 2 recency) vs 2 (recency only) for the rest.
    assert any("Met Marek" in t for t in texts)
    assert any("Marek owes me" in t for t in texts)


def test_sql_recall_recency_floor(db):
    """Pinning a known retriever quirk: every entry within the recent
    200 gets a +2 recency boost regardless of tag/term match, so a
    tag-only query with NO matching entries still returns recent ones
    by recency alone. Documented here so a future "tighten the
    retriever" change can intentionally break this test rather than
    silently change perception behaviour."""
    hero = _hero_with_journal(db)
    out = SqlRetriever().recall(db, hero_id=hero.id, tags=["nonexistent"], limit=10)
    # All 4 seeded entries surface (score 2 each from recency).
    assert len(out) == 4
    assert all(r["score"] >= 1 for r in out)


def test_sql_recall_substring_match(db):
    hero = _hero_with_journal(db)
    out = SqlRetriever().recall(db, hero_id=hero.id, query="firebolt")
    texts = {r["text"] for r in out}
    assert any("scroll of firebolt" in t for t in texts)


def test_sql_recall_respects_limit(db):
    hero = _hero_with_journal(db)
    out = SqlRetriever().recall(db, hero_id=hero.id, tags=["marek"], limit=1)
    assert len(out) == 1


def test_sql_recall_empty_when_no_journal(db):
    """A hero with no journal entries gets an empty recall regardless
    of how the query is shaped. (Combined with the recency floor pin
    above this distinguishes "no candidates" from "no matches but some
    recent entries.")"""
    if db.get(Zone, "z") is None:
        db.add(Zone(slug="z", name="Z", kind="sanctuary",
                    width=10, height=10, capacity_soft=10, description="", connections=[]))
    h = Hero(
        id=uuid.uuid4(), name="silent", author="t", division="featherweight",
        bio="", str_=10, dex=10, con=10, int_=10, wis=10, cha=10,
        hp=30, status="alive", zone="z", pos_x=5, pos_y=5,
        manifest={}, memory={}, skills={}, equipped={},
        mana_max=10, mana_current=10, known_spells=[], faction_rep={},
        auth_token=f"tk-{uuid.uuid4()}", born_at_tick=0,
    )
    db.add(h); db.flush()
    out = SqlRetriever().recall(db, hero_id=h.id, tags=["anything"])
    assert out == []


# --- CqRetriever fallthrough ----------------------------------------------


class _FailingCq:
    """A cq client that raises on every call. Models a misconfigured /
    network-flapping cq install."""

    def query(self, **_kwargs: Any) -> Any:
        raise RuntimeError("cq is down")

    def propose(self, **_kwargs: Any) -> Any:
        raise RuntimeError("cq is down")


def test_cq_recall_falls_back_to_sql_on_failure(db, caplog):
    """The headline P3-4 claim: a misconfigured cq must NOT silently
    return empty — it must fall back to SQL AND log a warning so the
    fallthrough is at least audit-trail-able."""
    hero = _hero_with_journal(db)
    cq = CqRetriever(_FailingCq())
    with caplog.at_level(logging.WARNING, logger="world.retriever"):
        out = cq.recall(db, hero_id=hero.id, tags=["marek"])
    # Got SQL results despite cq failing.
    texts = {r["text"] for r in out}
    assert any("Marek" in t for t in texts), out
    # The fallthrough left a log so an operator can spot it.
    assert any("cq.query failed" in r.message for r in caplog.records)


def test_cq_propose_swallows_errors_quietly_with_log(db, caplog):
    """Propose failures should not raise (would crash journal_write);
    they log and move on."""
    hero = _hero_with_journal(db)
    cq = CqRetriever(_FailingCq())
    with caplog.at_level(logging.WARNING, logger="world.retriever"):
        cq.record(db, hero_id=hero.id, text="test", tags=[], tick_id=0, kind="player")
    assert any("cq.propose failed" in r.message for r in caplog.records)


# --- _build_retriever environment switching --------------------------------


def test_build_default_returns_sql(monkeypatch):
    """No env vars set → SqlRetriever. The world's default boot path."""
    monkeypatch.delenv("CQ_EXCHANGE_ENABLED", raising=False)
    monkeypatch.delenv("CQ_ENABLED", raising=False)
    r = _build_retriever()
    assert isinstance(r, SqlRetriever)


def test_build_cq_exchange_missing_creds_falls_through(monkeypatch, caplog):
    """CQ_EXCHANGE_ENABLED but no URL/key/namespace → warning + SQL fallback.
    The previous bug shape: enabling cq-exchange via env without setting
    creds appeared to work (no error) while silently using SQL."""
    monkeypatch.setenv("CQ_EXCHANGE_ENABLED", "1")
    monkeypatch.delenv("CQ_EXCHANGE_URL", raising=False)
    monkeypatch.delenv("CQ_ENABLED", raising=False)
    with caplog.at_level(logging.WARNING, logger="world.retriever"):
        r = _build_retriever()
    assert isinstance(r, SqlRetriever)
    assert any("CQ_EXCHANGE_ENABLED" in record.message for record in caplog.records)


def test_build_cq_enabled_but_unimportable_falls_through(monkeypatch, caplog):
    """CQ_ENABLED set but `cq` package missing → warning + SQL fallback."""
    monkeypatch.setenv("CQ_ENABLED", "1")
    monkeypatch.delenv("CQ_EXCHANGE_ENABLED", raising=False)
    # Sandbox doesn't have `cq` installed; the import will fail.
    with caplog.at_level(logging.WARNING, logger="world.retriever"):
        r = _build_retriever()
    assert isinstance(r, SqlRetriever)
    assert any(
        "CQ_ENABLED set but cq import failed" in record.message
        for record in caplog.records
    )
