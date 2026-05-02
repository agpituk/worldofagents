"""Override-grammar additions to the reflex sandbox (Phase 3)."""

from __future__ import annotations

import pytest

from arena_bot.reflex_sandbox import (
    CallLimitExceeded,
    ExpressionTypeError,
    sandbox_eval,
    sandbox_eval_bool,
)


def test_helpers_min_max_clamp():
    ns = {"hp": 5}
    assert sandbox_eval("min(hp, 10)", namespace=ns) == 5
    assert sandbox_eval("max(hp, 10)", namespace=ns) == 10
    assert sandbox_eval("clamp(hp, 0, 3)", namespace=ns) == 3
    assert sandbox_eval("clamp(hp, 7, 100)", namespace=ns) == 7


def test_helpers_floor_ceil_abs_len():
    assert sandbox_eval("floor(3.7)", namespace={}) == 3
    assert sandbox_eval("ceil(3.1)", namespace={}) == 4
    assert sandbox_eval("abs(-5)", namespace={}) == 5
    assert sandbox_eval("len('abc')", namespace={}) == 3


def test_args_attribute_access():
    assert sandbox_eval(
        "args.dest", namespace={}, args={"dest": "hearthold"},
    ) == "hearthold"


def test_requested_binding():
    assert sandbox_eval(
        "min(requested, 5)", namespace={}, requested=10,
    ) == 5
    assert sandbox_eval(
        "min(requested, 5)", namespace={}, requested=2,
    ) == 2


def test_param_lookup():
    args = {"x": 7, "y": 3}
    result = sandbox_eval(
        "param('x') + param('y')", namespace={}, args=args,
        param_lookup=lambda n: args.get(n),
    )
    assert result == 10


def test_when_returns_bool():
    assert sandbox_eval_bool("hp > 8", namespace={"hp": 12}) is True
    assert sandbox_eval_bool("hp > 8", namespace={"hp": 4}) is False


def test_when_non_bool_raises():
    with pytest.raises(ExpressionTypeError):
        sandbox_eval_bool("hp + 1", namespace={"hp": 12})


def test_call_limit_honored():
    """Pyramid of helper calls hits the 200-cap quickly."""
    expr = " and ".join(["len('a') > 0"] * 250)
    with pytest.raises(CallLimitExceeded):
        sandbox_eval_bool(expr, namespace={})


def test_unsafe_ast_rejected():
    """Comprehensions are forbidden — nothing changed in Phase 3."""
    from arena_bot.reflex_sandbox import UnsafeExpression

    with pytest.raises(UnsafeExpression):
        sandbox_eval("[x for x in [1, 2, 3]]", namespace={})


def test_helpers_callable_via_namespace():
    """Helpers from the user's namespace pass through (e.g., reflex
    helpers like `enemy_in_range()`)."""
    ns = {"enemy_in_range": lambda: True, "hp": 12}
    assert sandbox_eval_bool(
        "enemy_in_range() and hp > 5", namespace=ns,
    ) is True
