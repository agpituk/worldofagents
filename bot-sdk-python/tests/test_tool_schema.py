"""Parser tests for the manifest tools[] section."""

from __future__ import annotations

import pytest

from arena_bot.tool_schema import (
    CompositeTool,
    OverrideTool,
    ToolParseError,
    parse_tools,
)


def test_empty_or_missing_returns_empty_list():
    assert parse_tools(None) == []
    assert parse_tools([]) == []


def test_composite_minimal():
    tools = parse_tools([
        {"name": "safe_gather", "description": "look first, then gather",
         "steps": [{"do": "look"}, {"do": "gather"}]},
    ])
    assert len(tools) == 1
    assert isinstance(tools[0], CompositeTool)
    assert tools[0].name == "safe_gather"
    assert len(tools[0].steps) == 2


def test_override_with_description_only():
    tools = parse_tools([
        {"override": "gather", "description": "ONLY when item_at_my_tile..."},
    ])
    assert len(tools) == 1
    assert isinstance(tools[0], OverrideTool)
    assert tools[0].name == "gather"
    assert tools[0].override_verb == "gather"


def test_override_must_match_name_when_set():
    with pytest.raises(ToolParseError) as exc:
        parse_tools([
            {"name": "weird", "override": "gather", "description": "..."},
        ])
    assert "name" in exc.value.path


def test_composite_name_regex():
    with pytest.raises(ToolParseError):
        parse_tools([{"name": "Bad-Name", "description": "x", "steps": [{"do": "look"}]}])
    with pytest.raises(ToolParseError):
        parse_tools([{"name": "1starts_with_digit", "description": "x", "steps": [{"do": "look"}]}])
    # OK
    parse_tools([{"name": "ok_name", "description": "x", "steps": [{"do": "look"}]}])


def test_composite_too_many_steps():
    steps = [{"do": "look"}] * 9
    with pytest.raises(ToolParseError) as exc:
        parse_tools([{"name": "long", "description": "x", "steps": steps}])
    assert "steps" in exc.value.path


def test_composite_parameter_validation():
    # Non-required param without default fails
    with pytest.raises(ToolParseError):
        parse_tools([{
            "name": "pp", "description": "x",
            "parameters": [{"name": "xx", "type": "string", "required": False}],
            "steps": [{"do": "look"}],
        }])
    # Unknown type fails
    with pytest.raises(ToolParseError):
        parse_tools([{
            "name": "pp", "description": "x",
            "parameters": [{"name": "xx", "type": "uuid"}],
            "steps": [{"do": "look"}],
        }])
    # Valid
    tools = parse_tools([{
        "name": "pp", "description": "x",
        "parameters": [
            {"name": "tgt", "type": "zone_slug", "required": False, "default": "hearthold"},
        ],
        "steps": [{"do": "look"}],
    }])
    assert len(tools[0].parameters) == 1
    assert tools[0].parameters[0].default == "hearthold"


def test_override_with_no_effect_rejected():
    with pytest.raises(ToolParseError):
        parse_tools([{"override": "gather"}])


def test_override_and_steps_mutually_exclusive():
    with pytest.raises(ToolParseError):
        parse_tools([{
            "override": "gather", "description": "x",
            "steps": [{"do": "look"}],
        }])


def test_if_step_simple_form_parses():
    tools = parse_tools([{
        "name": "comp", "description": "x",
        "steps": [{"if": "hp > 0", "do": "look"}],
    }])
    assert isinstance(tools[0], CompositeTool)


def test_if_step_full_form_parses():
    tools = parse_tools([{
        "name": "comp", "description": "x",
        "steps": [{
            "if": "hp > 0",
            "then": [{"do": "look"}],
            "else": [{"do": "wait"}],
        }],
    }])
    assert isinstance(tools[0], CompositeTool)


def test_nested_if_rejected():
    with pytest.raises(ToolParseError):
        parse_tools([{
            "name": "comp", "description": "x",
            "steps": [{
                "if": "hp > 0",
                "then": [{"if": "hp > 5", "then": [{"do": "look"}]}],
            }],
        }])
