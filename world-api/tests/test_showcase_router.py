"""Showcase router tests — leaderboards, tool detail, copy flow."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.models import Event, Hero, Tick, ToolCopy, ToolDefinition, Zone
from app.domains.showcase.canonicalize import canonicalize, tool_id
from app.domains.showcase.router import router as showcase_router


@pytest.fixture
def app_with_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(Tick(notes="seed"))
    db.add(Zone(slug="z", name="Z", kind="sanctuary",
                width=10, height=10, capacity_soft=10,
                description="", connections=[]))

    # Two heroes with overlapping tools.
    h1 = uuid.uuid4()
    h2 = uuid.uuid4()
    shared_tool = {
        "name": "safe_gather", "description": "look first then gather",
        "steps": [{"do": "look"}, {"do": "gather"}],
    }
    h1_tool = {
        "name": "patrol", "description": "walk a small patrol",
        "steps": [{"do": "look"}, {"do": "look"}],
    }
    db.add(Hero(
        id=h1, name="alice", author="a", division="featherweight",
        bio="", str_=10, dex=10, con=10, int_=10, wis=10, cha=10,
        hp=30, status="alive", zone="z", pos_x=5, pos_y=5,
        manifest={"hero": {"tools": [shared_tool, h1_tool]}},
        memory={}, skills={}, equipped={},
        mana_max=10, mana_current=10, known_spells=[], faction_rep={},
        auth_token=f"a-{h1}", born_at_tick=0,
    ))
    db.add(Hero(
        id=h2, name="bob", author="b", division="featherweight",
        bio="", str_=10, dex=10, con=10, int_=10, wis=10, cha=10,
        hp=30, status="alive", zone="z", pos_x=5, pos_y=5,
        manifest={"hero": {"tools": [shared_tool]}},
        memory={}, skills={}, equipped={},
        mana_max=10, mana_current=10, known_spells=[], faction_rep={},
        auth_token=f"b-{h2}", born_at_tick=0,
    ))
    db.commit()

    app = FastAPI()
    app.include_router(showcase_router)
    app.dependency_overrides[get_db] = lambda: db

    yield app, db, str(h1), str(h2)
    db.close()


def test_canonicalize_is_stable():
    a = {"name": "t", "description": "x", "steps": [{"do": "look"}]}
    b = {"description": "x", "steps": [{"do": "look"}], "name": "t"}
    assert canonicalize(a) == canonicalize(b)


def test_tool_id_strips_meta():
    a = {"name": "t", "description": "x", "steps": [{"do": "look"}]}
    b = {"name": "t", "description": "x", "steps": [{"do": "look"}],
         "_meta": {"parent_tool_id": "abc"}}
    assert tool_id(a) == tool_id(b)


def test_tool_id_changes_on_content_change():
    a = {"name": "t", "description": "x", "steps": [{"do": "look"}]}
    b = {"name": "t", "description": "x", "steps": [{"do": "wait"}]}
    assert tool_id(a) != tool_id(b)


def test_indexing_creates_tool_definitions(app_with_db):
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    # Hitting the leaderboards triggers indexing.
    client.get("/api/tools/leaderboards?board=most_copied")

    defs = list(db.scalars(__import__("sqlalchemy").select(ToolDefinition)))
    names = {d.name for d in defs}
    assert "safe_gather" in names
    assert "patrol" in names


def test_most_copied_leaderboard(app_with_db):
    from sqlalchemy import select as _select
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    # Trigger indexing
    client.get("/api/tools/leaderboards")
    # Find safe_gather's tool_id
    sg_def = db.execute(
        _select(ToolDefinition).where(ToolDefinition.name == "safe_gather")
    ).scalar_one()
    # Stamp 3 copies
    for _ in range(3):
        db.add(ToolCopy(source_tool_id=sg_def.tool_id, copied_by_hero=uuid.UUID(h2)))
    db.commit()

    body = client.get("/api/tools/leaderboards?board=most_copied").json()
    assert body["board"] == "most_copied"
    assert body["entries"][0]["name"] == "safe_gather"
    assert body["entries"][0]["metric"] == 3.0


def test_unknown_board_returns_400(app_with_db):
    app, *_ = app_with_db
    client = TestClient(app)
    r = client.get("/api/tools/leaderboards?board=invented")
    assert r.status_code == 400


def test_stub_boards_return_empty_with_note(app_with_db):
    app, *_ = app_with_db
    client = TestClient(app)
    body = client.get("/api/tools/leaderboards?board=highest_lift").json()
    assert body["entries"] == []
    assert "stub" in body["note"]


def test_tool_detail_returns_users(app_with_db):
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    # Trigger indexing
    client.get("/api/tools/leaderboards")
    from sqlalchemy import select as _select
    sg = db.execute(
        _select(ToolDefinition).where(ToolDefinition.name == "safe_gather")
    ).scalar_one()
    body = client.get(f"/api/tools/{sg.tool_id}").json()
    user_names = {u["name"] for u in body["users"]}
    assert user_names == {"alice", "bob"}


def test_copy_endpoint_records_copy(app_with_db):
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    # Trigger indexing
    client.get("/api/tools/leaderboards")
    from sqlalchemy import select as _select
    sg = db.execute(
        _select(ToolDefinition).where(ToolDefinition.name == "safe_gather")
    ).scalar_one()
    r = client.post(f"/api/tools/{sg.tool_id}/copy?by_hero={h2}")
    assert r.status_code == 200
    copies = list(db.scalars(_select(ToolCopy).where(
        ToolCopy.source_tool_id == sg.tool_id,
    )))
    assert len(copies) == 1


def test_copy_with_unknown_hero_404s(app_with_db):
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    client.get("/api/tools/leaderboards")
    from sqlalchemy import select as _select
    sg = db.execute(
        _select(ToolDefinition).where(ToolDefinition.name == "safe_gather")
    ).scalar_one()
    fake_hid = uuid.uuid4()
    r = client.post(f"/api/tools/{sg.tool_id}/copy?by_hero={fake_hid}")
    assert r.status_code == 404


def test_best_success_aggregates_events(app_with_db):
    from sqlalchemy import select as _select
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    client.get("/api/tools/leaderboards")  # index

    # Add 6 expanded events for safe_gather, all successful (well above 5-call floor).
    for tick in range(100, 106):
        db.add(Event(
            tick_id=tick, hero_id=uuid.UUID(h1), zone="z",
            kind="action.resolved",
            payload={
                "action": {"do": "look"}, "ok": True, "outcome": {},
                "kind": "llm",
                "debug": {"tool_events": [
                    {"event": "tool.expanded", "payload": {"tool": "safe_gather"}},
                ]},
            },
        ))
    db.commit()

    body = client.get("/api/tools/leaderboards?board=best_success").json()
    names = {e["name"] for e in body["entries"]}
    assert "safe_gather" in names
