"""FIX_PLAN P2-2: a reflex that fires mid-composite must abandon the
composite and act on the reflex.

Pre-fix, the runner expanded a composite into a queue of primitive
actions and dispatched one per tick without re-evaluating reflexes.
A hostile that appeared on step 2 of a 5-step gather plan got
gathered through. The fix is the reflex re-check between primitive
steps, with a `composite_interrupted` debug marker so spectators see
the hero break off rather than appear to ignore the threat.
"""

from __future__ import annotations

import asyncio

import pytest

from app.managed.runner import ManagedHeroTask


def _perception_msg(*, with_hostile: bool) -> dict:
    """Build the WS-shaped perception message that _decide consumes.
    Compact; only the fields the reflex DSL actually reads."""
    return {
        "tick_id": 1,
        "your_state": {"hp": 30, "pos": [5, 5]},
        "perception": {
            "visible_npcs": (
                [{"slug": "rat_a", "hostility": "hostile", "pos": [5, 5]}]
                if with_hostile else []
            ),
            "visible_heroes": [],
            "inventory": [],
            "visible_items": [],
            "memory": {},
            "zone": {"connections": [], "kind": "sanctuary"},
        },
        "deadline_ms": 6000,
        "gateway_permission_token": None,
    }


def _gather_manifest() -> dict:
    """A hero who reflexively gathers when no enemy is visible, and
    breaks off to attack when one is. Composite expands to 3 steps."""
    return {
        "hero": {
            "reflexes": [
                {"when": "hostile_visible()", "then": {"do": "attack", "target": "rat_a"}},
                {"when": "hp > 20", "then": {"do": "harvest_run"}},
            ],
            "abilities": {
                "harvest_run": {
                    "steps": [
                        {"do": "move", "target": [6, 5]},
                        {"do": "gather"},
                        {"do": "move", "target": [5, 5]},
                    ]
                },
            },
        }
    }


@pytest.fixture
def task():
    return ManagedHeroTask("hero-id", "test-hero", _gather_manifest())


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.get_event_loop().is_running() else asyncio.run(coro)


def test_composite_starts_and_drains_when_no_interrupt(task):
    """Sanity: the composite expands and dispatches 3 primitives across
    3 ticks when no reflex interrupts."""
    a1, d1, _ = asyncio.run(task._decide(_perception_msg(with_hostile=False)))
    assert a1 == {"do": "move", "target": [6, 5]}
    assert d1["via"] == "composite_start"

    a2, d2, _ = asyncio.run(task._decide(_perception_msg(with_hostile=False)))
    assert a2 == {"do": "gather"}
    assert d2["via"] == "composite"
    assert d2["remaining"] == 1

    a3, d3, _ = asyncio.run(task._decide(_perception_msg(with_hostile=False)))
    assert a3 == {"do": "move", "target": [5, 5]}
    assert d3["via"] == "composite"
    assert d3["remaining"] == 0


def test_hostile_appearing_mid_composite_interrupts_it(task):
    """The headline P2-2 case: a hostile mob appears on step 2 of the
    composite. The hero must abandon the gather and attack instead."""
    asyncio.run(task._decide(_perception_msg(with_hostile=False)))   # step 1 of harvest_run
    # Hostile appears before step 2.
    a2, d2, _ = asyncio.run(task._decide(_perception_msg(with_hostile=True)))
    assert a2 == {"do": "attack", "target": "rat_a"}
    assert d2.get("interrupt", {}).get("via") == "composite_interrupted"
    assert d2["interrupt"]["interrupted_composite"] == "harvest_run"
    assert d2["interrupt"]["remaining_was"] == 2  # steps 2 and 3 abandoned
    # Queue is now empty so a follow-up tick starts fresh, not draining.
    assert task._composite_queue == []
    assert task._composite_name is None


def test_same_composite_does_not_self_interrupt(task):
    """If a reflex re-fires the SAME composite the hero is already in,
    don't recurse — that would loop forever. Instead, drain the queue."""
    asyncio.run(task._decide(_perception_msg(with_hostile=False)))   # step 1, queue=[step2, step3]
    # Same perception — the gather reflex (hp > 20) still matches and
    # would re-pick harvest_run. Implementation must short-circuit.
    a2, _, _ = asyncio.run(task._decide(_perception_msg(with_hostile=False)))
    assert a2 == {"do": "gather"}  # next primitive of the SAME composite
    assert task._composite_name == "harvest_run"
