"""Decorator API for authoring tools in Python.

Convenience wrappers that emit canonical YAML matching the manifest
shape in GRAMMAR.md §0. The decorators are syntactic sugar — the same
server-side validator runs against both YAML-authored and decorator-
authored tools, so there's no second source of truth.

Example
-------

    from arena_bot.actions import attack_nearest_hostile, travel
    from arena_bot.user_tools import (
        user_tool, override, when, clamp, after, param,
    )

    @user_tool(
        description="Hit-and-run: attack nearest, retreat to sanctuary.",
        parameters=[param("retreat_to", "zone_slug", default="hearthold")],
    )
    def shoot_and_flee():
        yield {"do": "attack_nearest_hostile"}
        yield {"do": "travel", "args": {"zone": "{{ args.retreat_to }}"}}

    @override("move", description="Cautious move; never PvP, half-distance.")
    @when("not in_pvp_zone()")
    @clamp(distance="min(requested, max_move_distance() // 2)")
    @after({"do": "look"})
    def move_override():
        pass

`dump_tools(...)` collects every decorated function in a module and
returns a YAML string the player can paste into their manifest's
`tools:` section, or feed to `arena-bot manifest dump`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import yaml


_DECORATED_FNS: list[Callable[..., Any]] = []


@dataclass
class ParamSpec:
    name: str
    type: str
    required: bool = True
    default: Any = None


def param(
    name: str,
    type: str,
    *,
    required: bool = True,
    default: Any = None,
) -> ParamSpec:
    """Build a parameter declaration for `@user_tool(parameters=[...])`."""
    if default is not None:
        required = False
    return ParamSpec(name=name, type=type, required=required, default=default)


# ---------------------------------------------------------------------------
# Decorators — Shape B (composite)
# ---------------------------------------------------------------------------


def user_tool(
    *,
    description: str,
    parameters: list[ParamSpec] | None = None,
    name: str | None = None,
):
    """Decorate a generator function — each `yield`-ed step becomes one
    entry in the composite's `steps:` list.

    Steps must be plain dicts of the manifest step shape (`{do, args}`,
    or `{if, do/then/else}`). The function body is evaluated *once*
    at registration time to harvest the steps.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        composite_name = name or fn.__name__
        try:
            steps = list(fn())
        except Exception as exc:
            raise ValueError(
                f"@user_tool({composite_name!r}) body raised at registration: {exc}"
            ) from exc
        normalized = [_normalize_step(s) for s in steps]
        params_yaml = [_param_to_dict(p) for p in (parameters or [])]
        entry: dict[str, Any] = {
            "name": composite_name,
            "description": description.strip(),
        }
        if params_yaml:
            entry["parameters"] = params_yaml
        entry["steps"] = normalized
        fn.__user_tool__ = entry  # type: ignore[attr-defined]
        _DECORATED_FNS.append(fn)
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Decorators — Shape A (override)
# ---------------------------------------------------------------------------


def _ensure_override_entry(fn: Callable[..., Any]) -> dict[str, Any]:
    entry = getattr(fn, "__override__", None)
    if entry is None:
        entry = {}
        fn.__override__ = entry  # type: ignore[attr-defined]
        if fn not in _DECORATED_FNS:
            _DECORATED_FNS.append(fn)
    return entry


def override(verb: str, *, description: str | None = None):
    """Mark a function as a docstring/grammar override of the named
    primitive verb. The decorated function's body is ignored — the
    `@when`/`@clamp`/`@after` decorators on it carry the override
    behavior. Any decorator order works."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        entry = _ensure_override_entry(fn)
        entry["override"] = verb
        if description:
            entry["description"] = description.strip()
        return fn

    return decorator


def when(expression: str):
    """Add a `when:` gate. Companion to `@override`."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        entry = _ensure_override_entry(fn)
        entry["when"] = expression
        return fn

    return decorator


def clamp(**clamps: str):
    """Add `clamp:` expressions for the override's parameters.

    Usage: ``@clamp(distance="min(requested, 5)", target="requested")``.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        entry = _ensure_override_entry(fn)
        entry.setdefault("clamp", {}).update(clamps)
        return fn

    return decorator


def after(*steps: dict[str, Any]):
    """Add `after:` post-execution chain to an override.

    Each step is a dict in the manifest step shape (`{do: ...}` or
    `{if: ..., do: ...}` etc.).
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        entry = _ensure_override_entry(fn)
        entry.setdefault("after", []).extend(_normalize_step(s) for s in steps)
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Collection / serialization
# ---------------------------------------------------------------------------


def collect_tools() -> list[dict[str, Any]]:
    """Return tool entries from every decorated function loaded in the
    current process, in registration order.
    """
    out: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for fn in _DECORATED_FNS:
        if id(fn) in seen_ids:
            continue
        seen_ids.add(id(fn))
        if hasattr(fn, "__user_tool__"):
            out.append(fn.__user_tool__)  # type: ignore[attr-defined]
        if hasattr(fn, "__override__"):
            out.append(fn.__override__)  # type: ignore[attr-defined]
    return out


def dump_tools_yaml() -> str:
    """Serialize all decorated tools as a YAML `tools:` block."""
    return yaml.safe_dump(
        {"tools": collect_tools()},
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


def reset_registry() -> None:
    """Clear the registry. Tests use this to isolate cases."""
    _DECORATED_FNS.clear()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _param_to_dict(p: ParamSpec) -> dict[str, Any]:
    out: dict[str, Any] = {"name": p.name, "type": p.type, "required": p.required}
    if not p.required and p.default is not None:
        out["default"] = p.default
    return out


def _normalize_step(step: Any) -> dict[str, Any]:
    if not isinstance(step, dict):
        raise TypeError(f"step must be a dict, got {type(step).__name__}")
    return dict(step)
