"""Dispatcher tests for composite expansion (Phase 2)."""

from __future__ import annotations

from arena_bot.tool_dispatch import (
    ExpansionBudget,
    HeroToolset,
    expand_tool_call,
)


def _toolset(yaml_tools: list[dict]) -> HeroToolset:
    return HeroToolset.from_manifest({"hero": {"tools": yaml_tools}})


# ---------------------------------------------------------------------------
# Composite expansion
# ---------------------------------------------------------------------------


def test_primitive_passthrough():
    ts = _toolset([])
    result = expand_tool_call("attack", {"target": "rat_a"}, toolset=ts)
    assert result.ok
    assert result.actions == [{"do": "attack", "target": "rat_a"}]


def test_simple_composite_expands():
    ts = _toolset([{
        "name": "safe_gather",
        "description": "look first then gather",
        "steps": [{"do": "look"}, {"do": "gather"}],
    }])
    result = expand_tool_call("safe_gather", {}, toolset=ts)
    assert result.ok
    assert result.actions == [{"do": "look"}, {"do": "gather"}]


def test_composite_with_args_interpolation():
    ts = _toolset([{
        "name": "go_to",
        "description": "travel to a zone",
        "parameters": [{"name": "dest", "type": "zone_slug"}],
        "steps": [
            {"do": "travel", "args": {"zone": "{{ args.dest }}"}},
        ],
    }])
    result = expand_tool_call(
        "go_to", {"dest": "hearthold"}, toolset=ts,
    )
    assert result.actions == [{"do": "travel", "zone": "hearthold"}]


def test_composite_with_default_param():
    ts = _toolset([{
        "name": "go_home",
        "description": "go home",
        "parameters": [
            {"name": "dest", "type": "zone_slug", "required": False, "default": "hearthold"},
        ],
        "steps": [{"do": "travel", "args": {"zone": "{{ args.dest }}"}}],
    }])
    # No args supplied — default kicks in
    result = expand_tool_call("go_home", {}, toolset=ts)
    assert result.actions == [{"do": "travel", "zone": "hearthold"}]
    # Override the default
    result = expand_tool_call("go_home", {"dest": "stonehold"}, toolset=ts)
    assert result.actions == [{"do": "travel", "zone": "stonehold"}]


def test_composite_calling_composite():
    ts = _toolset([
        {
            "name": "safe_gather",
            "description": "look then gather",
            "steps": [{"do": "look"}, {"do": "gather"}],
        },
        {
            "name": "explore_safely",
            "description": "move then safe_gather",
            "steps": [{"do": "look"}, {"do": "safe_gather"}],
        },
    ])
    result = expand_tool_call("explore_safely", {}, toolset=ts)
    # Outer 'look' + inner 'look' + inner 'gather' = 3 primitives
    assert result.actions == [
        {"do": "look"}, {"do": "look"}, {"do": "gather"},
    ]


def test_budget_exceeded_returns_partial_or_wait():
    """Construct a composite chain that would exceed the budget."""
    # Six composites each calling the next, each with 4 primitives.
    # Worst case: ~24 primitives. Default budget = 16.
    chain_len = 6
    steps_per = 4
    tools_yaml = []
    for i in range(chain_len):
        steps = [{"do": "look"}] * steps_per
        if i + 1 < chain_len:
            steps.append({"do": f"chain{i + 1}"})
        tools_yaml.append({
            "name": f"chain{i}",
            "description": "x",
            "steps": steps,
        })
    ts = HeroToolset.from_manifest({"hero": {"tools": tools_yaml}})
    result = expand_tool_call("chain0", {}, toolset=ts, budget=ExpansionBudget(max_primitives=16))
    # We should have stopped at or before 16 primitives.
    assert len([a for a in result.actions if a.get("do") == "look"]) <= 16


def test_unknown_tool_falls_back_to_primitive_passthrough():
    """If the LLM calls a name we don't recognize as composite, treat it as
    a primitive — the world-api will reject if it's truly unknown."""
    ts = _toolset([])
    result = expand_tool_call("nonexistent_verb", {"x": 1}, toolset=ts)
    assert result.ok
    assert result.actions == [{"do": "nonexistent_verb", "x": 1}]
