"""Validator for the manifest's `tools:` section.

Covers (Phase 2 + Phase 3):
  • Shape parsing via `arena_bot.tool_schema.parse_tools`.
  • Name uniqueness across `tools[]`.
  • Composite step `do:` resolves to a primitive verb or a sibling
    composite (no cycles, no `invoke_llm`).
  • Cycle detection in the composite-call DAG.
  • Expansion-depth budget (≤ 16 primitives).
  • Override grammar: `when`, `clamp`, `after`, `if`-step.
  • Expression syntax via `compile_safe` (existing reflex sandbox).
  • Per-verb clampable params via `clamp_table.CLAMP_TABLE`.
"""

from __future__ import annotations

from typing import Any

from app.domains.manifest_validate.clamp_table import CLAMP_TABLE, is_clampable
from app.domains.manifest_validate.shared import META_VERBS, SDK_CONVENIENCE_VERBS

# Importing the SDK module so server + SDK use the same parser. The
# bot-sdk-python package is on PYTHONPATH inside this monorepo.
from arena_bot.reflex_sandbox import UnsafeExpression, compile_safe  # type: ignore
from arena_bot.tool_schema import (  # type: ignore
    CompositeTool,
    OverrideTool,
    ToolDef,
    ToolParseError,
    _parse_one,
)


# Issue mirrors the one declared in `manifest_validate.router`. We keep
# this validator return-type as plain dicts so the router can shape them
# into its Pydantic model without circular imports.
def _issue(severity: str, message: str, path: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"severity": severity, "message": message}
    if path is not None:
        out["path"] = path
    return out


def _check_expr(expr: str, path: str) -> list[dict[str, Any]]:
    """Best-effort syntax check via the reflex sandbox. Catches AST
    violations and parse errors at deploy time; runtime evaluation
    handles dynamic type errors via `tool.expression.type_error`."""
    if not isinstance(expr, str) or not expr.strip():
        return [_issue("error", "expression must be a non-empty string", path=path)]
    try:
        compile_safe(expr)
    except UnsafeExpression as exc:
        return [_issue("error", f"unsafe expression: {exc}", path=path)]
    except SyntaxError as exc:
        return [_issue("error", f"expression syntax error: {exc.msg}", path=path)]
    return []


def validate_tools(
    raw_tools: Any,
    *,
    valid_verbs: set[str],
    max_primitives: int = 16,
) -> tuple[list[dict[str, Any]], list[ToolDef]]:
    """Returns `(issues, parsed_tools)`. `parsed_tools` is best-effort —
    entries that failed to parse are omitted, but well-formed siblings
    still get returned so downstream consumers can keep working.
    """
    issues: list[dict[str, Any]] = []

    if raw_tools is None:
        return issues, []

    if not isinstance(raw_tools, list):
        issues.append(_issue(
            "error",
            f"tools must be a list (got {type(raw_tools).__name__})",
            path="tools",
        ))
        return issues, []

    parsed: list[ToolDef] = []
    for i, entry in enumerate(raw_tools):
        if not isinstance(entry, dict):
            issues.append(_issue(
                "error",
                f"tools[{i}] must be a mapping",
                path=f"tools[{i}]",
            ))
            continue
        try:
            parsed.append(_parse_one(entry, f"tools[{i}]"))
        except ToolParseError as exc:
            issues.append(_issue("error", exc.message, path=exc.path))

    # Name uniqueness across all parsed entries
    seen_names: set[str] = set()
    for tool in parsed:
        if tool.name in seen_names:
            issues.append(_issue(
                "error",
                f"duplicate tool name '{tool.name}'",
                path=f"tools.{tool.name}",
            ))
        seen_names.add(tool.name)

    composite_names = {t.name for t in parsed if isinstance(t, CompositeTool)}

    # Per-tool deeper checks
    for i, tool in enumerate(parsed):
        path = f"tools[{i}]"
        if isinstance(tool, OverrideTool):
            issues.extend(_validate_override(tool, path, valid_verbs, composite_names))
        else:
            issues.extend(_validate_composite(tool, path, valid_verbs, composite_names))

    # Cycle detection across composites
    composites_by_name = {
        t.name: t for t in parsed if isinstance(t, CompositeTool)
    }
    cycle_issues = _detect_cycles(composites_by_name)
    issues.extend(cycle_issues)

    # Expansion-depth budget — only meaningful if no cycles
    if not cycle_issues:
        for c in composites_by_name.values():
            depth = _max_expansion_depth(c, composites_by_name, set())
            if depth > max_primitives:
                issues.append(_issue(
                    "error",
                    f"composite '{c.name}' expands to {depth} primitives in worst "
                    f"case; max is {max_primitives}",
                    path=f"tools.{c.name}.steps",
                ))

    return issues, parsed


# ---------------------------------------------------------------------------
# Per-tool validation
# ---------------------------------------------------------------------------


def _validate_override(
    tool: OverrideTool,
    path: str,
    valid_verbs: set[str],
    composite_names: set[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    if tool.override_verb in META_VERBS:
        out.append(_issue(
            "error",
            f"cannot override meta-verb '{tool.override_verb}'",
            path=f"{path}.override",
        ))
        return out
    if tool.override_verb not in valid_verbs:
        out.append(_issue(
            "error",
            f"unknown verb '{tool.override_verb}'",
            path=f"{path}.override",
        ))
        return out

    # `when:` — must be a syntactically valid sandbox expression.
    if tool.when_expr is not None:
        out.extend(_check_expr(tool.when_expr, f"{path}.when"))

    # `clamp:` — every key must be a clampable param of this verb;
    # every value must be a valid expression.
    for param_name, expr in tool.clamp.items():
        if not is_clampable(tool.override_verb, param_name):
            allowed = sorted(CLAMP_TABLE.get(tool.override_verb, {}).keys())
            out.append(_issue(
                "error",
                f"'{param_name}' is not a clampable parameter of '{tool.override_verb}' "
                f"(allowed: {allowed})",
                path=f"{path}.clamp.{param_name}",
            ))
            continue
        out.extend(_check_expr(expr, f"{path}.clamp.{param_name}"))

    # `after:` — list of step dicts; each step must resolve like a composite step,
    # but cannot reference the verb being overridden (would loop).
    for i, step in enumerate(tool.after):
        out.extend(_validate_step(
            step,
            f"{path}.after[{i}]",
            valid_verbs=valid_verbs,
            composite_names=composite_names,
            self_name=tool.override_verb,
            allow_after_chain=False,
        ))

    return out


def _validate_composite(
    tool: CompositeTool,
    path: str,
    valid_verbs: set[str],
    composite_names: set[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    if tool.name in valid_verbs:
        out.append(_issue(
            "error",
            f"composite name '{tool.name}' shadows primitive verb — composites "
            f"with primitive names must declare `override:` (Shape A)",
            path=f"{path}.name",
        ))

    for i, step in enumerate(tool.steps):
        out.extend(_validate_step(
            step, f"{path}.steps[{i}]",
            valid_verbs=valid_verbs,
            composite_names=composite_names,
            self_name=tool.name,
            allow_after_chain=True,
        ))

    return out


def _validate_step(
    step: dict[str, Any],
    path: str,
    *,
    valid_verbs: set[str],
    composite_names: set[str],
    self_name: str,
    allow_after_chain: bool,
) -> list[dict[str, Any]]:
    """Validate one step entry. `allow_after_chain` tells us whether we're
    inside a composite's `steps:` (where if-steps are allowed) vs an
    override's `after:` (no nested `if-then-else` per GRAMMAR.md §4)."""
    out: list[dict[str, Any]] = []

    if "if" in step:
        # Validate the condition expression
        out.extend(_check_expr(step["if"], f"{path}.if"))

        if "then" in step or "else" in step:
            # Full form
            for branch_name in ("then", "else"):
                branch = step.get(branch_name) or []
                if not isinstance(branch, list):
                    continue
                for j, inner in enumerate(branch):
                    if not isinstance(inner, dict):
                        continue
                    out.extend(_validate_step(
                        inner, f"{path}.{branch_name}[{j}]",
                        valid_verbs=valid_verbs,
                        composite_names=composite_names,
                        self_name=self_name,
                        allow_after_chain=allow_after_chain,
                    ))
        else:
            # Simple form: if + do
            verb = step.get("do")
            if isinstance(verb, str):
                out.extend(_check_step_verb(
                    verb, f"{path}.do",
                    valid_verbs=valid_verbs,
                    composite_names=composite_names,
                    self_name=self_name,
                ))
        return out

    verb = step.get("do")
    if isinstance(verb, str):
        out.extend(_check_step_verb(
            verb, f"{path}.do",
            valid_verbs=valid_verbs,
            composite_names=composite_names,
            self_name=self_name,
        ))
    return out


def _check_step_verb(
    verb: str,
    path: str,
    *,
    valid_verbs: set[str],
    composite_names: set[str],
    self_name: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if verb in META_VERBS:
        out.append(_issue(
            "error",
            f"step cannot use meta-verb '{verb}' — composites chain primitives only",
            path=path,
        ))
    elif verb == self_name:
        out.append(_issue(
            "error",
            f"step references itself ('{self_name}') — would loop",
            path=path,
        ))
    elif (
        verb not in valid_verbs
        and verb not in composite_names
        and verb not in SDK_CONVENIENCE_VERBS
    ):
        out.append(_issue(
            "error",
            f"unknown verb '{verb}' (not a primitive nor a composite in this manifest)",
            path=path,
        ))
    return out


# ---------------------------------------------------------------------------
# Cycle detection (Tarjan's SCC; any non-trivial SCC is a cycle)
# ---------------------------------------------------------------------------


def _walk_step_composite_refs(step: dict[str, Any], composites: dict[str, CompositeTool]) -> set[str]:
    """Collect composite-tool references in a step (handles if-step
    full + simple forms)."""
    refs: set[str] = set()
    if "if" in step and ("then" in step or "else" in step):
        for branch in (step.get("then") or [], step.get("else") or []):
            for inner in branch:
                if isinstance(inner, dict):
                    refs |= _walk_step_composite_refs(inner, composites)
        return refs
    do = step.get("do")
    if isinstance(do, str) and do in composites:
        refs.add(do)
    return refs


def _detect_cycles(
    composites: dict[str, CompositeTool],
) -> list[dict[str, Any]]:
    graph: dict[str, set[str]] = {}
    for name, tool in composites.items():
        refs: set[str] = set()
        for step in tool.steps:
            if isinstance(step, dict):
                refs |= _walk_step_composite_refs(step, composites)
        graph[name] = refs

    out: list[dict[str, Any]] = []
    visited: set[str] = set()
    on_stack: set[str] = set()
    stack: list[str] = []

    def _visit(node: str) -> None:
        if node in on_stack:
            # Cycle — record once per cycle
            i = stack.index(node)
            cycle = stack[i:] + [node]
            out.append({
                "severity": "error",
                "message": f"composite cycle: {' → '.join(cycle)}",
                "path": f"tools.{node}.steps",
            })
            return
        if node in visited:
            return
        visited.add(node)
        on_stack.add(node)
        stack.append(node)
        for child in graph.get(node, ()):
            _visit(child)
        stack.pop()
        on_stack.discard(node)

    for n in graph:
        _visit(n)
    return out


# ---------------------------------------------------------------------------
# Worst-case expansion depth (assumes acyclic graph)
# ---------------------------------------------------------------------------


def _max_expansion_depth(
    tool: CompositeTool,
    composites: dict[str, CompositeTool],
    visiting: set[str],
) -> int:
    if tool.name in visiting:
        # Defensive — cycle should have been caught upstream.
        return 0
    visiting = visiting | {tool.name}
    return _step_list_depth(tool.steps, composites, visiting)


def _step_list_depth(
    steps: list[dict[str, Any]],
    composites: dict[str, CompositeTool],
    visiting: set[str],
) -> int:
    total = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        total += _step_depth(step, composites, visiting)
    return total


def _step_depth(
    step: dict[str, Any],
    composites: dict[str, CompositeTool],
    visiting: set[str],
) -> int:
    if "if" in step and ("then" in step or "else" in step):
        # Worst-case branch.
        then_d = _step_list_depth(step.get("then") or [], composites, visiting)
        else_d = _step_list_depth(step.get("else") or [], composites, visiting)
        return max(then_d, else_d)
    if "if" in step:
        # Simple if + do — worst case is "do fires".
        verb = step.get("do")
        if isinstance(verb, str) and verb in composites:
            return _max_expansion_depth(composites[verb], composites, visiting)
        return 1
    verb = step.get("do")
    if isinstance(verb, str) and verb in composites:
        return _max_expansion_depth(composites[verb], composites, visiting)
    return 1
