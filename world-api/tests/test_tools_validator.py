"""Validator unit tests for the manifest tools[] section (Phase 2 cut)."""

from __future__ import annotations

from app.domains.manifest_validate.router import VALID_VERBS
from app.domains.manifest_validate.tools_validator import validate_tools


def _err_paths(issues):
    return [i["path"] for i in issues if i["severity"] == "error"]


def test_no_tools_section_returns_clean():
    issues, parsed = validate_tools(None, valid_verbs=VALID_VERBS)
    assert issues == []
    assert parsed == []


def test_tools_must_be_list():
    issues, _ = validate_tools({"oops": True}, valid_verbs=VALID_VERBS)
    assert any("list" in i["message"] for i in issues)


def test_valid_composite_passes():
    issues, parsed = validate_tools(
        [{
            "name": "safe_gather",
            "description": "look then gather",
            "steps": [{"do": "look"}, {"do": "gather"}],
        }],
        valid_verbs=VALID_VERBS,
    )
    assert _err_paths(issues) == []
    assert len(parsed) == 1


def test_composite_unknown_verb_rejected():
    issues, _ = validate_tools(
        [{
            "name": "bad",
            "description": "x",
            "steps": [{"do": "magic_uncle"}],
        }],
        valid_verbs=VALID_VERBS,
    )
    assert any("magic_uncle" in i["message"] for i in issues)


def test_composite_step_can_reference_sibling_composite():
    issues, _ = validate_tools(
        [
            {
                "name": "inner",
                "description": "x",
                "steps": [{"do": "look"}],
            },
            {
                "name": "outer",
                "description": "x",
                "steps": [{"do": "inner"}],
            },
        ],
        valid_verbs=VALID_VERBS,
    )
    assert _err_paths(issues) == []


def test_self_reference_rejected():
    issues, _ = validate_tools(
        [{
            "name": "loopy",
            "description": "x",
            "steps": [{"do": "loopy"}],
        }],
        valid_verbs=VALID_VERBS,
    )
    assert any("loopy" in i["message"] for i in issues)


def test_indirect_cycle_detected():
    issues, _ = validate_tools(
        [
            {"name": "aaa", "description": "x", "steps": [{"do": "bbb"}]},
            {"name": "bbb", "description": "x", "steps": [{"do": "aaa"}]},
        ],
        valid_verbs=VALID_VERBS,
    )
    cycle_msgs = [i["message"] for i in issues if "cycle" in i["message"]]
    assert cycle_msgs


def test_expansion_depth_budget_caps():
    # Two leaf composites of 8 primitives each. An "outer" that calls both
    # expands to 16 — exactly at the limit. Adding one more primitive step
    # tips it over.
    inner_a = {"name": "inner_a", "description": "x", "steps": [{"do": "look"}] * 8}
    inner_b = {"name": "inner_b", "description": "x", "steps": [{"do": "look"}] * 8}
    at_limit = {
        "name": "outer", "description": "x",
        "steps": [{"do": "inner_a"}, {"do": "inner_b"}],
    }
    issues, _ = validate_tools(
        [inner_a, inner_b, at_limit], valid_verbs=VALID_VERBS,
    )
    over_budget_errors = [
        i for i in issues if "expands" in i["message"] and "outer" in i["message"]
    ]
    assert not over_budget_errors

    over = {
        "name": "outer", "description": "x",
        "steps": [{"do": "inner_a"}, {"do": "inner_b"}, {"do": "look"}],
    }
    issues, _ = validate_tools(
        [inner_a, inner_b, over], valid_verbs=VALID_VERBS,
    )
    assert any(
        "expands" in i["message"] and "outer" in i["message"]
        for i in issues
    )


def test_composite_shadowing_primitive_rejected():
    issues, _ = validate_tools(
        [{
            "name": "attack",  # primitive — needs override:
            "description": "x",
            "steps": [{"do": "look"}],
        }],
        valid_verbs=VALID_VERBS,
    )
    assert any("shadows primitive" in i["message"] for i in issues)


def test_invoke_llm_rejected_in_composite_step():
    issues, _ = validate_tools(
        [{
            "name": "sneak",
            "description": "x",
            "steps": [{"do": "invoke_llm"}],
        }],
        valid_verbs=VALID_VERBS,
    )
    assert any("invoke_llm" in i["message"] for i in issues)


def test_override_for_unknown_verb_rejected():
    issues, _ = validate_tools(
        [{"override": "ride_unicorn", "description": "x"}],
        valid_verbs=VALID_VERBS,
    )
    assert any("ride_unicorn" in i["message"] for i in issues)


def test_when_expression_validated():
    # Valid when: passes
    issues, _ = validate_tools(
        [{"override": "gather", "description": "x", "when": "hp > 8"}],
        valid_verbs=VALID_VERBS,
    )
    assert _err_paths(issues) == []
    # Garbage when: rejected
    issues, _ = validate_tools(
        [{"override": "gather", "description": "x", "when": "hp >>>"}],
        valid_verbs=VALID_VERBS,
    )
    assert any("syntax" in i["message"] or "unsafe" in i["message"] for i in issues)


def test_clamp_param_must_be_clampable():
    # Clamping `target` of attack (in CLAMP_TABLE) — passes
    issues, _ = validate_tools(
        [{"override": "attack", "description": "x", "clamp": {"target": "requested"}}],
        valid_verbs=VALID_VERBS,
    )
    assert _err_paths(issues) == []
    # Clamping a non-existent param of attack — rejected
    issues, _ = validate_tools(
        [{"override": "attack", "description": "x", "clamp": {"distance": "1"}}],
        valid_verbs=VALID_VERBS,
    )
    assert any("not a clampable" in i["message"] for i in issues)


def test_after_step_cannot_call_overridden_verb():
    issues, _ = validate_tools(
        [{
            "override": "move", "description": "x",
            "after": [{"do": "move"}],
        }],
        valid_verbs=VALID_VERBS,
    )
    assert any("would loop" in i["message"] for i in issues)


def test_if_step_in_composite_passes_with_valid_expression():
    issues, _ = validate_tools(
        [{
            "name": "branchy",
            "description": "x",
            "steps": [{"if": "hp > 0", "do": "look"}],
        }],
        valid_verbs=VALID_VERBS,
    )
    assert _err_paths(issues) == []


def test_if_step_full_form_passes():
    issues, _ = validate_tools(
        [{
            "name": "smart",
            "description": "x",
            "steps": [{
                "if": "hp > 12",
                "then": [{"do": "attack", "args": {"target": "rat_a"}}],
                "else": [{"do": "flee"}],
            }],
        }],
        valid_verbs=VALID_VERBS,
    )
    assert _err_paths(issues) == []


def test_docstring_only_override_passes():
    issues, parsed = validate_tools(
        [{"override": "gather", "description": "ONLY when item_at_my_tile..."}],
        valid_verbs=VALID_VERBS,
    )
    assert _err_paths(issues) == []
    assert len(parsed) == 1


def test_duplicate_tool_names_rejected():
    issues, _ = validate_tools(
        [
            {"name": "twin", "description": "x", "steps": [{"do": "look"}]},
            {"name": "twin", "description": "x", "steps": [{"do": "look"}]},
        ],
        valid_verbs=VALID_VERBS,
    )
    assert any("duplicate" in i["message"] for i in issues)
