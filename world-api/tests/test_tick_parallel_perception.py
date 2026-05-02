"""FIX_PLAN P1-2: parallel perception build + per-hero watchdog.

These tests exercise the read-pass parallelism and timeout behaviour
without standing up a full tick engine — the unit of behaviour is
TickEngine._build_perceptions_parallel, which fans the per-hero
perception build out via asyncio.to_thread + asyncio.wait_for and
collects results.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core import tick as tick_mod
from app.core.database import Base
from app.core.models import Hero, Zone


@pytest.fixture
def isolated_engine(monkeypatch):
    """Fresh in-memory engine + sessionmaker, swapped in for the
    one tick.py uses. Per-test unique cache name so worker threads
    inside this test see the same DB but tests don't bleed into
    each other."""
    cache_name = f"db_{uuid.uuid4().hex[:8]}"
    engine = create_engine(
        f"sqlite+pysqlite:///file:{cache_name}?mode=memory&cache=shared&uri=true",
        connect_args={"uri": True}, future=True,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr(tick_mod, "SessionLocal", SessionLocal)
    yield SessionLocal
    engine.dispose()


def _seed_hero(SessionLocal, *, name: str, status: str = "alive") -> str:
    with SessionLocal() as s:
        if s.get(Zone, "z") is None:
            s.add(Zone(slug="z", name="Z", kind="sanctuary",
                       width=10, height=10, capacity_soft=10, description="", connections=[]))
        h = Hero(
            id=uuid.uuid4(), name=name, author="t", division="featherweight",
            bio="", str_=10, dex=10, con=10, int_=10, wis=10, cha=10,
            hp=30, status=status, zone="z", pos_x=5, pos_y=5,
            manifest={}, memory={}, skills={}, equipped={},
            mana_max=10, mana_current=10, known_spells=[], faction_rep={},
            auth_token=f"tok-{uuid.uuid4()}", born_at_tick=0,
        )
        s.add(h); s.commit()
        return str(h.id)


def test_parallel_build_returns_payload_per_connected_hero(isolated_engine):
    SessionLocal = isolated_engine
    ids = [_seed_hero(SessionLocal, name=f"h{i}") for i in range(3)]
    engine = tick_mod.TickEngine()
    # Pretend all three are connected.
    for hero_id in ids:
        engine._connections[hero_id] = asyncio.Queue()

    payloads = asyncio.run(engine._build_perceptions_parallel(
        tick_id=1, alive_ids=ids, recent=[],
    ))
    assert set(payloads.keys()) == set(ids)
    for p in payloads.values():
        assert p["type"] == "perception"
        assert p["tick_id"] == 1
        assert "gateway_permission_token" in p


def test_parallel_build_skips_disconnected_heroes(isolated_engine):
    SessionLocal = isolated_engine
    ids = [_seed_hero(SessionLocal, name=f"h{i}") for i in range(3)]
    engine = tick_mod.TickEngine()
    # Only hero 0 is connected.
    engine._connections[ids[0]] = asyncio.Queue()

    payloads = asyncio.run(engine._build_perceptions_parallel(
        tick_id=1, alive_ids=ids, recent=[],
    ))
    assert set(payloads.keys()) == {ids[0]}


def test_parallel_build_skips_dead_hero(isolated_engine):
    SessionLocal = isolated_engine
    alive_id = _seed_hero(SessionLocal, name="alive")
    dead_id = _seed_hero(SessionLocal, name="dead", status="dead")
    engine = tick_mod.TickEngine()
    engine._connections[alive_id] = asyncio.Queue()
    engine._connections[dead_id] = asyncio.Queue()

    payloads = asyncio.run(engine._build_perceptions_parallel(
        tick_id=1, alive_ids=[alive_id, dead_id], recent=[],
    ))
    # Dead hero's per-thread session sees status != "alive" and the
    # helper returns None.
    assert set(payloads.keys()) == {alive_id}


def test_watchdog_skips_slow_perception(isolated_engine, monkeypatch):
    """The headline P1-2 done-when shape (single-hero variant): one
    slow perception build does NOT stall the rest of the tick. With
    PERCEPTION_BUILD_TIMEOUT_SEC reduced + a sleeping mock, the slow
    hero is skipped; fast heroes get their payloads."""
    SessionLocal = isolated_engine
    fast_id = _seed_hero(SessionLocal, name="fast")
    slow_id = _seed_hero(SessionLocal, name="slow")
    engine = tick_mod.TickEngine()
    engine._connections[fast_id] = asyncio.Queue()
    engine._connections[slow_id] = asyncio.Queue()

    monkeypatch.setattr(tick_mod, "PERCEPTION_BUILD_TIMEOUT_SEC", 0.05)

    real_helper = tick_mod._build_perception_payload_sync

    def _slow_for_one(hero_id_str, **kwargs):
        if hero_id_str == slow_id:
            time.sleep(0.5)  # well past the watchdog
        return real_helper(hero_id_str=hero_id_str, **kwargs)

    monkeypatch.setattr(tick_mod, "_build_perception_payload_sync", _slow_for_one)

    payloads = asyncio.run(engine._build_perceptions_parallel(
        tick_id=1, alive_ids=[fast_id, slow_id], recent=[],
    ))
    # Fast hero made it; slow hero was skipped (watchdog) — but the
    # tick didn't fail, which is the whole point.
    assert fast_id in payloads
    assert slow_id not in payloads


def test_parallelism_actually_overlaps(isolated_engine, monkeypatch):
    """Three heroes with 100ms artificial delay each: serial would
    take ≥300ms. Parallel completion ought to be much closer to 100ms.
    Test asserts substantially better than serial (200ms) to avoid
    flakiness on slow CI."""
    SessionLocal = isolated_engine
    ids = [_seed_hero(SessionLocal, name=f"h{i}") for i in range(3)]
    engine = tick_mod.TickEngine()
    for hero_id in ids:
        engine._connections[hero_id] = asyncio.Queue()

    real_helper = tick_mod._build_perception_payload_sync

    def _delayed(hero_id_str, **kwargs):
        time.sleep(0.1)
        return real_helper(hero_id_str=hero_id_str, **kwargs)

    monkeypatch.setattr(tick_mod, "_build_perception_payload_sync", _delayed)

    start = time.monotonic()
    payloads = asyncio.run(engine._build_perceptions_parallel(
        tick_id=1, alive_ids=ids, recent=[],
    ))
    elapsed = time.monotonic() - start
    assert len(payloads) == 3
    # Serial would be 0.3s; concurrent should be < 0.2s on any sane
    # asyncio.to_thread executor.
    assert elapsed < 0.2, f"parallel build took {elapsed:.2f}s — not actually parallel"
