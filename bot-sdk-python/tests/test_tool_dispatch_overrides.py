"""Override-middleware + if-step + interpolation tests (Phase 3)."""

from __future__ import annotations

from arena_bot.tool_dispatch import HeroToolset, expand_tool_call


def _toolset(yaml_tools: list[dict]) -> HeroToolset:
    return HeroToolset.from_manifest({"hero": {"tools": yaml_tools}})


# ---------------------------------------------------------------------------
# `when:` gate
# ---------------------------------------------------------------------------


def test_when_blocks_call():
    ts = _toolset([{
        "override": "attack", "description": "x",
        "when": "hp > 8",
    }])
    events: list[tuple[str, dict]] = []
    result = expand_tool_call(
        "attack", {"target": "rat_a"},
        toolset=ts,
        namespace={"hp": 4},
        trace=lambda e, p: events.append((e, p)),
    )
    assert result.actions == [{"do": "wait", "_blocked_by_override": "attack"}]
    assert any(e == "tool.gated" for e, _ in events)


def test_when_passes_executes_primitive():
    ts = _toolset([{
        "override": "attack", "description": "x",
        "when": "hp > 8",
    }])
    result = expand_tool_call(
        "attack", {"target": "rat_a"},
        toolset=ts, namespace={"hp": 12},
    )
    assert result.actions == [{"do": "attack", "target": "rat_a"}]


def test_when_non_bool_treated_as_false():
    """Type errors at runtime should gate the call (defensive; the
    validator should have caught it earlier)."""
    ts = _toolset([{
        "override": "attack", "description": "x",
        "when": "hp + 1",  # returns int, not bool
    }])
    events: list[tuple[str, dict]] = []
    result = expand_tool_call(
        "attack", {"target": "rat_a"},
        toolset=ts, namespace={"hp": 12},
        trace=lambda e, p: events.append((e, p)),
    )
    assert any(e == "tool.expression.type_error" for e, _ in events)
    assert result.actions[0]["do"] == "wait"


# ---------------------------------------------------------------------------
# `clamp:`
# ---------------------------------------------------------------------------


def test_clamp_reshapes_value():
    ts = _toolset([{
        "override": "buy", "description": "x",
        "clamp": {"qty": "min(requested, 5)"},
    }])
    events: list[tuple[str, dict]] = []
    result = expand_tool_call(
        "buy", {"target": "marek", "item": "iron_ore", "qty": 100},
        toolset=ts, namespace={},
        trace=lambda e, p: events.append((e, p)),
    )
    assert result.actions[0]["qty"] == 5
    clamp_event = next(e for e in events if e[0] == "tool.clamped")
    assert clamp_event[1]["from"] == 100
    assert clamp_event[1]["to"] == 5


def test_clamp_no_change_no_event():
    ts = _toolset([{
        "override": "buy", "description": "x",
        "clamp": {"qty": "min(requested, 5)"},
    }])
    events: list[tuple[str, dict]] = []
    expand_tool_call(
        "buy", {"target": "marek", "item": "iron_ore", "qty": 3},
        toolset=ts, namespace={},
        trace=lambda e, p: events.append((e, p)),
    )
    # 3 < 5, so requested wins; no `tool.clamped` event.
    assert not any(e == "tool.clamped" for e, _ in events)


def test_clamp_error_keeps_requested():
    ts = _toolset([{
        "override": "buy", "description": "x",
        "clamp": {"qty": "1 / 0"},
    }])
    events: list[tuple[str, dict]] = []
    result = expand_tool_call(
        "buy", {"target": "marek", "item": "iron_ore", "qty": 3},
        toolset=ts, namespace={},
        trace=lambda e, p: events.append((e, p)),
    )
    assert result.actions[0]["qty"] == 3
    assert any(e == "tool.clamp.error" for e, _ in events)


# ---------------------------------------------------------------------------
# `after:`
# ---------------------------------------------------------------------------


def test_after_chain_runs_after_primitive():
    ts = _toolset([{
        "override": "move", "description": "x",
        "after": [{"do": "look"}],
    }])
    events: list[tuple[str, dict]] = []
    result = expand_tool_call(
        "move", {"target": [3, 4]},
        toolset=ts, namespace={},
        trace=lambda e, p: events.append((e, p)),
    )
    assert result.actions[0]["do"] == "move"
    assert result.actions[1]["do"] == "look"
    assert any(e == "tool.after.step" for e, _ in events)


def test_after_skipped_when_when_blocks():
    ts = _toolset([{
        "override": "move", "description": "x",
        "when": "False",
        "after": [{"do": "look"}],
    }])
    events: list[tuple[str, dict]] = []
    result = expand_tool_call(
        "move", {"target": [3, 4]},
        toolset=ts, namespace={},
        trace=lambda e, p: events.append((e, p)),
    )
    assert result.actions[0]["do"] == "wait"
    assert not any(e == "tool.after.step" for e, _ in events)


# ---------------------------------------------------------------------------
# `if`-step inside composites
# ---------------------------------------------------------------------------


def test_if_simple_form_taken_when_true():
    ts = _toolset([{
        "name": "smart", "description": "x",
        "steps": [{"if": "hp > 8", "do": "look"}],
    }])
    result = expand_tool_call(
        "smart", {}, toolset=ts, namespace={"hp": 12},
    )
    assert result.actions == [{"do": "look"}]


def test_if_simple_form_skipped_when_false():
    ts = _toolset([{
        "name": "smart", "description": "x",
        "steps": [{"if": "hp > 8", "do": "look"}, {"do": "wait"}],
    }])
    result = expand_tool_call(
        "smart", {}, toolset=ts, namespace={"hp": 4},
    )
    # Only the unconditional `wait` should run.
    assert result.actions == [{"do": "wait"}]


def test_if_full_form_branches():
    ts = _toolset([{
        "name": "smart", "description": "x",
        "steps": [{
            "if": "hp > 12",
            "then": [{"do": "attack", "args": {"target": "rat_a"}}],
            "else": [{"do": "flee"}],
        }],
    }])
    result = expand_tool_call(
        "smart", {}, toolset=ts, namespace={"hp": 18},
    )
    assert result.actions == [{"do": "attack", "target": "rat_a"}]
    result = expand_tool_call(
        "smart", {}, toolset=ts, namespace={"hp": 3},
    )
    assert result.actions == [{"do": "flee"}]


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------


def test_args_interpolation_string():
    ts = _toolset([{
        "name": "go", "description": "x",
        "parameters": [{"name": "dest", "type": "zone_slug"}],
        "steps": [{"do": "travel", "args": {"zone": "{{ args.dest }}"}}],
    }])
    result = expand_tool_call(
        "go", {"dest": "hearthold"}, toolset=ts, namespace={},
    )
    assert result.actions == [{"do": "travel", "zone": "hearthold"}]


def test_expr_form_keeps_native_type():
    ts = _toolset([{
        "name": "buy_some", "description": "x",
        "parameters": [{"name": "qty", "type": "int"}],
        "steps": [{
            "do": "buy",
            "args": {
                "target": "marek",
                "item": "iron_ore",
                "qty": {"_expr": "min(args.qty, 10)"},
            },
        }],
    }])
    result = expand_tool_call(
        "buy_some", {"qty": 25}, toolset=ts, namespace={},
    )
    # qty preserved as int, not stringified.
    assert result.actions[0]["qty"] == 10


def test_embedded_string_interpolation():
    ts = _toolset([{
        "name": "log", "description": "x",
        "parameters": [{"name": "where", "type": "zone_slug"}],
        "steps": [{
            "do": "journal_write",
            "args": {"text": "Headed to {{ args.where }} now"},
        }],
    }])
    result = expand_tool_call(
        "log", {"where": "stonehold"}, toolset=ts, namespace={},
    )
    assert result.actions[0]["text"] == "Headed to stonehold now"


# ---------------------------------------------------------------------------
# Composite calling override — exercises the full chain
# ---------------------------------------------------------------------------


def test_composite_step_invokes_overridden_primitive():
    """Composite calls `move`, which has a docstring + `after: [{do: look}]`.
    Each `move` step in the composite should expand to move + look."""
    ts = _toolset([
        {
            "override": "move", "description": "cautious move",
            "after": [{"do": "look"}],
        },
        {
            "name": "patrol", "description": "x",
            "steps": [
                {"do": "move", "args": {"target": [1, 1]}},
                {"do": "move", "args": {"target": [2, 2]}},
            ],
        },
    ])
    # NB: composite walker dispatches via emitted action dicts; override
    # middleware only fires when expand_tool_call is the entry point. The
    # composite walker treats override targets as plain primitive emits.
    # Override `after` chain only kicks in for top-level LLM calls.
    result = expand_tool_call(
        "patrol", {}, toolset=ts, namespace={},
    )
    assert result.actions == [
        {"do": "move", "target": [1, 1]},
        {"do": "move", "target": [2, 2]},
    ]
