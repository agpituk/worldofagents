"""Integration tests — every GRAMMAR.md §11 worked example deploys,
validates, and dispatches end-to-end with the expected trace shape.

Together these are the headline acceptance: if the spec's worked
examples don't run, the feature isn't shipped. Each test:
  1. Wraps the example in a minimal manifest.
  2. Runs it through the validator (must pass with no errors).
  3. Runs the dispatcher with synthetic args/namespace.
  4. Asserts the trace events / actions match the spec's intent.
"""

from __future__ import annotations

import pytest

from app.domains.manifest_validate.router import VALID_VERBS
from app.domains.manifest_validate.tools_validator import validate_tools

from arena_bot.tool_dispatch import HeroToolset, expand_tool_call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate(tools_yaml: list[dict]) -> None:
    issues, _ = validate_tools(tools_yaml, valid_verbs=VALID_VERBS)
    errors = [i for i in issues if i["severity"] == "error"]
    assert errors == [], f"validator rejected: {errors}"


def _dispatch(
    tools_yaml: list[dict], tool: str, args: dict, namespace: dict | None = None,
):
    toolset = HeroToolset.from_manifest({"hero": {"tools": tools_yaml}})
    events: list[tuple[str, dict]] = []
    result = expand_tool_call(
        tool, args, toolset=toolset,
        namespace=namespace or {},
        trace=lambda e, p: events.append((e, p)),
    )
    return result, events


# ---------------------------------------------------------------------------
# §11.1 — Cautious move
# ---------------------------------------------------------------------------


def test_11_1_cautious_move():
    """Override of `move` with `when:` (not in_pvp_zone()) and `after: [look]`.
    Adapted: GRAMMAR.md uses `clamp.distance`, but the actual `move`
    primitive takes `target` (a tile). See IMPL_PLAN §2.1.
    """
    tools = [
        {
            "override": "move",
            "description": (
                "Cautious move. Never travels into PvP zones, always looks afterward."
            ),
            "when": "not in_pvp_zone()",
            "after": [{"do": "look"}],
        },
    ]
    _validate(tools)
    ns = {"in_pvp_zone": lambda: False}
    result, events = _dispatch(tools, "move", {"target": [3, 4]}, ns)
    assert result.ok
    assert result.actions[0] == {"do": "move", "target": [3, 4]}
    assert any(a["do"] == "look" for a in result.actions[1:])
    assert any(e == "tool.after.step" for e, _ in events)

    # Now fail the gate.
    ns_pvp = {"in_pvp_zone": lambda: True}
    result, events = _dispatch(tools, "move", {"target": [3, 4]}, ns_pvp)
    assert any(e == "tool.gated" for e, _ in events)
    assert result.actions[0]["do"] == "wait"


# ---------------------------------------------------------------------------
# §11.2 — Hit-and-run
# ---------------------------------------------------------------------------


def test_11_2_shoot_and_flee():
    """Composite with parameter + interpolation."""
    tools = [
        {
            "name": "shoot_and_flee",
            "description": "Hit-and-run.",
            "parameters": [
                {"name": "retreat_to", "type": "zone_slug", "required": False, "default": "hearthold"},
            ],
            "steps": [
                {"do": "attack", "args": {"target": "rat_a"}},
                {
                    "if": "hp > 0",
                    "do": "travel",
                    "args": {"zone": "{{ args.retreat_to }}"},
                },
                {
                    "do": "journal_write",
                    "args": {
                        "text": "Hit-and-run executed; retreated to {{ args.retreat_to }}",
                        "tags": ["tactic_log"],
                    },
                },
            ],
        },
    ]
    _validate(tools)
    result, events = _dispatch(
        tools, "shoot_and_flee", {"retreat_to": "stonehold"}, {"hp": 12},
    )
    assert any(e == "tool.expanded" for e, _ in events)
    do_list = [a["do"] for a in result.actions]
    assert do_list == ["attack", "travel", "journal_write"]
    assert result.actions[1]["zone"] == "stonehold"
    # Default kicks in when arg omitted
    result, _ = _dispatch(tools, "shoot_and_flee", {}, {"hp": 12})
    assert result.actions[1]["zone"] == "hearthold"


# ---------------------------------------------------------------------------
# §11.3 — Docstring-only override
# ---------------------------------------------------------------------------


def test_11_3_docstring_only_override():
    """No when/clamp/after — just rewrites the description shown to the LLM.
    At dispatch time it's a no-op passthrough."""
    from arena_bot.actions import DEFAULT_TOOLS
    from arena_bot.tools import build_tool_specs_for_hero

    tools = [
        {
            "override": "gather",
            "description": (
                "Harvest the resource on your tile. ONLY call when "
                "item_at_my_tile('resource') is true."
            ),
        },
    ]
    _validate(tools)
    toolset = HeroToolset.from_manifest({"hero": {"tools": tools}})
    specs = build_tool_specs_for_hero(
        list(DEFAULT_TOOLS), list(toolset.overrides.values()),
    )
    gather = next(s for s in specs if s["function"]["name"] == "gather")
    assert "ONLY call" in gather["function"]["description"]


# ---------------------------------------------------------------------------
# §11.4 — Composite calling composite
# ---------------------------------------------------------------------------


def test_11_4_composite_calling_composite():
    tools = [
        {
            "name": "safe_gather",
            "description": "Look first; only gather if no hostiles visible.",
            "steps": [
                {"do": "look"},
                {"if": "not hostile_visible()", "do": "gather"},
            ],
        },
        {
            "name": "explore_and_gather",
            "description": "Move one tile, then attempt a safe gather.",
            "parameters": [{"name": "direction", "type": "string", "required": True}],
            "steps": [
                {"do": "look"},
                {"do": "safe_gather"},
            ],
        },
    ]
    _validate(tools)
    ns = {"hostile_visible": lambda: False}
    result, events = _dispatch(
        tools, "explore_and_gather", {"direction": "north"}, ns,
    )
    # Outer look + safe_gather expansion (look + gather since no hostile)
    do_list = [a["do"] for a in result.actions]
    assert do_list == ["look", "look", "gather"]
    expanded_tools = [p["tool"] for e, p in events if e == "tool.expanded"]
    assert "explore_and_gather" in expanded_tools
    assert "safe_gather" in expanded_tools


# ---------------------------------------------------------------------------
# §11.5 — Branching if-step
# ---------------------------------------------------------------------------


def test_11_5_smart_engage_then_branch():
    tools = [
        {
            "name": "smart_engage",
            "description": "Attack if advantaged, otherwise retreat.",
            "parameters": [
                {"name": "retreat_to", "type": "zone_slug", "required": False, "default": "hearthold"},
            ],
            "steps": [
                {
                    "if": "hp > 12 and weapon_equipped()",
                    "then": [{"do": "attack", "args": {"target": "rat_a"}}],
                    "else": [
                        {"do": "travel", "args": {"zone": "{{ args.retreat_to }}"}},
                    ],
                },
            ],
        },
    ]
    _validate(tools)
    ns_advantage = {"hp": 18, "weapon_equipped": lambda: True}
    result, _ = _dispatch(tools, "smart_engage", {}, ns_advantage)
    assert result.actions == [{"do": "attack", "target": "rat_a"}]

    ns_disadvantage = {"hp": 4, "weapon_equipped": lambda: False}
    result, _ = _dispatch(tools, "smart_engage", {}, ns_disadvantage)
    assert result.actions == [{"do": "travel", "zone": "hearthold"}]
