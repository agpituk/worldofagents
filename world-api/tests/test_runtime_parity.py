"""FIX_PLAN P2-1 done-when: managed runner and SDK runner produce
byte-identical action streams when fed the same manifest + perception
sequence.

Pre-fix, both runtimes implemented reflex-eval / composite-expansion /
invoke_llm-dispatch independently and drifted (P2-2's composite
interrupt was in managed but not SDK). Post-fix, both wrappers route
through arena_bot.hero_runtime.decide_one(); this test exercises both
wrappers against the same canned inputs and asserts the action+debug
streams match.

invoke_llm is stubbed to a deterministic action so the test doesn't
need the gateway running.
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any

import pytest

from arena_bot.client import Decision, Perception


SHARED_MANIFEST = {
    "hero": {
        "bio": "test bio",
        "memory": {"initial": {"goal": "Survive."}},
        "models": {"cheap": {"model": "qwen3-4b"}},
        "model": "cheap",
        "reflexes": [
            {"when": "hostile_visible()", "then": {"do": "attack", "target": "rat_a"}},
            {"when": "hp < 10", "then": {"do": "flee"}},
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


def _perception(*, hp: int = 30, hostile: bool = False) -> dict:
    return {
        "tick_id": 1,
        "your_state": {"hp": hp, "pos": [5, 5]},
        "perception": {
            "visible_npcs": [{"slug": "rat_a", "hostility": "hostile", "pos": [5, 5]}] if hostile else [],
            "visible_heroes": [], "inventory": [], "visible_items": [],
            "memory": {}, "zone": {"connections": [], "kind": "sanctuary"},
        },
        "deadline_ms": 6000,
        "gateway_permission_token": None,
    }


# Canned sequence exercises every branch:
#   1. cold-start → harvest_run starts (composite_start)
#   2. composite drains step 2 (composite)
#   3. composite drains step 3 (composite)
#   4. cold-start again → harvest_run starts
#   5. mid-composite hostile appears → INTERRUPT, attack
#   6. low HP → flee
SEQUENCE = [
    _perception(hp=30, hostile=False),
    _perception(hp=30, hostile=False),
    _perception(hp=30, hostile=False),
    _perception(hp=30, hostile=False),
    _perception(hp=30, hostile=True),
    _perception(hp=5, hostile=False),
]


# --- managed-side runner -------------------------------------------------


def _run_managed(seq: list[dict]) -> list[tuple[dict, dict | None]]:
    from app.managed.runner import ManagedHeroTask

    task = ManagedHeroTask("hero-id", "test-hero", copy.deepcopy(SHARED_MANIFEST))
    out: list[tuple[dict, dict | None]] = []
    for msg in seq:
        action, debug, _kind = asyncio.run(task._decide(copy.deepcopy(msg)))
        out.append((action, debug))
    return out


# --- SDK-side runner ------------------------------------------------------


def _run_sdk(seq: list[dict]) -> list[tuple[dict, dict | None]]:
    from arena_bot.runner import ManifestHero

    # ManifestHero is a Hero subclass that expects to connect over WS;
    # for parity we only exercise decide(), so we instantiate a stub.
    hero = ManifestHero.__new__(ManifestHero)
    # ManifestHero.__init__ calls super().__init__(*args, **kwargs); we
    # bypass that here and only set the slots its decide() touches.
    hero.name = "test-hero"
    hero.hero_id = "hero-id"
    from arena_bot.hero_runtime import (
        HeroDecisionState, parse_abilities, parse_persona,
    )
    from arena_bot.reflexes import ReflexEngine
    persona = parse_persona(copy.deepcopy(SHARED_MANIFEST))
    hero._bio = persona["bio"]
    hero._goal = persona["goal"]
    hero._system_summary = persona["system_summary"]
    hero._model_id = persona["model_id"]
    hero._reflexes = ReflexEngine(SHARED_MANIFEST["hero"]["reflexes"])
    hero._abilities = parse_abilities(copy.deepcopy(SHARED_MANIFEST))
    hero._state = HeroDecisionState()

    out: list[tuple[dict, dict | None]] = []
    for msg in seq:
        p = Perception(
            tick_id=msg["tick_id"], your_state=msg["your_state"],
            perception=msg["perception"], deadline_ms=msg["deadline_ms"],
            gateway_permission_token=msg.get("gateway_permission_token"),
        )
        decision = asyncio.run(hero.decide(p))
        out.append((decision.action, decision.debug))
    return out


# --- the parity assertion ------------------------------------------------


def test_managed_and_sdk_runtimes_produce_identical_action_stream():
    """Same manifest + same perception sequence must produce byte-
    identical (action, debug) streams from both runtimes. Drifts here
    mean a hosted hero behaves differently from an SDK hero on a
    leaderboard — direct fairness violation."""
    managed = _run_managed(copy.deepcopy(SEQUENCE))
    sdk = _run_sdk(copy.deepcopy(SEQUENCE))

    assert len(managed) == len(sdk)
    for i, ((m_action, m_debug), (s_action, s_debug)) in enumerate(zip(managed, sdk)):
        assert m_action == s_action, (
            f"tick {i}: managed dispatched {m_action!r}, SDK dispatched {s_action!r}"
        )
        assert m_debug == s_debug, (
            f"tick {i}: debug differs.\n  managed={m_debug}\n  sdk={s_debug}"
        )


def test_canned_sequence_exercises_expected_branches():
    """Sanity on the test fixture itself — verify each tick goes
    through the branch we intended. If this test breaks, the parity
    test below isn't actually testing what we claim it is."""
    actions = [a for a, _ in _run_managed(copy.deepcopy(SEQUENCE))]
    assert actions[0] == {"do": "move", "target": [6, 5]}    # composite_start
    assert actions[1] == {"do": "gather"}                     # composite
    assert actions[2] == {"do": "move", "target": [5, 5]}    # composite tail
    assert actions[3] == {"do": "move", "target": [6, 5]}    # second composite_start
    assert actions[4] == {"do": "attack", "target": "rat_a"}  # interrupt
    assert actions[5] == {"do": "flee"}                       # low-hp reflex
