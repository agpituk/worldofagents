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
from app.domains.showcase.router import compare_router, router as showcase_router


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
    app.include_router(compare_router)
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


def test_david_leaderboard_filters_to_featherweights(app_with_db):
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    client.get("/api/tools/leaderboards")  # index
    # Both alice and bob are featherweights, so all their tools qualify.
    # Add some calls so the floor is met.
    for tick in range(10, 16):
        db.add(Event(
            tick_id=tick, hero_id=uuid.UUID(h1), zone="z",
            kind="action.resolved",
            payload={
                "action": {"do": "look"}, "ok": True, "outcome": {},
                "kind": "llm",
                "debug": {"tool_events": [
                    {"event": "tool.expanded", "payload": {"tool": "patrol"}},
                ]},
            },
        ))
    db.commit()
    body = client.get("/api/tools/leaderboards?board=david").json()
    names = [e["name"] for e in body["entries"]]
    assert "patrol" in names


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


def test_copy_endpoint_records_copy_event(app_with_db):
    """The Copy event itself is recorded — even when the actual append
    is rejected by collision. (Once a rename succeeds, both the copy
    event and the append fire.)"""
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    client.get("/api/tools/leaderboards")
    from sqlalchemy import select as _select
    patrol = db.execute(
        _select(ToolDefinition).where(ToolDefinition.name == "patrol")
    ).scalar_one()
    r = client.post(f"/api/tools/{patrol.tool_id}/copy?by_hero={h2}")
    assert r.status_code == 200
    copies = list(db.scalars(_select(ToolCopy).where(
        ToolCopy.source_tool_id == patrol.tool_id,
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


def test_copy_appends_to_target_manifest(app_with_db):
    from sqlalchemy import select as _select
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    client.get("/api/tools/leaderboards")  # index
    # Find h1's `patrol` tool — h2 doesn't have it.
    patrol = db.execute(
        _select(ToolDefinition).where(ToolDefinition.name == "patrol")
    ).scalar_one()
    r = client.post(f"/api/tools/{patrol.tool_id}/copy?by_hero={h2}")
    assert r.status_code == 200
    body = r.json()
    assert body["appended"] is True
    assert body["new_tool_id"]
    # Check the manifest actually has it now
    bob = db.scalar(_select(Hero).where(Hero.name == "bob"))
    bob_tools = bob.manifest["hero"]["tools"]
    bob_names = [t.get("name") or t.get("override") for t in bob_tools]
    assert "patrol" in bob_names
    # _meta lineage stamped
    new_patrol = next(t for t in bob_tools if t.get("name") == "patrol")
    assert new_patrol["_meta"]["parent_tool_id"] == patrol.tool_id


def test_copy_collision_returns_rename_prompt(app_with_db):
    from sqlalchemy import select as _select
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    client.get("/api/tools/leaderboards")
    sg = db.execute(
        _select(ToolDefinition).where(ToolDefinition.name == "safe_gather")
    ).scalar_one()
    # h2 already has safe_gather (shared) — so this collides.
    r = client.post(f"/api/tools/{sg.tool_id}/copy?by_hero={h2}")
    body = r.json()
    assert body["appended"] is False
    assert body["rename_to"] == "safe_gather"

    # Retry with rename
    r2 = client.post(f"/api/tools/{sg.tool_id}/copy?by_hero={h2}&rename=safe_gather_v2")
    assert r2.json()["appended"] is True
    bob = db.scalar(_select(Hero).where(Hero.name == "bob"))
    bob_names = [
        t.get("name") or t.get("override")
        for t in bob.manifest["hero"]["tools"]
    ]
    assert "safe_gather_v2" in bob_names


def test_most_called_leaderboard(app_with_db):
    from sqlalchemy import select as _select
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    client.get("/api/tools/leaderboards")  # index
    # 7 expanded events for safe_gather (above the 5-call floor used in
    # best_success and consistent across boards).
    for tick in range(50, 57):
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
    body = client.get("/api/tools/leaderboards?board=most_called").json()
    names = [e["name"] for e in body["entries"]]
    assert names[0] == "safe_gather"
    assert body["entries"][0]["metric"] == 7.0


def test_best_named_leaderboard_uses_offer_data(app_with_db):
    from sqlalchemy import select as _select
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    client.get("/api/tools/leaderboards")
    # 6 offers, picked 5 of 6.
    for tick in range(60, 66):
        picked = "safe_gather" if tick != 65 else "patrol"
        db.add(Event(
            tick_id=tick, hero_id=uuid.UUID(h1), zone="z",
            kind="action.resolved",
            payload={
                "action": {"do": "look"}, "ok": True, "outcome": {},
                "kind": "llm",
                "debug": {"tool_events": [
                    {"event": "llm.tools_offered", "payload": {
                        "chosen_tool": picked,
                        "tools_offered": [
                            {"name": "safe_gather", "description": "x"},
                            {"name": "patrol", "description": "y"},
                        ],
                        "reasoning_trace": "",
                    }},
                ]},
            },
        ))
    db.commit()
    body = client.get("/api/tools/leaderboards?board=best_named").json()
    names = [e["name"] for e in body["entries"]]
    assert "safe_gather" in names


def test_highest_lift_returns_entries_with_honesty(app_with_db):
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    client.get("/api/tools/leaderboards")
    body = client.get("/api/tools/leaderboards?board=highest_lift").json()
    assert "honesty" in body
    # Entries may be empty (insufficient data); the board returns shape, not data.
    assert isinstance(body["entries"], list)


def test_compare_returns_shared_tools(app_with_db):
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    client.get("/api/tools/leaderboards")  # index
    body = client.get(f"/api/compare?heroes={h1},{h2}").json()
    assert len(body["heroes"]) == 2
    shared_names = [s["name"] for s in body["shared"]]
    assert "safe_gather" in shared_names
    sg_shared = next(s for s in body["shared"] if s["name"] == "safe_gather")
    # h1 and h2 both have the same source — identical.
    assert sg_shared["identical"] is True


def test_compare_rejects_wrong_count(app_with_db):
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    r = client.get(f"/api/compare?heroes={h1}")  # only one
    assert r.status_code == 400


def test_gallery_returns_shape(app_with_db):
    app, db, h1, h2 = app_with_db
    client = TestClient(app)
    body = client.get("/api/tools-gallery").json()
    assert "by_category" in body
    assert "featured" in body
    assert "new_and_noteworthy" in body


def test_tool_visibility_private_excludes_from_index(app_with_db):
    from sqlalchemy import select as _select
    app, db, h1, h2 = app_with_db
    # Mark bob private; reindex should skip his tools.
    bob = db.scalar(_select(Hero).where(Hero.name == "bob"))
    bob.manifest = {"hero": {
        "tool_visibility": "private",
        "tools": [
            {
                "name": "secret_tool",
                "description": "shh",
                "steps": [{"do": "look"}],
            },
        ],
    }}
    db.commit()
    client = TestClient(app)
    client.get("/api/tools/leaderboards")
    # secret_tool should NOT have been indexed
    defs = list(db.scalars(_select(ToolDefinition)))
    names = {d.name for d in defs}
    assert "secret_tool" not in names


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
