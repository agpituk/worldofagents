"""Composite expansion + override middleware for user-defined tools.

The LLM's tool-call resolution is a layer on top of the existing
verb-dispatch path. When the model picks a composite tool, this module
walks its `steps` and produces a queue of primitive action dicts the
runtime can dispatch one per tick (using the same composite-queue
mechanism `abilities:` already uses).

Covers Phase 2 + Phase 3:
  • Composite expansion with `if`-step (simple + full forms).
  • Docstring overrides (description-only — see `tools.py`).
  • Override middleware: `when:` → `clamp:` → primitive → `after:`.
  • `{{ expr }}` and `{_expr: ...}` interpolation through the sandbox.
  • Trace events: tool.expanded, tool.gated, tool.clamped,
    tool.clamp.invalid, tool.clamp.error, tool.after.step,
    tool.after.step.failed, tool.expression.type_error,
    tool.budget_exceeded.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from arena_bot.reflex_sandbox import (
    ExpressionTypeError,
    UnsafeExpression,
    sandbox_eval,
    sandbox_eval_bool,
)
from arena_bot.tool_schema import (
    CompositeTool,
    OverrideTool,
    ParamDef,
    parse_tools,
)


# Trace event sink — the SDK and managed runtimes pass in their own
# implementation. The default is a no-op so dispatch works in unit tests
# without ceremony.
TraceSink = Callable[[str, dict[str, Any]], None]


def _noop_trace(event: str, payload: dict[str, Any]) -> None:
    return None


@dataclass
class ExpansionBudget:
    """Caps a single LLM tool call's expansion.

    GRAMMAR.md §8 budgets:
      • 16 expanded primitive operations per top-level call.
      • 50 ms wall-clock for all override evaluation in one call.
    """
    max_primitives: int = 16
    deadline_ms: int = 50
    primitives_used: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def has_capacity(self) -> bool:
        return (
            self.primitives_used < self.max_primitives
            and self._elapsed_ms() < self.deadline_ms
        )

    def charge_one(self) -> None:
        self.primitives_used += 1

    def elapsed_ms(self) -> int:
        return self._elapsed_ms()

    def _elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000)


@dataclass
class HeroToolset:
    """Pre-parsed view of the hero's tools[]. Built once per manifest
    version; the dispatcher consults it on every LLM tool call."""

    composites: dict[str, CompositeTool] = field(default_factory=dict)
    overrides: dict[str, OverrideTool] = field(default_factory=dict)

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> "HeroToolset":
        inner = manifest.get("hero") if isinstance(manifest.get("hero"), dict) else manifest
        raw = (inner or {}).get("tools") or []
        try:
            parsed = parse_tools(raw)
        except Exception:
            # The validator already produced structured issues for the user;
            # at runtime we degrade to "no tools" rather than crash.
            return cls()
        composites: dict[str, CompositeTool] = {}
        overrides: dict[str, OverrideTool] = {}
        for tool in parsed:
            if isinstance(tool, CompositeTool):
                composites[tool.name] = tool
            elif isinstance(tool, OverrideTool):
                overrides[tool.override_verb] = tool
        return cls(composites=composites, overrides=overrides)

    def is_composite(self, name: str) -> bool:
        return name in self.composites

    def is_override(self, name: str) -> bool:
        return name in self.overrides


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


@dataclass
class DispatchResult:
    """Outcome of expanding an LLM tool call.

    `actions` is a list of primitive action dicts in the order they
    should run. The runtime dispatches the first one this tick and
    queues the rest. `ok=False` indicates the dispatch failed
    (e.g., budget exceeded) and the call should produce a `wait`."""

    ok: bool
    actions: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None


def expand_tool_call(
    name: str,
    args: dict[str, Any] | None,
    *,
    toolset: HeroToolset,
    trace: TraceSink = _noop_trace,
    budget: ExpansionBudget | None = None,
    namespace: dict[str, Any] | None = None,
) -> DispatchResult:
    """Resolve one LLM-picked tool name + args into a queue of primitive
    action dicts.

    `namespace` is the expression evaluation context — hero state
    scalars + reflex helpers. Required when overrides use `when:` or
    `clamp:` or composites use `if`-step / interpolation. The runner
    builds it from perception (see `runner.py`); tests can pass an
    empty dict for primitives without override grammar.
    """
    if budget is None:
        budget = ExpansionBudget()
    ns = namespace or {}

    # Composite tool — recurse into its steps.
    if toolset.is_composite(name):
        composite = toolset.composites[name]
        trace("tool.expanded", {"tool": name, "args": args or {}})
        actions: list[dict[str, Any]] = []
        try:
            _walk_steps(
                composite.steps,
                parent_args=args or {},
                composite_param_defs=composite.parameters,
                toolset=toolset,
                trace=trace,
                budget=budget,
                out=actions,
                visiting={name},
                namespace=ns,
            )
        except _BudgetExceeded:
            trace("tool.budget_exceeded", {
                "tool": name,
                "primitives_used": budget.primitives_used,
                "elapsed_ms": budget.elapsed_ms(),
            })
            if actions:
                return DispatchResult(ok=True, actions=actions, reason="budget_partial")
            return DispatchResult(
                ok=False, actions=[{"do": "wait"}], reason="budget_exceeded"
            )
        return DispatchResult(ok=True, actions=actions or [{"do": "wait"}])

    # Primitive — apply override middleware if one exists for this verb.
    override = toolset.overrides.get(name)
    if override is not None:
        return _dispatch_override(
            name, args or {}, override,
            toolset=toolset, trace=trace, budget=budget, namespace=ns,
        )

    # Primitive without override — single action passthrough.
    action = {"do": name}
    if args:
        action.update(args)
    return DispatchResult(ok=True, actions=[action])


def _dispatch_override(
    name: str,
    args: dict[str, Any],
    override: OverrideTool,
    *,
    toolset: HeroToolset,
    trace: TraceSink,
    budget: ExpansionBudget,
    namespace: dict[str, Any],
) -> DispatchResult:
    """Apply the when → clamp → primitive → after middleware chain
    described in GRAMMAR.md §7."""

    # 1. when?
    if override.when_expr:
        try:
            ok = sandbox_eval_bool(
                override.when_expr, namespace=namespace, args=args,
            )
        except ExpressionTypeError as exc:
            trace("tool.expression.type_error", {
                "tool": name, "stage": "when", "error": str(exc),
            })
            ok = False
        except (UnsafeExpression, SyntaxError, NameError, Exception) as exc:
            trace("tool.expression.type_error", {
                "tool": name, "stage": "when", "error": repr(exc),
            })
            ok = False
        if not ok:
            trace("tool.gated", {"tool": name, "reason": "when_false"})
            # Gated: return a structured "wait" so the LLM gets feedback.
            return DispatchResult(
                ok=False,
                actions=[{"do": "wait", "_blocked_by_override": name}],
                reason="blocked_by_override",
            )

    # 2. clamp?
    clamped_args = dict(args)
    if override.clamp:
        clamped_args = _apply_clamps(
            name, override.clamp, args, namespace=namespace, trace=trace,
        )

    # 3. primitive
    primitive_action = {"do": name}
    primitive_action.update(clamped_args)
    actions: list[dict[str, Any]] = [primitive_action]
    budget.charge_one()

    # 4. after — each step processed like a composite step (no nested after,
    # no recursive call to the overridden verb — validator catches both).
    if override.after and budget.has_capacity():
        try:
            _walk_steps(
                override.after,
                parent_args=clamped_args,
                composite_param_defs=[],
                toolset=toolset,
                trace=trace,
                budget=budget,
                out=actions,
                visiting=set(),
                namespace=namespace,
                emit_after_events=True,
                after_verb=name,
            )
        except _BudgetExceeded:
            trace("tool.budget_exceeded", {
                "tool": name,
                "stage": "after",
                "primitives_used": budget.primitives_used,
                "elapsed_ms": budget.elapsed_ms(),
            })
    return DispatchResult(ok=True, actions=actions)


def _apply_clamps(
    verb: str,
    clamps: dict[str, str],
    args: dict[str, Any],
    *,
    namespace: dict[str, Any],
    trace: TraceSink,
) -> dict[str, Any]:
    """Per-param clamp evaluation. GRAMMAR.md §3 semantics:
      • Expression returns invalid → keep `requested`, emit
        tool.clamp.invalid.
      • Expression raises → keep `requested`, emit tool.clamp.error.
      • Expression returns a value different from requested → emit
        tool.clamped { from, to }.
    """
    out = dict(args)
    for param, expr in clamps.items():
        requested = args.get(param)
        try:
            value = sandbox_eval(
                expr, namespace=namespace, args=args,
                requested=requested,
                param_lookup=lambda n: args.get(n),
            )
        except (
            ExpressionTypeError, UnsafeExpression,
            SyntaxError, NameError, TypeError, ValueError, ZeroDivisionError,
        ) as exc:
            trace("tool.clamp.error", {
                "verb": verb, "param": param, "error": repr(exc),
            })
            continue

        # Coercion is light-touch in Phase 3 — defer heavy validation
        # (slug membership, tile-in-zone) to the server's existing per-verb
        # checks. Here we accept the value if it's not None.
        if value is None:
            trace("tool.clamp.invalid", {
                "verb": verb, "param": param, "reason": "none",
            })
            continue
        out[param] = value
        if value != requested:
            trace("tool.clamped", {
                "verb": verb, "param": param,
                "from": requested, "to": value,
            })
    return out


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


class _BudgetExceeded(RuntimeError):
    """Raised internally when expansion blows the budget; converted to a
    structured trace event at the top level."""


def _walk_steps(
    steps: list[dict[str, Any]],
    *,
    parent_args: dict[str, Any],
    composite_param_defs: list[ParamDef],
    toolset: HeroToolset,
    trace: TraceSink,
    budget: ExpansionBudget,
    out: list[dict[str, Any]],
    visiting: set[str],
    namespace: dict[str, Any],
    emit_after_events: bool = False,
    after_verb: str | None = None,
) -> None:
    # Apply parameter defaults — the dispatcher fills in defaults the LLM
    # didn't supply, so step interpolation always sees a complete map.
    effective_args = _apply_defaults(parent_args, composite_param_defs)

    for step in steps:
        if not budget.has_capacity():
            raise _BudgetExceeded

        # if-step (full or simple form)
        if "if" in step:
            cond_expr = step["if"]
            try:
                cond = sandbox_eval_bool(
                    cond_expr, namespace=namespace, args=effective_args,
                )
            except ExpressionTypeError as exc:
                trace("tool.expression.type_error", {
                    "stage": "if", "error": str(exc),
                })
                cond = False
            except (UnsafeExpression, SyntaxError, NameError, Exception) as exc:
                trace("tool.expression.type_error", {
                    "stage": "if", "error": repr(exc),
                })
                cond = False

            if "then" in step or "else" in step:
                branch = step.get("then") if cond else step.get("else")
                if isinstance(branch, list):
                    _walk_steps(
                        branch,
                        parent_args=effective_args,
                        composite_param_defs=[],
                        toolset=toolset,
                        trace=trace, budget=budget,
                        out=out, visiting=visiting,
                        namespace=namespace,
                        emit_after_events=emit_after_events,
                        after_verb=after_verb,
                    )
            elif cond:
                # Simple form: synthesize a single primitive step
                _walk_steps(
                    [{"do": step.get("do"), "args": step.get("args") or {}}],
                    parent_args=effective_args,
                    composite_param_defs=[],
                    toolset=toolset,
                    trace=trace, budget=budget,
                    out=out, visiting=visiting,
                    namespace=namespace,
                    emit_after_events=emit_after_events,
                    after_verb=after_verb,
                )
            continue

        verb = step.get("do")
        if not isinstance(verb, str):
            continue
        step_args = step.get("args") or {}
        if not isinstance(step_args, dict):
            step_args = {}

        if toolset.is_composite(verb):
            if verb in visiting:
                raise _BudgetExceeded
            child = toolset.composites[verb]
            child_args = _resolve_args(step_args, effective_args, namespace)
            trace("tool.expanded", {"tool": verb, "args": child_args})
            _walk_steps(
                child.steps,
                parent_args=child_args,
                composite_param_defs=child.parameters,
                toolset=toolset,
                trace=trace, budget=budget,
                out=out, visiting=visiting | {verb},
                namespace=namespace,
            )
            continue

        # Primitive step — emit a concrete action dict.
        primitive_args = _resolve_args(step_args, effective_args, namespace)
        action = {"do": verb}
        action.update(primitive_args)
        out.append(action)
        budget.charge_one()
        if emit_after_events:
            trace("tool.after.step", {
                "verb": after_verb, "step": {"do": verb, "args": primitive_args},
            })


def _apply_defaults(
    args: dict[str, Any], param_defs: list[ParamDef]
) -> dict[str, Any]:
    out = dict(args)
    for p in param_defs:
        if p.name not in out and not p.required and p.default is not None:
            out[p.name] = p.default
    return out


_INTERP_RE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)


def _resolve_args(
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
    out: dict[str, Any] = {}
    for k, v in step_args.items():
        out[k] = _resolve_value(v, parent_args, namespace)
    return out


def _resolve_value(
    v: Any, parent_args: dict[str, Any], namespace: dict[str, Any],
) -> Any:
    if isinstance(v, dict) and set(v.keys()) == {"_expr"}:
        try:
            return sandbox_eval(
                v["_expr"], namespace=namespace, args=parent_args,
            )
        except Exception:
            return None
    if isinstance(v, str) and "{{" in v:
        return _interpolate_string(v, parent_args, namespace)
    if isinstance(v, list):
        return [_resolve_value(x, parent_args, namespace) for x in v]
    if isinstance(v, dict):
        return {k: _resolve_value(x, parent_args, namespace) for k, x in v.items()}
    return v


def _interpolate_string(
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
