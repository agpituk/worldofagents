"""Per-hero tool spec assembly (Phase 2)."""

from __future__ import annotations

from arena_bot.actions import DEFAULT_TOOLS
from arena_bot.tool_dispatch import HeroToolset
from arena_bot.tools import build_tool_specs, build_tool_specs_for_hero


def test_no_manifest_tools_equals_defaults():
    specs = build_tool_specs_for_hero(list(DEFAULT_TOOLS), [])
    default = build_tool_specs(list(DEFAULT_TOOLS))
    assert {s["function"]["name"] for s in specs} == {
        s["function"]["name"] for s in default
    }


def test_docstring_override_replaces_description():
    ts = HeroToolset.from_manifest({"hero": {"tools": [
        {"override": "gather", "description": "ONLY when item_at_my_tile..."},
    ]}})
    specs = build_tool_specs_for_hero(
        list(DEFAULT_TOOLS), list(ts.overrides.values()),
    )
    gather_spec = next(s for s in specs if s["function"]["name"] == "gather")
    assert gather_spec["function"]["description"].startswith("ONLY when item_at_my_tile")


def test_composite_appears_in_spec_list():
    ts = HeroToolset.from_manifest({"hero": {"tools": [
        {
            "name": "safe_gather",
            "description": "look first then gather",
            "steps": [{"do": "look"}, {"do": "gather"}],
        },
    ]}})
    specs = build_tool_specs_for_hero(
        list(DEFAULT_TOOLS), list(ts.composites.values()),
    )
    by_name = {s["function"]["name"]: s for s in specs}
    assert "safe_gather" in by_name
    assert by_name["safe_gather"]["function"]["description"].startswith(
        "look first then gather"
    )


def test_composite_parameter_schema():
    ts = HeroToolset.from_manifest({"hero": {"tools": [
        {
            "name": "go_to",
            "description": "travel",
            "parameters": [
                {"name": "dest", "type": "zone_slug"},
                {"name": "haste", "type": "bool", "required": False, "default": False},
            ],
            "steps": [{"do": "travel", "args": {"zone": "{{ args.dest }}"}}],
        },
    ]}})
    specs = build_tool_specs_for_hero(
        list(DEFAULT_TOOLS), list(ts.composites.values()),
    )
    go_to = next(s for s in specs if s["function"]["name"] == "go_to")
    params = go_to["function"]["parameters"]
    assert "dest" in params["properties"]
    assert "haste" in params["properties"]
    assert params["properties"]["dest"]["type"] == "string"
    assert params["properties"]["haste"]["type"] == "boolean"
    assert params["required"] == ["dest"]
