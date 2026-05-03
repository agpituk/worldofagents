"""Argument-resolution helpers for composite/override tool dispatch.

Handles defaulting, `{{ expr }}` string interpolation, and `{_expr: …}`
native-typed evaluation per GRAMMAR.md §5.3. Pulled out of
`tool_dispatch.py` to keep the dispatcher focused on expansion logic.
"""

from __future__ import annotations

import re
from typing import Any

from arena_bot.reflex_sandbox import sandbox_eval
from arena_bot.tool_schema import ParamDef


_INTERP_RE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)


def apply_defaults(
    args: dict[str, Any], param_defs: list[ParamDef]
) -> dict[str, Any]:
    out = dict(args)
    for p in param_defs:
        if p.name not in out and not p.required and p.default is not None:
            out[p.name] = p.default
    return out


def resolve_args(
    step_args: dict[str, Any],
    parent_args: dict[str, Any],
    namespace: dict[str, Any],
) -> dict[str, Any]:
    """GRAMMAR.md §5.3 interpolation:
      • String values containing `{{ expr }}` — render through sandbox,
        result coerced to string (each {{ }} block independently).
      • Dict value `{_expr: "..."}` — evaluate; result keeps native type.
      • Other values pass through.
    """
    return {k: resolve_value(v, parent_args, namespace) for k, v in step_args.items()}


def resolve_value(
    v: Any, parent_args: dict[str, Any], namespace: dict[str, Any],
) -> Any:
    if isinstance(v, dict) and set(v.keys()) == {"_expr"}:
        try:
            return sandbox_eval(v["_expr"], namespace=namespace, args=parent_args)
        except Exception:
            return None
    if isinstance(v, str) and "{{" in v:
        return interpolate_string(v, parent_args, namespace)
    if isinstance(v, list):
        return [resolve_value(x, parent_args, namespace) for x in v]
    if isinstance(v, dict):
        return {k: resolve_value(x, parent_args, namespace) for k, x in v.items()}
    return v


def interpolate_string(
    s: str, parent_args: dict[str, Any], namespace: dict[str, Any],
) -> str:
    """Replace each {{ expr }} with its evaluated value (cast to str).
    If a single {{ }} block spans the whole string and the result is
    not a string, return the native value — this preserves the common
    case `{{ args.dest }}` for slug pass-through without stringifying."""
    stripped = s.strip()
    m = _INTERP_RE.fullmatch(stripped)
    if m is not None:
        expr = m.group(1).strip()
        try:
            return sandbox_eval(expr, namespace=namespace, args=parent_args)
        except Exception:
            return s

    def _replace(match: re.Match) -> str:
        expr = match.group(1).strip()
        try:
            value = sandbox_eval(expr, namespace=namespace, args=parent_args)
        except Exception:
            return match.group(0)
        return str(value)

    return _INTERP_RE.sub(_replace, s)
