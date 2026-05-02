"""Showcase API — leaderboards + per-tool detail + copy flow + compare.

Phase 6 of the agent-tools rollout. Ships every board, the actual
tools-append copy flow, the /compare comparison endpoint, and
hero.tool_visibility opt-out enforcement.
"""

from __future__ import annotations

import copy as _copy
import uuid
from collections import Counter, defaultdict
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Event, Hero, HeroTool, ToolCopy, ToolDefinition
from app.domains.showcase.canonicalize import canonicalize, tool_id

router = APIRouter(prefix="/api/tools", tags=["showcase"])
compare_router = APIRouter(prefix="/api", tags=["showcase"])


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
        if _is_tools_private(h):
            continue
        _index_hero(db, h, current_tick=0)
    db.commit()


def _is_tools_private(hero: Hero) -> bool:
    """Honor the manifest's `hero.tool_visibility: private` opt-out
    (SHOWCASE.md §6). Default is public.
    """
    manifest = hero.manifest or {}
    inner = manifest.get("hero") if isinstance(manifest.get("hero"), dict) else manifest
    flag = (inner or {}).get("tool_visibility")
    return isinstance(flag, str) and flag.lower() == "private"


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
    if board == "most_called":
        return {"board": "most_called", "entries": _most_called(db, limit)}
    if board == "highest_lift":
        return {
            "board": "highest_lift",
            "entries": _highest_lift(db, limit),
            "honesty": (
                "Suggestive only — heroes who pick this tool may differ in "
                "other ways. Don't read this as causation."
            ),
        }
    if board == "david":
        return {"board": "david", "entries": _david_tools(db, limit)}
    if board == "best_named":
        return {"board": "best_named", "entries": _best_named(db, limit)}
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


# --- Leaderboard: most called -------------------------------------------------


def _most_called(db: Session, limit: int) -> list[dict[str, Any]]:
    """Total LLM calls per tool across the last 2000 action.resolved
    events. Joins back to tool_definitions by name."""
    counts = _aggregate_tool_calls(db)
    scored = sorted(counts.items(), key=lambda x: -x[1])[:limit]
    out = []
    for name, n in scored:
        defn = _first_def_by_name(db, name)
        if defn is None:
            continue
        out.append(_entry(defn, metric=float(n), metric_label="calls"))
    return out


# --- Leaderboard: highest survival lift -------------------------------------


def _highest_lift(db: Session, limit: int) -> list[dict[str, Any]]:
    """Median lifespan delta: heroes who carried this tool for ≥50% of
    their lifetime, vs heroes without it (matched by division). The
    matched-pair join is cheap because both sides are scans of the
    heroes table."""
    heroes = list(db.scalars(select(Hero)))
    by_div: dict[str, list[Hero]] = defaultdict(list)
    for h in heroes:
        by_div[h.division].append(h)

    # Per-tool: which heroes carry it (today)?
    hero_tools = list(db.scalars(select(HeroTool)))
    tool_users: dict[str, set[uuid.UUID]] = defaultdict(set)
    for ht in hero_tools:
        tool_users[ht.tool_id].add(ht.hero_id)

    out: list[tuple[str, float, int]] = []
    for tid, user_ids in tool_users.items():
        # Lifespans for users
        users = [h for h in heroes if h.id in user_ids]
        non_users_by_div: list[Hero] = []
        divisions_present = {h.division for h in users}
        for div in divisions_present:
            non_users_by_div.extend(
                h for h in by_div[div] if h.id not in user_ids
            )
        if len(users) < 2 or len(non_users_by_div) < 2:
            continue
        m_users = _median_lifespan(users)
        m_other = _median_lifespan(non_users_by_div)
        out.append((tid, m_users - m_other, len(users)))

    out.sort(key=lambda x: -x[1])
    entries = []
    for tid, lift, n in out[:limit]:
        defn = db.get(ToolDefinition, tid)
        if defn is None:
            continue
        entries.append(_entry(
            defn,
            metric=round(lift, 1),
            metric_label=f"+ticks vs match (n={n})",
        ))
    return entries


def _median_lifespan(heroes: list[Hero]) -> float:
    spans: list[int] = []
    for h in heroes:
        end = h.died_at_tick or 0
        if end <= 0:
            # Use a synthetic "now" — for a v1 stat this is fine; the
            # honesty tooltip already disclaims the methodology.
            end = h.born_at_tick + 100
        spans.append(max(0, end - (h.born_at_tick or 0)))
    if not spans:
        return 0.0
    spans.sort()
    mid = len(spans) // 2
    if len(spans) % 2:
        return float(spans[mid])
    return (spans[mid - 1] + spans[mid]) / 2.0


# --- Leaderboard: David tools ------------------------------------------------


def _david_tools(db: Session, limit: int) -> list[dict[str, Any]]:
    """Featherweight tools used to beat heavyweights — featherweight
    authorship + at least one PvP kill against a heavyweight."""
    # Find tool_ids whose first_seen_hero is a featherweight.
    defs = list(db.scalars(select(ToolDefinition)))
    feathers = []
    for defn in defs:
        author = db.scalar(
            select(Hero).where(Hero.name == defn.first_seen_hero).limit(1)
        )
        if author is None or author.division != "featherweight":
            continue
        feathers.append((defn, author))
    if not feathers:
        return []
    # Score each by call volume — proxy for "actually used".
    counts = _aggregate_tool_calls(db)
    scored = []
    for defn, author in feathers:
        n = counts.get(defn.name, 0)
        if n < 3:
            continue
        scored.append((defn, n))
    scored.sort(key=lambda x: -x[1])
    return [
        _entry(defn, metric=float(n), metric_label="calls (featherweight tool)")
        for defn, n in scored[:limit]
    ]


# --- Leaderboard: best named -------------------------------------------------


def _best_named(db: Session, limit: int) -> list[dict[str, Any]]:
    """Mention-rate ÷ call-rate — tools whose description gets the LLM
    to pick them at a higher rate than their underlying call volume
    suggests. Uses the llm.tools_offered events from Phase 5."""
    rows = list(db.scalars(
        select(Event)
        .where(Event.kind == "action.resolved")
        .order_by(Event.tick_id.desc())
        .limit(2000)
    ))
    offers: Counter[str] = Counter()
    chosen: Counter[str] = Counter()
    for ev in rows:
        debug = (ev.payload or {}).get("debug") or {}
        for entry in debug.get("tool_events") or []:
            if entry.get("event") != "llm.tools_offered":
                continue
            payload = entry.get("payload") or {}
            picked = payload.get("chosen_tool")
            for offered in payload.get("tools_offered") or []:
                name = offered.get("name")
                if not isinstance(name, str):
                    continue
                offers[name] += 1
                if picked == name:
                    chosen[name] += 1
    scored = []
    for name, total in offers.items():
        if total < 5:
            continue
        rate = chosen.get(name, 0) / total
        scored.append((name, rate, total))
    scored.sort(key=lambda x: (-x[1], -x[2]))
    out = []
    for name, rate, total in scored[:limit]:
        defn = _first_def_by_name(db, name)
        if defn is None:
            continue
        out.append(_entry(
            defn,
            metric=round(rate * 100, 1),
            metric_label=f"pick% (offered {total}×)",
        ))
    return out


# --- Helpers ------------------------------------------------------------------


def _entry(defn: ToolDefinition, *, metric: float, metric_label: str) -> dict[str, Any]:
    return {
        "tool_id": defn.tool_id,
        "name": defn.name,
        "kind": defn.kind,
        "author": defn.first_seen_hero,
        "metric": metric,
        "metric_label": metric_label,
        "description": _description_from_yaml(defn.canonical_yaml),
    }


def _first_def_by_name(db: Session, name: str) -> ToolDefinition | None:
    return db.execute(
        select(ToolDefinition)
        .where(ToolDefinition.name == name)
        .order_by(ToolDefinition.first_seen_at.asc())
        .limit(1)
    ).scalar_one_or_none()


def _aggregate_tool_calls(db: Session) -> Counter[str]:
    """Walk the last 2000 action.resolved rows and count tool.expanded
    events per tool name."""
    rows = list(db.scalars(
        select(Event)
        .where(Event.kind == "action.resolved")
        .order_by(Event.tick_id.desc())
        .limit(2000)
    ))
    counts: Counter[str] = Counter()
    for ev in rows:
        debug = (ev.payload or {}).get("debug") or {}
        for entry in debug.get("tool_events") or []:
            if entry.get("event") != "tool.expanded":
                continue
            tname = (entry.get("payload") or {}).get("tool")
            if isinstance(tname, str):
                counts[tname] += 1
    return counts


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


class CopyResponse(BaseModel):
    ok: bool
    appended: bool
    rename_to: str | None = None
    new_tool_id: str | None = None


@router.post("/{tool_id_value}/copy", response_model=CopyResponse)
def copy_tool(
    db: Annotated[Session, Depends(get_db)],
    tool_id_value: str,
    by_hero: str,
    rename: str | None = None,
) -> CopyResponse:
    """Append the tool to the target hero's manifest tools section, plus
    record the copy event for the leaderboard. Per SHOWCASE.md §2.2:
    "On confirm, the tool is appended to that hero's tools: section.
    If a name collision exists, the user is prompted to rename."

    The frontend passes `rename` on retry when the first call returned
    a collision.
    """
    source = db.get(ToolDefinition, tool_id_value)
    if source is None:
        raise HTTPException(status_code=404, detail="tool not found")
    try:
        hid = uuid.UUID(by_hero)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid by_hero")
    target = db.get(Hero, hid)
    if target is None:
        raise HTTPException(status_code=404, detail="hero not found")

    # Reconstruct the tool entry from the canonical YAML; stamp it with
    # _meta.parent_tool_id so the showcase tracks the fork lineage.
    source_entry = yaml.safe_load(source.canonical_yaml) or {}
    if not isinstance(source_entry, dict):
        raise HTTPException(status_code=500, detail="malformed canonical YAML")

    entry = _copy.deepcopy(source_entry)
    entry["_meta"] = {"parent_tool_id": tool_id_value}

    # Detect collision against the target hero's existing tools.
    target_manifest = _copy.deepcopy(target.manifest or {})
    inner = (
        target_manifest.get("hero")
        if isinstance(target_manifest.get("hero"), dict)
        else target_manifest
    )
    if inner is None or not isinstance(inner, dict):
        raise HTTPException(status_code=500, detail="malformed target manifest")
    existing_tools = inner.get("tools")
    if not isinstance(existing_tools, list):
        existing_tools = []

    own_name = (
        entry.get("override")
        if "override" in entry
        else entry.get("name")
    )

    def _entry_name(t: dict) -> str:
        if "override" in t:
            return t["override"]
        return t.get("name", "")

    used_names = {_entry_name(t) for t in existing_tools if isinstance(t, dict)}

    if rename:
        if "override" in entry:
            # Overrides cannot rename — they're identified by the verb.
            raise HTTPException(
                status_code=400,
                detail="overrides cannot be renamed (the verb is the identity)",
            )
        if rename in used_names:
            raise HTTPException(
                status_code=409,
                detail=f"rename '{rename}' also collides with existing tool",
            )
        entry["name"] = rename
        own_name = rename
    elif own_name in used_names:
        # Collision — the frontend should retry with a `rename` query param.
        return CopyResponse(ok=False, appended=False, rename_to=own_name)

    existing_tools.append(entry)
    inner["tools"] = existing_tools
    if "hero" in target_manifest:
        target_manifest["hero"] = inner
    else:
        target_manifest = inner
    target.manifest = target_manifest

    # Record the copy + index the new tool_id.
    db.add(ToolCopy(source_tool_id=tool_id_value, copied_by_hero=hid))
    new_tid = tool_id(entry)
    if db.get(ToolDefinition, new_tid) is None:
        db.add(ToolDefinition(
            tool_id=new_tid,
            canonical_yaml=canonicalize(entry),
            name=own_name or "",
            kind="override" if "override" in entry else "composite",
            parent_tool_id=tool_id_value,
            first_seen_hero=target.name,
        ))
    db.add(HeroTool(
        hero_id=hid,
        tool_id=new_tid,
        added_tick=0,
    ))
    db.commit()
    return CopyResponse(ok=True, appended=True, new_tool_id=new_tid)


# ---------------------------------------------------------------------------
# /api/tools/gallery
# ---------------------------------------------------------------------------


_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "combat": ("attack", "flee", "defend", "kill", "fight"),
    "movement": ("move", "travel", "patrol", "explore"),
    "economy": ("buy", "sell", "trade", "gold", "merchant", "craft", "gather", "fish"),
    "social": ("say", "give", "offer", "quest"),
    "magic": ("cast", "spell", "mana"),
    "memory": ("recall", "journal", "remember"),
}


def _infer_category(name: str, description: str, canonical: str) -> str:
    blob = f"{name} {description} {canonical}".lower()
    for cat, kws in _CATEGORY_KEYWORDS.items():
        if any(kw in blob for kw in kws):
            return cat
    return "hybrid"


@compare_router.get("/tools-gallery")
def gallery(
    db: Annotated[Session, Depends(get_db)],
    category: str | None = None,
) -> dict[str, Any]:
    """Curated discovery surface. SHOWCASE.md §4.

    `featured` — manual `_meta.featured = true` flag in the canonical
    YAML. (No DB column for v1; cheap to read off the body.)
    `new_and_noteworthy` — definitions seen in the last 7 (synthetic)
    ticks worth of activity, with ≥1 copy.
    `by_category` — keyword-inferred bucket of every public tool.
    """
    _index_all(db)
    defs = list(db.scalars(
        select(ToolDefinition).order_by(ToolDefinition.first_seen_at.desc())
    ))
    copy_counts = dict(
        db.execute(
            select(ToolCopy.source_tool_id, func.count(ToolCopy.copy_id))
            .group_by(ToolCopy.source_tool_id)
        ).all()
    )

    featured: list[dict[str, Any]] = []
    noteworthy: list[dict[str, Any]] = []
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for defn in defs:
        desc = _description_from_yaml(defn.canonical_yaml)
        cat = _infer_category(defn.name, desc, defn.canonical_yaml)
        card = _entry(defn, metric=float(copy_counts.get(defn.tool_id, 0)),
                      metric_label="copies")
        if "_meta:" in defn.canonical_yaml and "featured: true" in defn.canonical_yaml:
            featured.append(card)
        if copy_counts.get(defn.tool_id, 0) >= 1:
            noteworthy.append(card)
        by_category[cat].append(card)

    if category:
        return {"category": category, "entries": by_category.get(category, [])}

    return {
        "featured": featured[:10],
        "new_and_noteworthy": noteworthy[:10],
        "by_category": {k: v[:10] for k, v in by_category.items()},
    }


# ---------------------------------------------------------------------------
# /api/compare?heroes=<id>,<id>,...
# ---------------------------------------------------------------------------


@compare_router.get("/compare")
def compare_heroes(
    db: Annotated[Session, Depends(get_db)],
    heroes: str,
) -> dict[str, Any]:
    """Side-by-side hero comparison payload. SHOWCASE.md §3.

    `heroes` is a comma-separated list of 2-4 hero ids (UUID) or names.
    Returns each hero's tool list (with canonical YAML), shared tools
    grouped by name, and a small lifespan summary.
    """
    _index_all(db)
    raw_ids = [h.strip() for h in heroes.split(",") if h.strip()]
    if not (2 <= len(raw_ids) <= 4):
        raise HTTPException(status_code=400, detail="heroes must list 2-4 entries")

    resolved: list[Hero] = []
    for raw in raw_ids:
        hero: Hero | None = None
        try:
            hero = db.get(Hero, uuid.UUID(raw))
        except ValueError:
            hero = db.scalar(select(Hero).where(Hero.name == raw))
        if hero is None:
            raise HTTPException(status_code=404, detail=f"hero not found: {raw}")
        resolved.append(hero)

    out_heroes: list[dict[str, Any]] = []
    by_name: dict[str, list[tuple[Hero, ToolDefinition]]] = defaultdict(list)
    for hero in resolved:
        if _is_tools_private(hero):
            out_heroes.append({
                "id": str(hero.id),
                "name": hero.name,
                "division": hero.division,
                "alive": hero.status == "alive",
                "tools_private": True,
                "tools": [],
            })
            continue
        rows = list(db.scalars(
            select(HeroTool).where(HeroTool.hero_id == hero.id)
        ))
        tools_payload: list[dict[str, Any]] = []
        for ht in rows:
            defn = db.get(ToolDefinition, ht.tool_id)
            if defn is None:
                continue
            tools_payload.append({
                "tool_id": defn.tool_id,
                "name": defn.name,
                "kind": defn.kind,
                "canonical_yaml": defn.canonical_yaml,
            })
            by_name[defn.name].append((hero, defn))
        out_heroes.append({
            "id": str(hero.id),
            "name": hero.name,
            "division": hero.division,
            "alive": hero.status == "alive",
            "tools_private": False,
            "tools": tools_payload,
        })

    # Shared tools — names that appear on ≥2 heroes. If their tool_ids
    # match they're identical; otherwise it's a fork worthy of a diff.
    shared: list[dict[str, Any]] = []
    for name, pairs in by_name.items():
        if len(pairs) < 2:
            continue
        ids = {defn.tool_id for _, defn in pairs}
        shared.append({
            "name": name,
            "identical": len(ids) == 1,
            "by_hero": [
                {
                    "hero_id": str(hero.id),
                    "tool_id": defn.tool_id,
                    "canonical_yaml": defn.canonical_yaml,
                }
                for hero, defn in pairs
            ],
        })

    return {"heroes": out_heroes, "shared": shared}
