"""Managed runner — `llm.tools_offered` trace contract.

The prompt inspector reads back `prompt_text`, `tokens_in`, `tokens_out`,
`tokens_budget`, and `latency_ms` from this event. If the runner stops
emitting (or stops including these fields), the inspector silently
becomes empty even when an LLM tick actually fired. This test pins the
shape and the emit-on-every-LLM-call contract.
"""

from __future__ import annotations

import asyncio
from typing import Any

from arena_bot.types import Perception

from app.managed.runner import ManagedHeroTask


def _stub_gateway_response(**overrides) -> dict[str, Any]:
    base = {
        "completion": "I will attack.",
        "tool_calls": [
            {"id": "1", "name": "attack", "arguments": {"target": "rat"}}
        ],
        "model": "stub",
        "tokens_in": 100,
        "tokens_out": 5,
        "latency_ms": 42,
        "gateway_token": "fake.token",
        "tokens_budget": 200,
    }
    base.update(overrides)
    return base


def _make_task(reflexes: list | None = None) -> ManagedHeroTask:
    manifest = {
        "name": "Trace Test",
        "author": "@t",
        "division": "featherweight",
        "build": {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        "extras": {
            "reflexes": reflexes or [{"when": "hp > 0", "then": {"do": "invoke_llm"}}],
            "memory": {"initial": {"goal": "test"}},
        },
    }
    return ManagedHeroTask(hero_id="00000000-0000-0000-0000-000000000001",
                           name="Trace Test", manifest=manifest)


def _bare_perception(tick_id: int = 1) -> Perception:
    return Perception(
        tick_id=tick_id,
        your_state={
            "hp": 30, "gold": 0, "zone": "market_square", "pos": [4, 4],
            "mana_current": 5, "mana_max": 5, "equipped": {}, "inventory": [],
            "skills": {},
        },
        perception={
            "visible_npcs": [], "visible_heroes": [], "visible_items": [],
            "visible_resources": [], "memory": {"npcs": {}},
            "zone": {"connections": [], "kind": "sanctuary"},
            "inventory": [],
        },
        deadline_ms=6000,
    )


class _FakeResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body
        self.status_code = 200
    def raise_for_status(self) -> None: pass
    def json(self) -> dict[str, Any]: return self._body


class _FakeAsyncClient:
    """Replaces httpx.AsyncClient inside the runner. Captures the post
    call so the test can assert what the runner sent, and returns a
    canned response."""
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body
        self.last_post: tuple[str, dict[str, Any]] | None = None
    async def __aenter__(self): return self
    async def __aexit__(self, *_): return False
    async def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:
        self.last_post = (url, json)
        return _FakeResponse(self._body)


def _patched_call_llm(task: ManagedHeroTask, body: dict[str, Any]) -> dict[str, Any]:
    """Run task._call_llm with httpx.AsyncClient swapped for the fake.
    Returns the action and leaves the trace buffer on the task for
    assertions."""
    import app.managed.runner as runner_mod

    fake = _FakeAsyncClient(body)
    real_client = runner_mod.httpx.AsyncClient

    def factory(*_a, **_kw):
        return fake

    runner_mod.httpx.AsyncClient = factory  # type: ignore[assignment]
    try:
        task._tick_trace = []
        action = asyncio.run(task._call_llm(_bare_perception()))
    finally:
        runner_mod.httpx.AsyncClient = real_client  # type: ignore[assignment]
    return action


def test_trace_event_emitted_on_primitive_verb_choice():
    """When the LLM picks a primitive verb (the common case), the
    runner must still stash an llm.tools_offered event with prompt +
    tokens + budget + latency."""
    task = _make_task()
    action = _patched_call_llm(task, _stub_gateway_response())
    assert action == {"do": "attack", "target": "rat"} or action.get("do")  # primitive ran

    trace = getattr(task, "_tick_trace", [])
    offered = [e for e in trace if e["event"] == "llm.tools_offered"]
    assert len(offered) == 1, f"expected exactly one llm.tools_offered, got {trace}"

    payload = offered[0]["payload"]
    assert payload["chosen_tool"] == "attack"
    assert payload["chosen_args"] == {"target": "rat"}
    assert "# system" in payload["prompt_text"]
    assert "# user" in payload["prompt_text"]
    assert payload["tokens_in"] == 100
    assert payload["tokens_out"] == 5
    assert payload["tokens_budget"] == 200
    assert payload["latency_ms"] == 42
    # Tools list must be a non-empty array of {name, description}.
    assert isinstance(payload["tools_offered"], list)
    assert payload["tools_offered"]
    assert {"name", "description"}.issubset(payload["tools_offered"][0].keys())


def test_trace_event_emitted_when_no_tool_call():
    """If the gateway returns no tool_calls (free-text fallback), the
    trace event should still fire with chosen_tool=None so the
    inspector can show the prompt and reasoning."""
    task = _make_task()
    body = _stub_gateway_response(tool_calls=[], completion='{"do":"wait"}')
    _patched_call_llm(task, body)

    trace = getattr(task, "_tick_trace", [])
    offered = [e for e in trace if e["event"] == "llm.tools_offered"]
    assert len(offered) == 1
    assert offered[0]["payload"]["chosen_tool"] is None
    assert offered[0]["payload"]["tokens_in"] == 100


def test_trace_event_handles_missing_budget():
    """Older gateway responses (or providers that bypass permission
    tokens) won't carry tokens_budget. The runner must still emit the
    event with tokens_budget=None."""
    task = _make_task()
    body = _stub_gateway_response()
    body.pop("tokens_budget", None)
    _patched_call_llm(task, body)

    trace = getattr(task, "_tick_trace", [])
    offered = [e for e in trace if e["event"] == "llm.tools_offered"]
    assert len(offered) == 1
    assert offered[0]["payload"]["tokens_budget"] is None
    assert offered[0]["payload"]["tokens_in"] == 100
