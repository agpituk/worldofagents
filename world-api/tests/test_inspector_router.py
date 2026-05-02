"""Inspector router tests — aggregations over the Event table."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.models import Event, Hero, Tick, Zone
from app.domains.inspector.router import router as inspector_router


@pytest.fixture
def app_with_db():
    # StaticPool keeps a single connection so multiple Session objects
    # share the same in-memory SQLite database.
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

    hid = uuid.uuid4()
    db.add(Hero(
        id=hid, name="t", author="t", division="featherweight",
        bio="", str_=10, dex=10, con=10, int_=10, wis=10, cha=10,
        hp=30, status="alive", zone="z", pos_x=5, pos_y=5,
        manifest={"hero": {"tools": [
            {
                "name": "safe_gather", "description": "look first then gather",
                "steps": [{"do": "look"}, {"do": "gather"}],
            },
            {
                "override": "move", "description": "Cautious move",
                "after": [{"do": "look"}],
            },
        ]}},
        memory={}, skills={}, equipped={},
        mana_max=10, mana_current=10, known_spells=[], faction_rep={},
        auth_token=f"t-{hid}", born_at_tick=0,
    ))
    db.commit()

    app = FastAPI()
    app.include_router(inspector_router)
    app.dependency_overrides[get_db] = lambda: db

    yield app, db, str(hid)
    db.close()


def _add_resolved(db, hid, tick, tool_events, action_kind="llm"):
    db.add(Event(
        tick_id=tick, hero_id=uuid.UUID(hid), zone="z",
        kind="action.resolved",
        payload={
            "action": {"do": "look"},
            "ok": True, "outcome": {},
            "kind": action_kind,
            "debug": {"tool_events": tool_events},
        },
    ))
    db.commit()


def test_summary_returns_tools_with_zero_calls(app_with_db):
    app, db, hid = app_with_db
    client = TestClient(app)
    r = client.get(f"/api/heroes/{hid}/tools/summary")
    assert r.status_code == 200
    body = r.json()
    names = {t["name"] for t in body["tools"]}
    assert "safe_gather" in names
    assert "move" in names
    by_name = {t["name"]: t for t in body["tools"]}
    assert by_name["safe_gather"]["calls"] == 0


def test_summary_aggregates_calls(app_with_db):
    app, db, hid = app_with_db
    _add_resolved(db, hid, 100, [
        {"event": "tool.expanded", "payload": {"tool": "safe_gather", "args": {}}},
    ])
    _add_resolved(db, hid, 101, [
        {"event": "tool.expanded", "payload": {"tool": "safe_gather", "args": {}}},
    ])
    _add_resolved(db, hid, 102, [
        {"event": "tool.gated", "payload": {"tool": "safe_gather", "reason": "when_false"}},
    ])
    client = TestClient(app)
    body = client.get(f"/api/heroes/{hid}/tools/summary").json()
    by_name = {t["name"]: t for t in body["tools"]}
    sg = by_name["safe_gather"]
    assert sg["calls"] == 3
    assert sg["success"] == 2
    assert sg["blocked_by_override"] == 1
    assert sg["last_called_tick"] == 102


def test_tool_detail_returns_recent_calls(app_with_db):
    app, db, hid = app_with_db
    _add_resolved(db, hid, 200, [
        {"event": "tool.expanded", "payload": {"tool": "safe_gather", "args": {"k": 1}}},
    ])
    _add_resolved(db, hid, 201, [
        {"event": "tool.expanded", "payload": {"tool": "safe_gather", "args": {"k": 2}}},
        {"event": "tool.clamped", "payload": {"verb": "move", "param": "x", "from": 9, "to": 5}},
    ])
    client = TestClient(app)
    r = client.get(f"/api/heroes/{hid}/tools/safe_gather")
    assert r.status_code == 200
    body = r.json()
    assert body["definition"]["name"] == "safe_gather"
    assert body["stats"]["calls"] == 2
    assert body["stats"]["success"] == 2
    assert len(body["recent_calls"]) == 2
    # Reverse chronological — newest first.
    assert body["recent_calls"][0]["tick"] == 201


def test_tool_detail_404_when_unknown(app_with_db):
    app, db, hid = app_with_db
    client = TestClient(app)
    r = client.get(f"/api/heroes/{hid}/tools/unknown_tool")
    assert r.status_code == 404


def test_tick_llm_call_returns_tools_offered(app_with_db):
    app, db, hid = app_with_db
    _add_resolved(db, hid, 300, [
        {"event": "llm.tools_offered", "payload": {
            "chosen_tool": "safe_gather",
            "chosen_args": {},
            "tools_offered": [
                {"name": "safe_gather", "description": "look then gather"},
                {"name": "attack", "description": "strike a hostile"},
            ],
            "reasoning_trace": "I'll use safe_gather here since no hostile is visible.",
        }},
        {"event": "tool.expanded", "payload": {"tool": "safe_gather"}},
    ])
    client = TestClient(app)
    r = client.get(f"/api/heroes/{hid}/ticks/300/llm-call")
    assert r.status_code == 200
    body = r.json()
    assert body["chosen_tool"] == "safe_gather"
    assert "safe_gather" in body["tool_mentions"]


def test_tick_llm_call_404_when_no_event(app_with_db):
    app, db, hid = app_with_db
    client = TestClient(app)
    r = client.get(f"/api/heroes/{hid}/ticks/9999/llm-call")
    assert r.status_code == 404
