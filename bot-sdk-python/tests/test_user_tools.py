"""Decorator API tests."""

from __future__ import annotations

import yaml

from arena_bot.user_tools import (
    after,
    clamp,
    collect_tools,
    dump_tools_yaml,
    override,
    param,
    reset_registry,
    user_tool,
    when,
)


def setup_function() -> None:
    reset_registry()


def test_user_tool_collects_steps_from_yields():
    @user_tool(
        description="Hit-and-run.",
        parameters=[param("retreat_to", "zone_slug", default="hearthold")],
    )
    def shoot_and_flee():  # noqa: ANN201
        yield {"do": "attack", "args": {"target": "rat_a"}}
        yield {"do": "travel", "args": {"zone": "{{ args.retreat_to }}"}}

    tools = collect_tools()
    assert len(tools) == 1
    t = tools[0]
    assert t["name"] == "shoot_and_flee"
    assert t["description"] == "Hit-and-run."
    assert t["parameters"][0]["default"] == "hearthold"
    assert len(t["steps"]) == 2
    assert t["steps"][0]["do"] == "attack"


def test_override_with_when_clamp_after():
    @override("move", description="Cautious move.")
    @when("not in_pvp_zone()")
    @clamp(target="requested")
    @after({"do": "look"})
    def move_override():
        pass

    tools = collect_tools()
    assert len(tools) == 1
    t = tools[0]
    assert t["override"] == "move"
    assert t["when"] == "not in_pvp_zone()"
    assert t["clamp"] == {"target": "requested"}
    assert t["after"] == [{"do": "look"}]


def test_dump_tools_yaml_round_trips():
    @user_tool(description="x", parameters=[param("y", "string")])
    def thing():
        yield {"do": "look"}

    yaml_text = dump_tools_yaml()
    parsed = yaml.safe_load(yaml_text)
    assert "tools" in parsed
    assert parsed["tools"][0]["name"] == "thing"


def test_decorator_order_doesnt_matter():
    """All four decorators tolerate any stacking order."""

    @after({"do": "look"})
    @clamp(target="requested")
    @when("hp > 0")
    @override("attack")
    def _a():
        pass

    @override("attack")
    @when("hp > 0")
    @clamp(target="requested")
    @after({"do": "look"})
    def _b():
        pass

    tools = collect_tools()
    assert len(tools) == 2
    for t in tools:
        assert t["override"] == "attack"
        assert t["when"] == "hp > 0"
        assert t["clamp"] == {"target": "requested"}
        assert t["after"] == [{"do": "look"}]


def test_param_default_implies_required_false():
    p = param("x", "string", default="abc")
    assert p.required is False
    assert p.default == "abc"
