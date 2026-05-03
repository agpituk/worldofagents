"""Sandbox for `when:` reflex expressions.

Reflex DSL is plain Python evaluated against a context dict. Without
constraints, a manifest like `when: "[0 for _ in range(10**9)]"` will
pin a CPU and stall the (currently single-threaded) tick loop —
FIX_PLAN P1-1's headline incident vector.

This module provides:

  • compile_safe(expr) — pre-compiles the expression and refuses any
    AST node outside the allowlist, plus any Attribute access whose
    name starts with `_` (rules out `().__class__.__bases__[...]`-style
    object-introspection escapes that would otherwise reach
    `BuiltinImporter` / `subprocess.Popen` / etc.).
  • CallCounter / wrap_callables — each reflex eval gets a fresh limit
    on helper invocations so a `hostile_visible() and hostile_visible()
    and ...` pyramid can't spin forever.

Pow (`**`) is intentionally NOT in the allowlist: a single
`2 ** (10**9)` would freeze the tick loop on bigint allocation, and
no current reflex grammar needs exponentiation. Re-introduce only with
a bounded-exponent helper.
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
    # Pow (**) intentionally omitted: 2**(10**9) would freeze the tick loop.
})


class UnsafeExpression(ValueError):
    """An expression contains an AST node we refuse to execute."""

    def __init__(self, node: ast.AST, expr: str, *, reason: str | None = None) -> None:
        self.node_kind = type(node).__name__
        self.expr = expr
        msg = f"unsafe AST node {self.node_kind!r} in reflex {expr!r}"
        if reason:
            msg += f" — {reason}"
        super().__init__(msg)


def compile_safe(expr: str) -> CodeType:
    """Parse + validate + compile a reflex expression."""
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODES:
            raise UnsafeExpression(node, expr)
        # Block underscore-prefixed attribute access. Rules out the
        # `().__class__.__bases__[0].__subclasses__()` family of escapes
        # that walk the type tree to reach `BuiltinImporter` / `Popen` /
        # etc. Single-underscore "private" attrs are also blocked since
        # any escape worth worrying about goes through them.
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise UnsafeExpression(
                node, expr, reason=f"attribute {node.attr!r} starts with '_'"
            )
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


# ---------------------------------------------------------------------------
# Override grammar helpers (Phase 3)
#
# Reflexes already get hero state + helpers via the wrapper layer; the
# override grammar in GRAMMAR.md §1.2 adds a small math/utility set
# (min, max, clamp, floor, ceil, abs, len) and the `requested` /
# `param(name)` bindings used inside `clamp:` expressions. These run
# through the same compile_safe + CallCounter machinery — no new
# evaluator.
# ---------------------------------------------------------------------------


import math


def _clamp(x: Any, lo: Any, hi: Any) -> Any:
    """3-arg clamp; documented in GRAMMAR.md §1.2."""
    if hi < lo:
        # User error — just return the low bound rather than swap silently.
        return lo
    return max(lo, min(hi, x))


OVERRIDE_HELPERS: dict[str, Any] = {
    "min": min,
    "max": max,
    "clamp": _clamp,
    "floor": math.floor,
    "ceil": math.ceil,
    "abs": abs,
    "len": len,
}


class _AttrDict:
    """Wraps a dict so `args.x` works in expressions. The whitelist
    forbids attribute writes, so this is read-only by construction."""

    __slots__ = ("_d",)

    def __init__(self, d: dict[str, Any]) -> None:
        self._d = d

    def __getattr__(self, name: str) -> Any:
        try:
            return self._d[name]
        except KeyError as e:
            raise AttributeError(name) from e

    def __getitem__(self, key: str) -> Any:
        return self._d[key]

    def __contains__(self, key: object) -> bool:
        return key in self._d


class ExpressionTypeError(TypeError):
    """Raised when an override expression returns a value of the wrong type
    (e.g., `when:` returned a non-bool). The dispatcher catches this and
    emits `tool.expression.type_error` so the inspector can render it."""


def sandbox_eval(
    expr: str,
    *,
    namespace: Mapping[str, Any],
    args: Mapping[str, Any] | None = None,
    requested: Any = None,
    param_lookup: Callable[[str], Any] | None = None,
    call_limit: int = 200,
) -> Any:
    """Compile + evaluate an override expression.

    Returns the raw value the expression produced. Callers that need a
    bool/numeric/etc. should use the higher-level helpers below or do
    their own coercion.

    The namespace gets:
      • Everything from `namespace` (hero state scalars + helper fns).
      • `OVERRIDE_HELPERS` (min/max/clamp/floor/ceil/abs/len).
      • `args.<name>` access via _AttrDict (when `args` provided).
      • `requested` and `param(name)` (when provided — `clamp` only).
    """
    code = compile_safe(expr)
    counter = CallCounter(call_limit)
    ns: dict[str, Any] = {}
    ns.update(OVERRIDE_HELPERS)
    ns.update(namespace)
    if args is not None:
        ns["args"] = _AttrDict(dict(args))
    if requested is not None:
        ns["requested"] = requested
    if param_lookup is not None:
        ns["param"] = param_lookup
    wrapped = wrap_callables(ns, counter)
    return eval(code, {"__builtins__": {}}, wrapped)


def sandbox_eval_bool(
    expr: str,
    *,
    namespace: Mapping[str, Any],
    args: Mapping[str, Any] | None = None,
) -> bool:
    """Evaluate a `when:` or `if:` condition. Non-bool result raises
    ExpressionTypeError; the dispatcher converts that into a structured
    trace event and treats the condition as false (gating the call)."""
    value = sandbox_eval(expr, namespace=namespace, args=args)
    if not isinstance(value, bool):
        raise ExpressionTypeError(
            f"expression {expr!r} returned {type(value).__name__}, expected bool"
        )
    return value
