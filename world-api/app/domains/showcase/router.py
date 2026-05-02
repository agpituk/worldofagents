"""Showcase API — leaderboards + per-tool detail + copy flow.

Phase 6 of the agent-tools rollout. Scope reduction (see IMPL_PLAN §5):
ships two leaderboards well — `most_copied` and `best_success` —
and stubs the others. The /compare and /tools/gallery surfaces are
follow-up.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Event, Hero, HeroTool, ToolCopy, ToolDefinition
from app.domains.showcase.canonicalize import canonicalize, tool_id

router = APIRouter(prefix="/api/tools", tags=["showcase"])


# ---------------------------------------------------------------------------
# Indexing — discover tools from hero manifests on demand
# ---------------------------------------------------------------------------


def _index_hero(db: Session, hero: Hero, current_tick: int) -> None:
    """Idempotent: ensure tool_definitions and hero_tools rows exist for
    every tool in this hero's manifest. Called lazily on read paths so
    existing heroes get backfilled the first time their tools are
    inspected. A scheduled batch backfill is follow-up."""
    manifest = hero.manifest or {}
    inner = manifest.get("hero") if isinstance(manifest.get("hero"), dict) else manifest
    tools = (inner or {}).get("tools") or []
    if not isinstance(tools, list):
        return

    for entry in tools:
        if not isinstance(entry, dict):
            continue
        try:
            canonical = canonicalize(entry)
            tid = tool_id(entry)
        except Exception:
            continue

        if db.get(ToolDefinition, tid) is None:
            kind = "override" if "override" in entry else "composite"
            name = entry.get("override") if "override" in entry else entry.get("name")
            if not isinstance(name, str):
                continue
            parent_id = None
            meta = entry.get("_meta")
            if isinstance(meta, dict):
                parent = meta.get("parent_tool_id")
                if isinstance(parent, str):
                    parent_id = parent
            db.add(ToolDefinition(
                tool_id=tid,
                canonical_yaml=canonical,
                name=name,
                kind=kind,
                parent_tool_id=parent_id,
                first_seen_hero=hero.name,
            ))

        # Ensure hero_tools row.
        existing = db.execute(
            select(HeroTool).where(
                HeroTool.hero_id == hero.id, HeroTool.tool_id == tid,
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(HeroTool(
                hero_id=hero.id,
                tool_id=tid,
                added_tick=current_tick,
            ))
    db.flush()


def _index_all(db: Session) -> None:
    """Index every alive hero's tools. Cheap enough for v1 traffic; if
    it shows up in a profile later, replace with a scheduled job."""
    rows = list(db.scalars(select(Hero).where(Hero.status == "alive")))
    for h in rows:
        _index_hero(db, h, current_tick=0)
    db.commit()


# ---------------------------------------------------------------------------
# /api/tools/leaderboards
# ---------------------------------------------------------------------------


class LeaderboardEntry(BaseModel):
    tool_id: str
    name: str
    kind: str
    author: str
    metric: float
    metric_label: str
    description: str


@router.get("/leaderboards", response_model=dict)
def leaderboards(
    db: Annotated[Session, Depends(get_db)],
    board: str = "most_copied",
    limit: int = 10,
) -> dict[str, Any]:
    _index_all(db)

    if board == "most_copied":
        return {"board": "most_copied", "entries": _most_copied(db, limit)}
    if board == "best_success":
        return {"board": "best_success", "entries": _best_success(db, limit)}
    if board in ("most_called", "highest_lift", "david", "best_named"):
        # Stubs in v1 — see IMPL_PLAN §5.
        return {"board": board, "entries": [], "note": "v1 stub — coming soon"}
    raise HTTPException(status_code=400, detail=f"unknown board '{board}'")


def _most_copied(db: Session, limit: int) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            ToolCopy.source_tool_id,
            func.count(ToolCopy.copy_id).label("n"),
        )
        .group_by(ToolCopy.source_tool_id)
        .order_by(func.count(ToolCopy.copy_id).desc())
        .limit(limit)
    ).all()
    out = []
    for tid, count in rows:
        defn = db.get(ToolDefinition, tid)
        if defn is None:
            continue
        out.append({
            "tool_id": tid,
            "name": defn.name,
            "kind": defn.kind,
            "author": defn.first_seen_hero,
            "metric": float(count),
            "metric_label": "copies",
            "description": _description_from_yaml(defn.canonical_yaml),
        })
    return out


def _best_success(db: Session, limit: int) -> list[dict[str, Any]]:
    """Compute success rate per tool by walking the events table for the
    last N rows and aggregating tool.expanded vs tool.gated /
    tool.budget_exceeded counts. Joins back to tool_definitions by name
    (since events carry only the name, not the tool_id). Heroes with
    multiple variants of the same tool name share aggregation here —
    accept the imprecision for the v1 board, mark it in the response."""
    rows = list(db.scalars(
        select(Event)
        .where(Event.kind == "action.resolved")
        .order_by(Event.tick_id.desc())
        .limit(2000)
    ))
    counts: Counter[str] = Counter()
    succ: Counter[str] = Counter()
    for ev in rows:
        debug = (ev.payload or {}).get("debug") or {}
        for entry in debug.get("tool_events") or []:
            event = entry.get("event")
            payload = entry.get("payload") or {}
            tname = payload.get("tool")
            if not isinstance(tname, str):
                continue
            if event == "tool.expanded":
                counts[tname] += 1
                succ[tname] += 1
            elif event == "tool.gated":
                counts[tname] += 1
            elif event == "tool.budget_exceeded":
                if succ[tname] > 0:
                    succ[tname] -= 1

    scored = []
    for name, n in counts.items():
        if n < 5:
            continue
        rate = succ[name] / n
        scored.append((name, rate, n))
    scored.sort(key=lambda x: (-x[1], -x[2]))

    out = []
    for name, rate, n in scored[:limit]:
        defn = db.execute(
            select(ToolDefinition)
            .where(ToolDefinition.name == name)
            .order_by(ToolDefinition.first_seen_at.asc())
            .limit(1)
        ).scalar_one_or_none()
        if defn is None:
            continue
        out.append({
            "tool_id": defn.tool_id,
            "name": defn.name,
            "kind": defn.kind,
            "author": defn.first_seen_hero,
            "metric": round(rate * 100, 1),
            "metric_label": f"success% (n={n})",
            "description": _description_from_yaml(defn.canonical_yaml),
        })
    return out


def _description_from_yaml(canonical: str) -> str:
    """Lift the description field out of a canonical YAML body without
    re-loading. Cheap line scan; falls back to empty string."""
    for line in canonical.splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip("'\"")[:240]
    return ""


# ---------------------------------------------------------------------------
# /api/tools/{tool_id}
# ---------------------------------------------------------------------------


@router.get("/{tool_id_value}")
def tool_detail(
    db: Annotated[Session, Depends(get_db)],
    tool_id_value: str,
) -> dict[str, Any]:
    _index_all(db)
    defn = db.get(ToolDefinition, tool_id_value)
    if defn is None:
        raise HTTPException(status_code=404, detail="tool not found")

    users = list(db.scalars(
        select(HeroTool).where(HeroTool.tool_id == tool_id_value)
    ))
    user_ids = [u.hero_id for u in users]
    user_heroes: list[dict[str, Any]] = []
    if user_ids:
        for h in db.scalars(select(Hero).where(Hero.id.in_(user_ids))):
            user_heroes.append({"id": str(h.id), "name": h.name, "alive": h.status == "alive"})

    copy_count = db.execute(
        select(func.count(ToolCopy.copy_id))
        .where(ToolCopy.source_tool_id == tool_id_value)
    ).scalar_one() or 0

    return {
        "tool_id": defn.tool_id,
        "name": defn.name,
        "kind": defn.kind,
        "author": defn.first_seen_hero,
        "parent_tool_id": defn.parent_tool_id,
        "canonical_yaml": defn.canonical_yaml,
        "users": user_heroes,
        "copy_count": copy_count,
    }


# ---------------------------------------------------------------------------
# POST /api/tools/{tool_id}/copy
# ---------------------------------------------------------------------------


@router.post("/{tool_id_value}/copy")
def copy_tool(
    db: Annotated[Session, Depends(get_db)],
    tool_id_value: str,
    by_hero: str,
) -> dict[str, Any]:
    """Record a "copy this tool" UX click. Doesn't mutate the target
    hero's manifest — that's a deploy-flow concern handled in the
    frontend by re-deploying with the appended tool. This endpoint
    just stamps the lineage so leaderboards know."""
    if db.get(ToolDefinition, tool_id_value) is None:
        raise HTTPException(status_code=404, detail="tool not found")
    try:
        hid = uuid.UUID(by_hero)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid by_hero")
    if db.get(Hero, hid) is None:
        raise HTTPException(status_code=404, detail="hero not found")
    db.add(ToolCopy(source_tool_id=tool_id_value, copied_by_hero=hid))
    db.commit()
    return {"ok": True}
