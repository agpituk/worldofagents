"""Composite expansion + override middleware for user-defined tools.

The LLM's tool-call resolution is a layer on top of the existing
verb-dispatch path. When the model picks a composite tool, this module
walks its `steps` and produces a queue of primitive action dicts the
runtime can dispatch one per tick (using the same composite-queue
mechanism `abilities:` already uses).

Phase 2 (this cut):
  • Composite expansion (no `if`-step).
  • Docstring override is a no-op at dispatch time — the override only
    changes the description shown to the LLM (handled in `tools.py`).
  • Trace events: `tool.expanded`, `tool.budget_exceeded`.

Phase 3 will add:
  • `when:` gate, `clamp:` argument shaping, `after:` post-chain,
    `if`-step inside composites.
  • Trace events: `tool.gated`, `tool.clamped`, `tool.clamp.invalid`,
    `tool.clamp.error`, `tool.after.step`, `tool.after.step.failed`,
    `tool.expression.type_error`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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
) -> DispatchResult:
    """Resolve one LLM-picked tool name + args into a queue of primitive
    action dicts. If the name is a primitive (or a primitive under
    docstring override), this is a single-action passthrough.

    Phase 2 only.
    """
    if budget is None:
        budget = ExpansionBudget()

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
            )
        except _BudgetExceeded:
            trace("tool.budget_exceeded", {
                "tool": name,
                "primitives_used": budget.primitives_used,
                "elapsed_ms": budget.elapsed_ms(),
            })
            # Best-effort: return what we have if non-empty, otherwise wait.
            if actions:
                return DispatchResult(ok=True, actions=actions, reason="budget_partial")
            return DispatchResult(
                ok=False, actions=[{"do": "wait"}], reason="budget_exceeded"
            )
        return DispatchResult(ok=True, actions=actions or [{"do": "wait"}])

    # Primitive (with or without docstring override) — single action passthrough.
    action = {"do": name}
    if args:
        action.update(args)
    return DispatchResult(ok=True, actions=[action])


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
) -> None:
    # Apply parameter defaults — the dispatcher fills in defaults the LLM
    # didn't supply, so step interpolation always sees a complete map.
    effective_args = _apply_defaults(parent_args, composite_param_defs)

    for step in steps:
        if not budget.has_capacity():
            raise _BudgetExceeded
        verb = step.get("do")
        if not isinstance(verb, str):
            # Validator caught this at deploy time; runtime is forgiving.
            continue
        step_args = step.get("args") or {}
        if not isinstance(step_args, dict):
            step_args = {}

        if toolset.is_composite(verb):
            if verb in visiting:
                # Defensive — validator catches cycles at deploy, but if the
                # manifest got past validation somehow, blow the budget rather
                # than infinite-loop.
                raise _BudgetExceeded
            child = toolset.composites[verb]
            child_args = _resolve_args_phase2(step_args, effective_args)
            trace("tool.expanded", {"tool": verb, "args": child_args})
            _walk_steps(
                child.steps,
                parent_args=child_args,
                composite_param_defs=child.parameters,
                toolset=toolset,
                trace=trace,
                budget=budget,
                out=out,
                visiting=visiting | {verb},
            )
            continue

        # Primitive step — emit a concrete action dict.
        primitive_args = _resolve_args_phase2(step_args, effective_args)
        action = {"do": verb}
        action.update(primitive_args)
        out.append(action)
        budget.charge_one()


def _apply_defaults(
    args: dict[str, Any], param_defs: list[ParamDef]
) -> dict[str, Any]:
    out = dict(args)
    for p in param_defs:
        if p.name not in out and not p.required and p.default is not None:
            out[p.name] = p.default
    return out


def _resolve_args_phase2(
    step_args: dict[str, Any], parent_args: dict[str, Any]
) -> dict[str, Any]:
    """Phase 2 arg resolution — only the simplest interpolation form
    `"{{ args.X }}"` (whole-string replace, no expressions). The full
    expression-DSL interpolation lands in Phase 3 with the sandbox helpers.
    """
    out: dict[str, Any] = {}
    for k, v in step_args.items():
        if isinstance(v, str):
            stripped = v.strip()
            if (
                stripped.startswith("{{")
                and stripped.endswith("}}")
                and stripped[2:-2].strip().startswith("args.")
            ):
                ref = stripped[2:-2].strip()[len("args."):]
                if ref in parent_args:
                    out[k] = parent_args[ref]
                    continue
        out[k] = v
    return out
