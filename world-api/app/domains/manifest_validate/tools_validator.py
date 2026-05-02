"""Validator for the manifest's `tools:` section.

Phase 2 (this module's first cut) covers:
  • Shape parsing via `arena_bot.tool_schema.parse_tools`.
  • Name uniqueness across `tools[]`.
  • Composite step `do:` resolves to a primitive verb or a sibling
    composite (no cycles, no `invoke_llm`).
  • Cycle detection in the composite-call DAG.
  • Expansion-depth budget (≤ 16 primitives).

Phase 3 will add:
  • Expression validation through `compile_safe` for `when` / `clamp`
    expressions.
  • Per-verb clampable-parameter table.
  • `if`-step expression checks.

Until then, any tool entry that sets `when`, `clamp`, `after`, or uses
`if`-step inside a composite is rejected with a Phase-3-pending error.
"""

from __future__ import annotations

from typing import Any

from app.domains.manifest_validate.shared import META_VERBS

# Importing the SDK module so server + SDK use the same parser. The
# bot-sdk-python package is on PYTHONPATH inside this monorepo.
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


# Phase-2 cap. Phase 3 lifts this when the override-grammar lands.
PHASE_2_FORBIDDEN_FIELDS = ("when", "clamp", "after")


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
            issues.extend(_validate_override(tool, path, valid_verbs))
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
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    if tool.override_verb in META_VERBS:
        out.append(_issue(
            "error",
            f"cannot override meta-verb '{tool.override_verb}'",
            path=f"{path}.override",
        ))
    elif tool.override_verb not in valid_verbs:
        out.append(_issue(
            "error",
            f"unknown verb '{tool.override_verb}'",
            path=f"{path}.override",
        ))

    # Phase 2 — reject grammar that's not landed yet
    if tool.when_expr is not None:
        out.append(_issue(
            "error",
            "`when:` is part of the Phase 3 override grammar — not yet live",
            path=f"{path}.when",
        ))
    if tool.clamp:
        out.append(_issue(
            "error",
            "`clamp:` is part of the Phase 3 override grammar — not yet live",
            path=f"{path}.clamp",
        ))
    if tool.after:
        out.append(_issue(
            "error",
            "`after:` is part of the Phase 3 override grammar — not yet live",
            path=f"{path}.after",
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
        ))

    return out


def _validate_step(
    step: dict[str, Any],
    path: str,
    *,
    valid_verbs: set[str],
    composite_names: set[str],
    self_name: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    if "if" in step:
        # Phase 2 — `if`-step is part of the override grammar surface and
        # not yet supported in composites. Phase 3 lifts.
        out.append(_issue(
            "error",
            "`if`-step in composites is part of the Phase 3 grammar — not yet live",
            path=f"{path}.if",
        ))
        return out

    verb = step.get("do")
    if verb in META_VERBS:
        out.append(_issue(
            "error",
            f"composite step cannot use meta-verb '{verb}' — composites chain "
            f"primitives only",
            path=f"{path}.do",
        ))
    elif verb == self_name:
        out.append(_issue(
            "error",
            f"composite step references itself ('{self_name}') — would loop",
            path=f"{path}.do",
        ))
    elif verb not in valid_verbs and verb not in composite_names:
        out.append(_issue(
            "error",
            f"unknown verb '{verb}' (not a primitive nor a composite in this manifest)",
            path=f"{path}.do",
        ))
    return out


# ---------------------------------------------------------------------------
# Cycle detection (Tarjan's SCC; any non-trivial SCC is a cycle)
# ---------------------------------------------------------------------------


def _detect_cycles(
    composites: dict[str, CompositeTool],
) -> list[dict[str, Any]]:
    graph: dict[str, set[str]] = {}
    for name, tool in composites.items():
        refs: set[str] = set()
        for step in tool.steps:
            if isinstance(step, dict) and isinstance(step.get("do"), str):
                d = step["do"]
                if d in composites:
                    refs.add(d)
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
    total = 0
    for step in tool.steps:
        if isinstance(step, dict):
            verb = step.get("do")
            if isinstance(verb, str) and verb in composites:
                total += _max_expansion_depth(
                    composites[verb], composites, visiting
                )
            else:
                total += 1
    return total
