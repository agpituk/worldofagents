"""Parsed representation of the manifest's `tools:` section.

The validator (`world-api/app/domains/manifest_validate/tools_validator.py`)
and the dispatcher (`bot-sdk-python/src/arena_bot/tool_dispatch.py`) both
consume these dataclasses. The same code runs server-side and SDK-side —
this module is the single source of truth for the shape.

GRAMMAR.md §0 defines two ToolDef shapes:
  • Shape A — override of an existing primitive verb (`override:` set)
  • Shape B — composite tool (named sequence of steps, exposed to LLM)

Phase 2 ships composites + docstring-only overrides. `when`/`clamp`/
`after`/`if`-step land in Phase 3 — the dataclasses already have those
fields so the schema is stable across phases; Phase 2 validator simply
rejects any tool that sets them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_PARAM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,20}$")

PARAM_TYPES: frozenset[str] = frozenset({
    "int", "float", "string", "bool",
    "slug", "npc_slug", "zone_slug", "item_slug", "spell_slug",
    "tile",
})


@dataclass(frozen=True)
class ParamDef:
    name: str
    type: str
    required: bool = True
    default: Any = None


@dataclass
class CompositeTool:
    """Shape B — a named sequence the LLM sees as a new tool."""
    name: str
    description: str
    parameters: list[ParamDef] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    kind: Literal["composite"] = "composite"


@dataclass
class OverrideTool:
    """Shape A — replaces description / gates / shapes a primitive verb.

    Phase 2: only `description` is honored (the LLM sees a different
    docstring). `when`/`clamp`/`after` are validated as forbidden until
    Phase 3 lands.
    """
    name: str
    override_verb: str
    description: str | None = None
    when_expr: str | None = None
    clamp: dict[str, str] = field(default_factory=dict)
    after: list[dict[str, Any]] = field(default_factory=list)
    kind: Literal["override"] = "override"


ToolDef = CompositeTool | OverrideTool


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class ToolParseError(ValueError):
    """Surfaces a *path* and *message* the validator can render as an Issue."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


def parse_tools(raw: Any) -> list[ToolDef]:
    """Best-effort parse. Anything malformed becomes a ToolParseError so the
    caller can render a structured validation issue. The validator wraps
    this and continues collecting other issues.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ToolParseError("tools", f"must be a list (got {type(raw).__name__})")

    out: list[ToolDef] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ToolParseError(
                f"tools[{i}]",
                f"each entry must be a mapping (got {type(entry).__name__})",
            )
        out.append(_parse_one(entry, f"tools[{i}]"))
    return out


def _parse_one(entry: dict[str, Any], path: str) -> ToolDef:
    has_override = "override" in entry
    has_steps = "steps" in entry

    if has_override and has_steps:
        raise ToolParseError(
            path,
            "tool entry has both `override:` and `steps:` — pick one (Shape A or B)",
        )
    if has_override:
        return _parse_override(entry, path)
    return _parse_composite(entry, path)


def _parse_composite(entry: dict[str, Any], path: str) -> CompositeTool:
    name = entry.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ToolParseError(
            f"{path}.name",
            "composite name must match ^[a-z][a-z0-9_]{1,30}$",
        )
    desc = entry.get("description")
    if not isinstance(desc, str) or not (1 <= len(desc) <= 600):
        raise ToolParseError(
            f"{path}.description",
            "composite description is required and must be 1–600 chars",
        )

    raw_params = entry.get("parameters", []) or []
    if not isinstance(raw_params, list):
        raise ToolParseError(
            f"{path}.parameters",
            f"parameters must be a list (got {type(raw_params).__name__})",
        )
    if len(raw_params) > 4:
        raise ToolParseError(
            f"{path}.parameters",
            f"max 4 parameters per composite (got {len(raw_params)})",
        )
    params = [_parse_param(p, f"{path}.parameters[{i}]") for i, p in enumerate(raw_params)]
    seen_names: set[str] = set()
    for p in params:
        if p.name in seen_names:
            raise ToolParseError(
                f"{path}.parameters",
                f"duplicate parameter name '{p.name}'",
            )
        seen_names.add(p.name)

    raw_steps = entry.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ToolParseError(
            f"{path}.steps",
            "composite must have a non-empty `steps:` list",
        )
    if len(raw_steps) > 8:
        raise ToolParseError(
            f"{path}.steps",
            f"max 8 steps per composite (got {len(raw_steps)})",
        )
    for i, step in enumerate(raw_steps):
        _check_step_shape(step, f"{path}.steps[{i}]")

    return CompositeTool(
        name=name,
        description=desc,
        parameters=params,
        steps=raw_steps,
    )


def _parse_override(entry: dict[str, Any], path: str) -> OverrideTool:
    verb = entry.get("override")
    if not isinstance(verb, str):
        raise ToolParseError(f"{path}.override", "override must be a verb string")
    name = entry.get("name", verb)
    if not isinstance(name, str):
        raise ToolParseError(f"{path}.name", "name must be a string")
    if name != verb:
        raise ToolParseError(
            f"{path}.name",
            f"override entry's name must equal `override` value or be omitted (got name={name!r}, override={verb!r})",
        )

    desc = entry.get("description")
    if desc is not None:
        if not isinstance(desc, str) or not (1 <= len(desc) <= 600):
            raise ToolParseError(
                f"{path}.description",
                "description must be 1–600 chars when provided",
            )

    when_expr = entry.get("when")
    if when_expr is not None and not isinstance(when_expr, str):
        raise ToolParseError(f"{path}.when", "when must be a string expression")

    clamp = entry.get("clamp") or {}
    if not isinstance(clamp, dict):
        raise ToolParseError(f"{path}.clamp", "clamp must be a mapping")
    for cp_name, cp_expr in clamp.items():
        if not isinstance(cp_name, str) or not isinstance(cp_expr, str):
            raise ToolParseError(
                f"{path}.clamp.{cp_name}",
                "clamp param keys and expressions must be strings",
            )

    after = entry.get("after") or []
    if not isinstance(after, list):
        raise ToolParseError(f"{path}.after", "after must be a list of steps")
    if len(after) > 4:
        raise ToolParseError(f"{path}.after", f"max 4 after steps (got {len(after)})")
    for i, step in enumerate(after):
        _check_step_shape(step, f"{path}.after[{i}]")

    if desc is None and when_expr is None and not clamp and not after:
        raise ToolParseError(
            path,
            "override has no effect — set at least one of description / when / clamp / after",
        )

    return OverrideTool(
        name=name,
        override_verb=verb,
        description=desc,
        when_expr=when_expr,
        clamp=clamp,
        after=after,
    )


def _parse_param(raw: Any, path: str) -> ParamDef:
    if not isinstance(raw, dict):
        raise ToolParseError(path, f"parameter must be a mapping (got {type(raw).__name__})")
    name = raw.get("name")
    if not isinstance(name, str) or not _PARAM_NAME_RE.match(name):
        raise ToolParseError(f"{path}.name", "parameter name must match ^[a-z][a-z0-9_]{1,20}$")
    type_ = raw.get("type")
    if type_ not in PARAM_TYPES:
        raise ToolParseError(
            f"{path}.type",
            f"parameter type must be one of {sorted(PARAM_TYPES)} (got {type_!r})",
        )
    required = raw.get("required", True)
    if not isinstance(required, bool):
        raise ToolParseError(f"{path}.required", "required must be a bool")
    default = raw.get("default")
    if not required and default is None:
        raise ToolParseError(
            f"{path}.default",
            "non-required parameter must declare a default value",
        )
    return ParamDef(name=name, type=type_, required=required, default=default)


def _check_step_shape(step: Any, path: str) -> None:
    """Cheap structural check. Deeper resolution (verb exists, no cycles,
    no `invoke_llm` in steps) happens in the validator."""
    if not isinstance(step, dict):
        raise ToolParseError(path, f"step must be a mapping (got {type(step).__name__})")
    has_if = "if" in step
    has_do = "do" in step
    has_then = "then" in step
    has_else = "else" in step

    if has_if:
        if not isinstance(step["if"], str):
            raise ToolParseError(f"{path}.if", "if condition must be a string expression")
        if has_then or has_else:
            # Full form
            if has_do:
                raise ToolParseError(
                    path,
                    "if-step can have either `do:` (simple form) or `then`/`else` (full form), not both",
                )
            then_branch = step.get("then") or []
            else_branch = step.get("else") or []
            for branch_name, branch in [("then", then_branch), ("else", else_branch)]:
                if not isinstance(branch, list):
                    raise ToolParseError(f"{path}.{branch_name}", "must be a list of steps")
                if len(branch) > 4:
                    raise ToolParseError(
                        f"{path}.{branch_name}",
                        f"max 4 steps in {branch_name} (got {len(branch)})",
                    )
                for i, inner in enumerate(branch):
                    if isinstance(inner, dict) and "if" in inner and ("then" in inner or "else" in inner):
                        raise ToolParseError(
                            f"{path}.{branch_name}[{i}]",
                            "no nested if/then/else inside an if branch (factor into a composite)",
                        )
                    _check_step_shape(inner, f"{path}.{branch_name}[{i}]")
        else:
            # Simple form: if + do
            if not has_do:
                raise ToolParseError(
                    path,
                    "if-step must have either `do:` (simple form) or `then:`/`else:` (full form)",
                )
            if not isinstance(step["do"], str):
                raise ToolParseError(f"{path}.do", "do must be a string verb name")
    else:
        if not has_do:
            raise ToolParseError(path, "step must declare `do:` (or `if:` for conditional)")
        if not isinstance(step["do"], str):
            raise ToolParseError(f"{path}.do", "do must be a string verb name")
        args = step.get("args")
        if args is not None and not isinstance(args, dict):
            raise ToolParseError(f"{path}.args", "args must be a mapping")
