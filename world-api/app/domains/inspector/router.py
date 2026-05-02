"""Inspector API — surfaces per-hero tool stats and per-tick LLM
reasoning to the spectator UI.

Phase 5 of the agent-tools rollout. The data lives in the existing
Event table — `action.resolved` rows carry a `debug.tool_events` list
populated by the managed runner (see `world-api/app/managed/runner.py`).
This router computes aggregations on demand; a daily rollup table is
follow-up work flagged in IMPL_PLAN §5.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Event, Hero

router = APIRouter(prefix="/api/heroes", tags=["inspector"])


# ---------------------------------------------------------------------------
# Helpers — extract tool-call data from Event rows
# ---------------------------------------------------------------------------


def _hero_id_or_404(db: Session, hero_id: str) -> uuid.UUID:
    try:
        hid = uuid.UUID(hero_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid hero_id")
    if db.get(Hero, hid) is None:
        raise HTTPException(status_code=404, detail="hero not found")
    return hid


def _hero_manifest(db: Session, hid: uuid.UUID) -> dict[str, Any]:
    h = db.get(Hero, hid)
    return (h.manifest if h else None) or {}


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
# GET /api/heroes/{hero_id}/tools/summary
# ---------------------------------------------------------------------------


@router.get("/{hero_id}/tools/summary")
def tools_summary(
    db: Annotated[Session, Depends(get_db)],
    hero_id: str,
) -> dict[str, Any]:
    hid = _hero_id_or_404(db, hero_id)
    manifest = _hero_manifest(db, hid)
    tools_def = _hero_tools_def(manifest)

    rows = list(db.scalars(
        select(Event).where(
            Event.hero_id == hid, Event.kind == "action.resolved",
        ).order_by(Event.tick_id.desc()).limit(1000)
    ))
    raw_events = _walk_tool_events(rows)

    # Aggregate per-tool counters.
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


# ---------------------------------------------------------------------------
# GET /api/heroes/{hero_id}/tools/{tool_name}
# ---------------------------------------------------------------------------


@router.get("/{hero_id}/tools/{tool_name}")
def tool_detail(
    db: Annotated[Session, Depends(get_db)],
    hero_id: str,
    tool_name: str,
) -> dict[str, Any]:
    hid = _hero_id_or_404(db, hero_id)
    manifest = _hero_manifest(db, hid)
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
        raise HTTPException(status_code=404, detail="tool not found on this hero")

    rows = list(db.scalars(
        select(Event).where(
            Event.hero_id == hid, Event.kind == "action.resolved",
        ).order_by(Event.tick_id.desc()).limit(500)
    ))

    recent_calls: list[dict[str, Any]] = []
    stats = {"calls": 0, "success": 0, "blocked_by_override": 0,
             "clamps_applied": 0, "budget_exceeded": 0}

    for ev in rows:
        debug = (ev.payload or {}).get("debug") or {}
        events = debug.get("tool_events") or []
        # Group events by their "containing" tool — the first
        # tool.expanded or tool.gated event in the list names the
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
# GET /api/heroes/{hero_id}/ticks/{tick}/llm-call
# ---------------------------------------------------------------------------


@router.get("/{hero_id}/ticks/{tick}/llm-call")
def tick_llm_call(
    db: Annotated[Session, Depends(get_db)],
    hero_id: str,
    tick: int,
) -> dict[str, Any]:
    hid = _hero_id_or_404(db, hero_id)
    rows = list(db.scalars(
        select(Event).where(
            Event.hero_id == hid,
            Event.kind == "action.resolved",
            Event.tick_id == tick,
        )
    ))
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="no action.resolved event for this hero/tick",
        )
    ev = rows[0]
    debug = (ev.payload or {}).get("debug") or {}
    events = debug.get("tool_events") or []
    llm_offered = next(
        (e for e in events if e.get("event") == "llm.tools_offered"), None,
    )
    if not llm_offered:
        return {
            "chosen_tool": None,
            "chosen_args": None,
            "tools_offered": [],
            "reasoning_trace": "",
            "tool_mentions": [],
        }
    payload = llm_offered.get("payload") or {}
    reasoning = payload.get("reasoning_trace") or ""
    tool_names = [t.get("name") for t in payload.get("tools_offered") or []]
    mentions = sorted({n for n in tool_names if n and n in reasoning})
    return {
        "chosen_tool": payload.get("chosen_tool"),
        "chosen_args": payload.get("chosen_args"),
        "tools_offered": payload.get("tools_offered") or [],
        "reasoning_trace": reasoning,
        "tool_mentions": mentions,
    }
