"""Sandbox for `when:` reflex expressions.

Reflex DSL is plain Python evaluated against a context dict. Without
constraints, a manifest like `when: "[0 for _ in range(10**9)]"` will
pin a CPU and stall the (currently single-threaded) tick loop —
FIX_PLAN P1-1's headline incident vector.

This module provides:

  • compile_safe(expr) — pre-compiles the expression and refuses any
    AST node outside the allowlist. The expensive shapes (comprehensions,
    yields, walrus, attribute walks to non-allowed names) are rejected
    at compile time, before they touch a hero.
  • CallCounter / wrap_callables — each reflex eval gets a fresh limit
    on helper invocations so a `hostile_visible() and hostile_visible()
    and ...` pyramid can't spin forever.

Wall-clock timeout via thread + signal is deliberately deferred; with
the AST allowlist + call counter, the remaining attack surface is
"compute a huge int via **" which is a separate (mitigatable) hazard
worth its own change.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from types import CodeType
from typing import Any, Callable

# Nodes the reflex DSL may use. Anything outside this set raises
# UnsafeExpression at compile-time. The allowlist is the FIX_PLAN one
# minus comprehensions and Yield, plus Slice/Starred/keyword which
# safe expressions of allowed shapes can produce.
_ALLOWED_NODES: frozenset[type[ast.AST]] = frozenset({
    ast.Expression,
    ast.BoolOp, ast.And, ast.Or,
    ast.BinOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.LShift, ast.RShift, ast.BitAnd, ast.BitOr, ast.BitXor,
    ast.UnaryOp, ast.UAdd, ast.USub, ast.Not, ast.Invert,
    ast.Compare,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn,
    ast.Call,
    ast.Attribute, ast.Subscript,
    ast.Name, ast.Constant, ast.Load,
    ast.List, ast.Tuple, ast.Dict, ast.Set,
    ast.IfExp,
    ast.Slice,
    ast.Starred, ast.keyword,
    # Pow is allowed but expensive — see module docstring.
    ast.Pow,
})


class UnsafeExpression(ValueError):
    """An expression contains an AST node we refuse to execute."""

    def __init__(self, node: ast.AST, expr: str) -> None:
        self.node_kind = type(node).__name__
        self.expr = expr
        super().__init__(f"unsafe AST node {self.node_kind!r} in reflex {expr!r}")


def compile_safe(expr: str) -> CodeType:
    """Parse + validate + compile a reflex expression."""
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODES:
            raise UnsafeExpression(node, expr)
    return compile(tree, "<reflex>", "eval")


# ---------------------------------------------------------------------------
# Call counter — one bomb that aborts a runaway helper invocation
# ---------------------------------------------------------------------------


class CallLimitExceeded(RuntimeError):
    """Raised when a reflex evaluation invoked helpers more than the cap."""


class CallCounter:
    __slots__ = ("count", "limit")

    def __init__(self, limit: int) -> None:
        self.count = 0
        self.limit = limit

    def bump(self) -> None:
        self.count += 1
        if self.count > self.limit:
            raise CallLimitExceeded(f"reflex eval exceeded {self.limit} helper calls")


def wrap_callables(ctx: Mapping[str, Any], counter: CallCounter) -> dict[str, Any]:
    """Return a new context where every callable in `ctx` is wrapped to bump
    the counter on each invocation. Non-callables pass through untouched."""

    def _wrap(fn: Callable) -> Callable:
        def _bumped(*args: Any, **kwargs: Any):
            counter.bump()
            return fn(*args, **kwargs)
        _bumped.__name__ = getattr(fn, "__name__", "wrapped")
        return _bumped

    out: dict[str, Any] = {}
    for k, v in ctx.items():
        out[k] = _wrap(v) if callable(v) else v
    return out
