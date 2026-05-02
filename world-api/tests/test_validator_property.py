"""Property tests for the tools validator + dispatcher.

We don't pull in Hypothesis for the SDK; instead, this module is a
focused property battery that:
  • Generates random *valid* manifests (within the spec's shape rules)
    and asserts the validator accepts every one.
  • Generates random *invalid* shapes (cycle, overflow, bad regex, etc.)
    and asserts the validator rejects with the expected error code.
  • Round-trips every accepted manifest through the dispatcher and
    asserts the trace shape is well-formed (no unhandled exceptions,
    no None action dicts in the result).
"""

from __future__ import annotations

import random
import string
from typing import Any

import pytest

from app.domains.manifest_validate.router import VALID_VERBS
from app.domains.manifest_validate.tools_validator import validate_tools

from arena_bot.tool_dispatch import HeroToolset, expand_tool_call


# ---------------------------------------------------------------------------
# Random valid manifest generator
# ---------------------------------------------------------------------------


SAFE_VERBS = ("look", "wait", "flee", "defend", "gather", "fish")


def _rand_name(rng: random.Random) -> str:
    n = rng.randint(2, 12)
    head = rng.choice(string.ascii_lowercase)
    rest = "".join(rng.choice(string.ascii_lowercase + string.digits + "_") for _ in range(n - 1))
    return head + rest


def _rand_step(rng: random.Random) -> dict[str, Any]:
    return {"do": rng.choice(SAFE_VERBS)}


def _rand_composite(rng: random.Random) -> dict[str, Any]:
    name = _rand_name(rng)
    n_steps = rng.randint(1, 6)
    return {
        "name": name,
        "description": "auto-generated composite for property tests",
        "steps": [_rand_step(rng) for _ in range(n_steps)],
    }


def _rand_override(rng: random.Random) -> dict[str, Any]:
    verb = rng.choice(list(VALID_VERBS - {"invoke_llm"}))
    return {
        "override": verb,
        "description": "auto-generated override",
    }


def _rand_manifest_tools(rng: random.Random, n: int) -> list[dict[str, Any]]:
    out = []
    used: set[str] = set()
    for _ in range(n):
        if rng.random() < 0.4:
            entry = _rand_override(rng)
        else:
            entry = _rand_composite(rng)
            # Ensure unique names
            base = entry["name"]
            i = 0
            while entry["name"] in used:
                i += 1
                entry["name"] = f"{base}_{i}"
            used.add(entry["name"])
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Property: every randomly-generated valid manifest is accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(20))
def test_random_valid_manifests_accepted(seed: int) -> None:
    rng = random.Random(seed)
    n = rng.randint(0, 8)
    tools = _rand_manifest_tools(rng, n)
    issues, parsed = validate_tools(tools, valid_verbs=VALID_VERBS)
    errors = [i for i in issues if i["severity"] == "error"]
    # If there are errors, the generator created a name collision among
    # overrides — the only legitimate "invalid" outcome from the
    # generator. Filter those out.
    non_dup_errors = [
        e for e in errors
        if "duplicate" not in e["message"]
    ]
    assert non_dup_errors == [], f"unexpected errors for seed={seed}: {non_dup_errors}"
    if not errors:
        assert len(parsed) == n


# ---------------------------------------------------------------------------
# Property: every accepted manifest dispatches without exceptions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(20))
def test_random_valid_manifests_dispatch_cleanly(seed: int) -> None:
    rng = random.Random(seed)
    tools = _rand_manifest_tools(rng, rng.randint(0, 8))
    toolset = HeroToolset.from_manifest({"hero": {"tools": tools}})

    for name, composite in toolset.composites.items():
        events: list = []
        result = expand_tool_call(
            name, {}, toolset=toolset, namespace={},
            trace=lambda e, p: events.append((e, p)),
        )
        assert result.actions is not None
        assert all(isinstance(a, dict) and "do" in a for a in result.actions)


# ---------------------------------------------------------------------------
# Property: known-invalid shapes are rejected with stable error codes
# ---------------------------------------------------------------------------


def test_self_referential_composite_rejected():
    tools = [
        {"name": "loop", "description": "x", "steps": [{"do": "loop"}]},
    ]
    issues, _ = validate_tools(tools, valid_verbs=VALID_VERBS)
    assert any("loop" in i["message"] for i in issues)


def test_too_many_steps_rejected():
    tools = [
        {
            "name": "wide",
            "description": "x",
            "steps": [{"do": "look"}] * 9,
        },
    ]
    issues, _ = validate_tools(tools, valid_verbs=VALID_VERBS)
    assert any("max 8 steps" in i["message"] for i in issues)


def test_bad_name_regex_rejected():
    for bad in ["A_uppercase", "1starts_with_digit", "has-hyphen", ""]:
        tools = [{"name": bad, "description": "x", "steps": [{"do": "look"}]}]
        issues, _ = validate_tools(tools, valid_verbs=VALID_VERBS)
        assert any("name" in i.get("path", "") for i in issues), f"name {bad!r} should reject"


def test_garbage_when_expression_rejected():
    tools = [
        {"override": "gather", "description": "x", "when": "this is not python >>>"},
    ]
    issues, _ = validate_tools(tools, valid_verbs=VALID_VERBS)
    assert any(
        "syntax" in i["message"] or "unsafe" in i["message"]
        for i in issues
    )


def test_clamp_for_unclampable_param_rejected():
    tools = [
        {"override": "look", "description": "x", "clamp": {"foo": "1"}},
    ]
    issues, _ = validate_tools(tools, valid_verbs=VALID_VERBS)
    assert any("not a clampable" in i["message"] for i in issues)


def test_invoke_llm_in_composite_step_rejected():
    tools = [
        {
            "name": "sneaky",
            "description": "x",
            "steps": [{"do": "invoke_llm"}],
        },
    ]
    issues, _ = validate_tools(tools, valid_verbs=VALID_VERBS)
    assert any("invoke_llm" in i["message"] for i in issues)
