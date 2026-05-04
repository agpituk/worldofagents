"""Inspector business logic — aggregates `action.resolved.debug.tool_events`
into the shapes the spectator UI consumes.

Two distinct concerns live here:
  1. Tool usage (composite/override) aggregation — `tools_summary`,
     `tool_detail`. Reads many ticks, counts per-tool outcomes.
  2. Per-tick LLM call inspection — `tick_llm_call`, `latest_llm_call`.
     Reads one tick, exposes prompt/tokens/latency to the owner only.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import Event
from app.domains.hero.service import HeroService
from app.domains.inspector import repository


# ---------------------------------------------------------------------------
# Tool definitions — extracted from the hero's manifest
# ---------------------------------------------------------------------------


def _hero_tools_def(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    inner = manifest.get("hero") if isinstance(manifest.get("hero"), dict) else manifest
    return list((inner or {}).get("tools") or [])


def _walk_tool_events(events: list[Event]) -> list[dict[str, Any]]:
    """Flatten the per-tick `tool_events` arrays embedded under each
    action.resolved Event's `debug.tool_events`. Returns one record per
    raw tool.* event, annotated with the originating tick."""
    out: list[dict[str, Any]] = []
    for ev in events:
        debug = (ev.payload or {}).get("debug") or {}
        for entry in debug.get("tool_events") or []:
            out.append({
                "tick": ev.tick_id,
                "event": entry.get("event"),
                "payload": entry.get("payload") or {},
            })
    return out


# ---------------------------------------------------------------------------
# Tool usage aggregation
# ---------------------------------------------------------------------------


def tools_summary(db: Session, hero_id: str, hid: uuid.UUID) -> dict[str, Any]:
    manifest = repository.hero_manifest(db, hid)
    tools_def = _hero_tools_def(manifest)

    rows = repository.recent_resolved(db, hid, limit=1000)
    raw_events = _walk_tool_events(rows)

    counters: dict[str, dict[str, int]] = defaultdict(lambda: {
        "calls": 0, "success": 0, "blocked_by_override": 0,
        "clamps_applied": 0, "budget_exceeded": 0,
        "after_chain_failures": 0, "expression_type_errors": 0,
    })
    last_tick: dict[str, int] = {}

    for entry in raw_events:
        ev = entry["event"]
        payload = entry["payload"]
        if ev == "tool.expanded":
            tool = payload.get("tool")
            if tool:
                counters[tool]["calls"] += 1
                counters[tool]["success"] += 1
                last_tick[tool] = max(last_tick.get(tool, 0), entry["tick"])
        elif ev == "tool.gated":
            tool = payload.get("tool")
            if tool:
                counters[tool]["calls"] += 1
                counters[tool]["blocked_by_override"] += 1
                last_tick[tool] = max(last_tick.get(tool, 0), entry["tick"])
        elif ev == "tool.clamped":
            verb = payload.get("verb")
            if verb:
                counters[verb]["clamps_applied"] += 1
        elif ev == "tool.budget_exceeded":
            tool = payload.get("tool")
            if tool:
                counters[tool]["budget_exceeded"] += 1
                if counters[tool]["success"] > 0:
                    counters[tool]["success"] -= 1
        elif ev == "tool.after.step.failed":
            verb = payload.get("verb")
            if verb:
                counters[verb]["after_chain_failures"] += 1
        elif ev == "tool.expression.type_error":
            tool = payload.get("tool") or payload.get("stage")
            if tool:
                counters[tool]["expression_type_errors"] += 1

    out_tools: list[dict[str, Any]] = []
    for entry in tools_def:
        if not isinstance(entry, dict):
            continue
        is_override = "override" in entry
        kind = "override" if is_override else "composite"
        name = entry.get("override") if is_override else entry.get("name")
        if not name:
            continue
        c = counters.get(name, {})
        out_tools.append({
            "name": name,
            "kind": kind,
            "calls": c.get("calls", 0),
            "success": c.get("success", 0),
            "blocked_by_override": c.get("blocked_by_override", 0),
            "clamps_applied": c.get("clamps_applied", 0),
            "budget_exceeded": c.get("budget_exceeded", 0),
            "after_chain_failures": c.get("after_chain_failures", 0),
            "expression_type_errors": c.get("expression_type_errors", 0),
            "last_called_tick": last_tick.get(name),
            "description": (entry.get("description") or "").strip()[:240],
        })

    return {"hero_id": hero_id, "tools": out_tools}


def tool_detail(db: Session, hid: uuid.UUID, tool_name: str) -> dict[str, Any] | None:
    """Return per-call detail for one tool, or None if the tool isn't
    declared on this hero (the route raises 404 in that case)."""
    manifest = repository.hero_manifest(db, hid)
    tools_def = _hero_tools_def(manifest)

    definition = None
    for entry in tools_def:
        if not isinstance(entry, dict):
            continue
        candidate = entry.get("override") if "override" in entry else entry.get("name")
        if candidate == tool_name:
            definition = entry
            break
    if definition is None:
        return None

    rows = repository.recent_resolved(db, hid, limit=500)

    recent_calls: list[dict[str, Any]] = []
    stats = {"calls": 0, "success": 0, "blocked_by_override": 0,
             "clamps_applied": 0, "budget_exceeded": 0}

    for ev in rows:
        debug = (ev.payload or {}).get("debug") or {}
        events = debug.get("tool_events") or []
        # The first tool.expanded or tool.gated entry names the
        # top-level tool the LLM picked.
        top_tool: str | None = None
        for entry in events:
            if entry.get("event") in ("tool.expanded", "tool.gated"):
                top_tool = entry.get("payload", {}).get("tool")
                break
        if top_tool != tool_name:
            continue

        gated = any(e.get("event") == "tool.gated" for e in events)
        budget_exceeded = any(e.get("event") == "tool.budget_exceeded" for e in events)
        clamps = sum(1 for e in events if e.get("event") == "tool.clamped")

        stats["calls"] += 1
        if gated:
            stats["blocked_by_override"] += 1
        elif budget_exceeded:
            stats["budget_exceeded"] += 1
        else:
            stats["success"] += 1
        stats["clamps_applied"] += clamps

        if len(recent_calls) < 50:
            top_args: dict[str, Any] = {}
            for entry in events:
                if entry.get("event") == "tool.expanded":
                    top_args = entry.get("payload", {}).get("args", {})
                    break
            result = "blocked" if gated else (
                "budget_exceeded" if budget_exceeded else "ok"
            )
            recent_calls.append({
                "tick": ev.tick_id,
                "args": top_args,
                "result": result,
                "trace": events,
            })

    return {
        "definition": definition,
        "recent_calls": recent_calls,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# Per-tick LLM call inspection (owner-gated)
# ---------------------------------------------------------------------------


def _empty_llm_call(is_owner: bool) -> dict[str, Any]:
    return {
        "chosen_tool": None,
        "chosen_args": None,
        "tools_offered": [],
        "reasoning_trace": "",
        "tool_mentions": [],
        "prompt_visible": is_owner,
        "prompt_text": None,
        "tokens_in": None,
        "tokens_out": None,
        "tokens_budget": None,
        "latency_ms": None,
        "error": None,
    }


def _shape_llm_call(payload: dict[str, Any], is_owner: bool) -> dict[str, Any]:
    reasoning = payload.get("reasoning_trace") or ""
    tool_names = [t.get("name") for t in payload.get("tools_offered") or []]
    mentions = sorted({n for n in tool_names if n and n in reasoning})
    # The chosen_tool/args and tool list show what happened — that's the
    # spectator-visible "action" surface and stays public. The LLM's
    # *reasoning trace* is inner monologue that reveals strategy and
    # any hero-private context the model wove into its plan; restrict
    # to the owner along with prompt_text and operational metadata.
    out: dict[str, Any] = {
        "chosen_tool": payload.get("chosen_tool"),
        "chosen_args": payload.get("chosen_args"),
        "tools_offered": payload.get("tools_offered") or [],
        "tool_mentions": mentions,
        "prompt_visible": is_owner,
        # Gateway/provider error (if any). Public so the spectator UI
        # can show "the gateway is down" alongside the tool list — much
        # less mysterious than an empty `tools_offered` with no reason.
        "error": payload.get("error"),
    }
    if is_owner:
        out["reasoning_trace"] = reasoning
        out["prompt_text"] = payload.get("prompt_text")
        out["tokens_in"] = payload.get("tokens_in")
        out["tokens_out"] = payload.get("tokens_out")
        out["tokens_budget"] = payload.get("tokens_budget")
        out["latency_ms"] = payload.get("latency_ms")
    else:
        out["reasoning_trace"] = ""
        out["prompt_text"] = None
        out["tokens_in"] = None
        out["tokens_out"] = None
        out["tokens_budget"] = None
        out["latency_ms"] = None
    return out


def _find_llm_offered(rows: list[Event]) -> dict[str, Any] | None:
    """Multiple action.resolved rows can land at the same tick; prefer
    the one carrying an llm.tools_offered entry so the inspector
    surfaces real prompt data instead of the empty placeholder."""
    for candidate in rows:
        debug = (candidate.payload or {}).get("debug") or {}
        events = debug.get("tool_events") or []
        match = next(
            (e for e in events if e.get("event") == "llm.tools_offered"), None,
        )
        if match is not None:
            return match
    return None


def tick_llm_call(
    db: Session,
    hid: uuid.UUID,
    tick: int,
    *,
    owner_token: str | None,
) -> dict[str, Any]:
    """Returns the shaped LLM call record for a given tick. Raises
    LookupError if the tick has no action.resolved row at all (the
    route surfaces this as 404)."""
    is_owner = HeroService.verify_owner(db, hid, owner_token)
    rows = repository.resolved_at_tick(db, hid, tick)
    if not rows:
        raise LookupError("no action.resolved event for this hero/tick")
    llm_offered = _find_llm_offered(rows)
    if llm_offered is None:
        return _empty_llm_call(is_owner)
    return _shape_llm_call(llm_offered.get("payload") or {}, is_owner)


def latest_llm_call(
    db: Session,
    hid: uuid.UUID,
    *,
    owner_token: str | None,
) -> dict[str, Any]:
    """Most recent tick that actually carried an llm.tools_offered
    event. Returns a placeholder with `tick_id: None` when the hero
    has no LLM tick on record yet (e.g., reflex-only heroes, or
    just-registered)."""
    is_owner = HeroService.verify_owner(db, hid, owner_token)
    rows = repository.recent_resolved(db, hid, limit=50)
    for ev in rows:
        debug = (ev.payload or {}).get("debug") or {}
        events = debug.get("tool_events") or []
        match = next(
            (e for e in events if e.get("event") == "llm.tools_offered"), None,
        )
        if match is not None:
            shaped = _shape_llm_call(match.get("payload") or {}, is_owner)
            shaped["tick_id"] = int(ev.tick_id)
            return shaped
    return {"tick_id": None, "prompt_visible": is_owner}
