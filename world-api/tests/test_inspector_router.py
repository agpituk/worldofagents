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
    # Public path: no prompt data leaks even when payload contains it.
    assert body["prompt_visible"] is False
    assert body["prompt_text"] is None
    assert body["tokens_in"] is None


def test_tick_llm_call_404_when_no_event(app_with_db):
    app, db, hid = app_with_db
    client = TestClient(app)
    r = client.get(f"/api/heroes/{hid}/ticks/9999/llm-call")
    assert r.status_code == 404


def test_tick_llm_call_owner_token_unlocks_prompt(app_with_db):
    app, db, hid = app_with_db
    _add_resolved(db, hid, 400, [
        {"event": "llm.tools_offered", "payload": {
            "chosen_tool": "safe_gather",
            "chosen_args": {},
            "tools_offered": [{"name": "safe_gather", "description": "x"}],
            "reasoning_trace": "...",
            "prompt_text": "# system\nyou are t\n\n# user\nperception here",
            "tokens_in": 120, "tokens_out": 30,
            "tokens_budget": 500, "latency_ms": 412,
        }},
    ])
    client = TestClient(app)
    auth = f"t-{hid}"

    # Wrong token → still public-only.
    r = client.get(f"/api/heroes/{hid}/ticks/400/llm-call?owner_token=wrong")
    assert r.status_code == 200
    assert r.json()["prompt_visible"] is False
    assert r.json()["prompt_text"] is None

    # Right token → owner sees prompt + tokens + latency.
    r = client.get(f"/api/heroes/{hid}/ticks/400/llm-call?owner_token={auth}")
    assert r.status_code == 200
    body = r.json()
    assert body["prompt_visible"] is True
    assert "you are t" in body["prompt_text"]
    assert body["tokens_in"] == 120
    assert body["tokens_out"] == 30
    assert body["tokens_budget"] == 500
    assert body["latency_ms"] == 412


def test_latest_llm_call_returns_most_recent_event(app_with_db):
    app, db, hid = app_with_db
    # An older reflex-only tick (no llm event).
    _add_resolved(db, hid, 500, [
        {"event": "tool.expanded", "payload": {"tool": "safe_gather"}},
    ])
    # A more recent llm tick.
    _add_resolved(db, hid, 510, [
        {"event": "llm.tools_offered", "payload": {
            "chosen_tool": "safe_gather", "chosen_args": {},
            "tools_offered": [{"name": "safe_gather", "description": "x"}],
            "reasoning_trace": "...",
            "prompt_text": "P", "tokens_in": 5, "tokens_out": 5,
            "tokens_budget": 500, "latency_ms": 100,
        }},
    ])
    client = TestClient(app)
    auth = f"t-{hid}"
    r = client.get(f"/api/heroes/{hid}/llm-call/latest?owner_token={auth}")
    assert r.status_code == 200
    body = r.json()
    assert body["tick_id"] == 510
    assert body["prompt_visible"] is True
    assert body["prompt_text"] == "P"


def test_latest_llm_call_returns_null_when_none(app_with_db):
    app, db, hid = app_with_db
    client = TestClient(app)
    r = client.get(f"/api/heroes/{hid}/llm-call/latest")
    assert r.status_code == 200
    assert r.json()["tick_id"] is None
