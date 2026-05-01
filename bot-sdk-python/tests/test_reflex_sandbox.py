"""FIX_PLAN P1-1: an unsafe reflex must not be able to stall the world.

Pure-AST tests on the sandbox primitives, plus an integration test
through ReflexEngine to confirm a malicious manifest deploys with the
offending reflex disabled rather than poisoning the whole tick.
"""

from __future__ import annotations

import pytest

from arena_bot.reflex_sandbox import (
    CallCounter,
    CallLimitExceeded,
    UnsafeExpression,
    compile_safe,
    wrap_callables,
)


# --- AST allowlist ---------------------------------------------------------


@pytest.mark.parametrize("expr", [
    "1 + 1",
    "hp < 8",
    "adjacent_to('rat_a')",
    "hp < 30 and not enemy_in_range()",
    "hp_pct if hp_pct else 100",
    "[1, 2, 3]",
    "{'a': 1}",
    "items[0]",
    "value.attr",  # Attribute is allowed; the runtime ctx decides what's reachable.
])
def test_safe_expressions_compile(expr):
    code = compile_safe(expr)
    assert code is not None


@pytest.mark.parametrize("expr,expected_kind", [
    # Comprehensions are FIX_PLAN's headline incident vector — bombs the CPU.
    ("[0 for _ in range(10**9)]", "ListComp"),
    ("[x for x in range(100)]", "ListComp"),
    ("(x for x in range(100))", "GeneratorExp"),
    ("{x for x in range(100)}", "SetComp"),
    ("{k: v for k, v in items}", "DictComp"),
    # Walrus inside an if would let a reflex mutate ctx.
    ("(x := 1)", "NamedExpr"),
    # Lambdas would let a reflex smuggle in a closure to defer execution.
    ("lambda: 1", "Lambda"),
])
def test_unsafe_nodes_refused(expr, expected_kind):
    with pytest.raises(UnsafeExpression) as exc_info:
        compile_safe(expr)
    assert exc_info.value.node_kind == expected_kind


def test_syntax_error_propagates_as_syntax_error():
    """A genuinely malformed reflex (typo) is a SyntaxError, not an
    UnsafeExpression — engine handles both, but tests pin the type."""
    with pytest.raises(SyntaxError):
        compile_safe("hp <")


# --- call counter ----------------------------------------------------------


def test_call_counter_aborts_runaway():
    counter = CallCounter(limit=3)

    def helper():
        return True

    wrapped = wrap_callables({"helper": helper}, counter)
    h = wrapped["helper"]
    h(); h(); h()
    with pytest.raises(CallLimitExceeded):
        h()


def test_non_callables_pass_through():
    counter = CallCounter(limit=10)
    wrapped = wrap_callables({"hp": 30, "name": "rat"}, counter)
    assert wrapped["hp"] == 30
    assert wrapped["name"] == "rat"


# --- end-to-end through the reflex engine ----------------------------------


def _make_perception():
    from arena_bot.client import Perception
    return Perception(
        tick_id=1,
        your_state={"hp": 30, "pos": [5, 5]},
        perception={
            "visible_npcs": [], "visible_heroes": [], "inventory": [],
            "visible_items": [], "memory": {}, "zone": {"connections": [], "kind": "sanctuary"},
        },
        deadline_ms=6000,
    )


def test_unsafe_reflex_deploys_with_offender_disabled():
    """The headline FIX_PLAN P1-1 done-when: a manifest with one bad
    reflex still works — the world doesn't stall, the bad reflex is
    disabled, the rest of the manifest evaluates normally."""
    from arena_bot.reflexes import ReflexEngine

    specs = [
        {"when": "[0 for _ in range(10**9)]", "then": {"do": "wait"}},  # CPU bomb
        {"when": "hp < 100", "then": {"do": "defend"}},                  # safe
    ]
    engine = ReflexEngine(specs)
    action, debug = engine.evaluate_with_debug(_make_perception())
    assert action is not None
    assert action.get("do") == "defend"
    assert debug["reflex_index"] == 1


def test_runaway_helper_calls_disable_only_that_reflex():
    """A reflex that bombs `hostile_visible() and hostile_visible() and ...`
    times 1000 is shut down by the call counter without taking out the
    rest of the manifest."""
    from arena_bot.reflexes import ReflexEngine

    bomb = " and ".join(["hostile_visible()"] * 1000)
    specs = [
        {"when": bomb, "then": {"do": "wait"}},
        {"when": "hp == 30", "then": {"do": "defend"}},
    ]
    engine = ReflexEngine(specs)
    action, _ = engine.evaluate_with_debug(_make_perception())
    assert action is not None and action.get("do") == "defend"
