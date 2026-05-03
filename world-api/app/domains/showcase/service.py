"""Showcase service — gallery, comparison, copy, and indexing.

Orchestrates `repository`, `leaderboards`, and `canonicalize`. The
router is a thin HTTP adapter on top of the methods exposed here.
"""

from __future__ import annotations

import copy as _copy
import uuid
from collections import defaultdict
from typing import Any

import yaml
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.models import Hero, HeroTool, ToolDefinition
from app.domains.showcase import leaderboards, repository as repo
from app.domains.showcase.canonicalize import canonicalize, tool_id


# ---------------------------------------------------------------------------
# Manifest helpers (no DB access — pure logic)
# ---------------------------------------------------------------------------


def is_tools_private(hero: Hero) -> bool:
    """Honor the manifest's `hero.tool_visibility: private` opt-out
    (SHOWCASE.md §6). Default is public."""
    manifest = hero.manifest or {}
    inner = manifest.get("hero") if isinstance(manifest.get("hero"), dict) else manifest
    flag = (inner or {}).get("tool_visibility")
    return isinstance(flag, str) and flag.lower() == "private"


def _description_from_yaml(canonical: str) -> str:
    for line in canonical.splitlines():
        if line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip("'\"")[:240]
    return ""


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


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------


def index_hero(db: Session, hero: Hero, current_tick: int) -> None:
    """Idempotent: ensure tool_definitions and hero_tools rows exist for
    every tool in this hero's manifest. Called lazily on read paths so
    existing heroes get backfilled the first time their tools are
    inspected."""
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

        if repo.get_definition(db, tid) is None:
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
            repo.add_definition(db, ToolDefinition(
                tool_id=tid,
                canonical_yaml=canonical,
                name=name,
                kind=kind,
                parent_tool_id=parent_id,
                first_seen_hero=hero.name,
            ))

        if repo.get_hero_tool(db, hero.id, tid) is None:
            repo.add_hero_tool(db, HeroTool(
                hero_id=hero.id,
                tool_id=tid,
                added_tick=current_tick,
            ))
    db.flush()


def index_all(db: Session) -> None:
    """Index every alive hero's tools. Cheap enough for v1 traffic."""
    for h in repo.list_alive_heroes(db):
        if is_tools_private(h):
            continue
        index_hero(db, h, current_tick=0)
    db.commit()


# ---------------------------------------------------------------------------
# Leaderboards (delegates)
# ---------------------------------------------------------------------------


def leaderboard(db: Session, board: str, limit: int) -> dict[str, Any]:
    index_all(db)
    return leaderboards.dispatch(db, board, limit)


# ---------------------------------------------------------------------------
# Tool detail
# ---------------------------------------------------------------------------


def tool_detail(db: Session, tool_id_value: str) -> dict[str, Any]:
    index_all(db)
    defn = repo.get_definition(db, tool_id_value)
    if defn is None:
        raise HTTPException(status_code=404, detail="tool not found")

    user_ids = [u.hero_id for u in repo.list_users_of_tool(db, tool_id_value)]
    user_heroes: list[dict[str, Any]] = []
    for h in repo.get_heroes_by_ids(db, user_ids):
        user_heroes.append({
            "id": str(h.id),
            "name": h.name,
            "alive": h.status == "alive",
        })

    return {
        "tool_id": defn.tool_id,
        "name": defn.name,
        "kind": defn.kind,
        "author": defn.first_seen_hero,
        "parent_tool_id": defn.parent_tool_id,
        "canonical_yaml": defn.canonical_yaml,
        "users": user_heroes,
        "copy_count": repo.count_copies(db, tool_id_value),
    }


# ---------------------------------------------------------------------------
# Copy
# ---------------------------------------------------------------------------


def copy_tool(
    db: Session,
    tool_id_value: str,
    by_hero: str,
    rename: str | None,
) -> dict[str, Any]:
    """Append the tool to the target hero's manifest tools section, plus
    record the copy event for the leaderboard. Per SHOWCASE.md §2.2."""
    source = repo.get_definition(db, tool_id_value)
    if source is None:
        raise HTTPException(status_code=404, detail="tool not found")
    try:
        hid = uuid.UUID(by_hero)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid by_hero")
    target = repo.get_hero_by_id(db, hid)
    if target is None:
        raise HTTPException(status_code=404, detail="hero not found")

    source_entry = yaml.safe_load(source.canonical_yaml) or {}
    if not isinstance(source_entry, dict):
        raise HTTPException(status_code=500, detail="malformed canonical YAML")

    entry = _copy.deepcopy(source_entry)
    entry["_meta"] = {"parent_tool_id": tool_id_value}

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

    own_name = entry.get("override") if "override" in entry else entry.get("name")

    def _entry_name(t: dict) -> str:
        return t["override"] if "override" in t else t.get("name", "")

    used_names = {_entry_name(t) for t in existing_tools if isinstance(t, dict)}

    if rename:
        if "override" in entry:
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
        return {"ok": False, "appended": False, "rename_to": own_name}

    existing_tools.append(entry)
    inner["tools"] = existing_tools
    if "hero" in target_manifest:
        target_manifest["hero"] = inner
    else:
        target_manifest = inner
    target.manifest = target_manifest

    repo.add_copy(db, source_tool_id=tool_id_value, copied_by_hero=hid)
    new_tid = tool_id(entry)
    if repo.get_definition(db, new_tid) is None:
        repo.add_definition(db, ToolDefinition(
            tool_id=new_tid,
            canonical_yaml=canonicalize(entry),
            name=own_name or "",
            kind="override" if "override" in entry else "composite",
            parent_tool_id=tool_id_value,
            first_seen_hero=target.name,
        ))
    repo.add_hero_tool(db, HeroTool(
        hero_id=hid,
        tool_id=new_tid,
        added_tick=0,
    ))
    db.commit()
    return {"ok": True, "appended": True, "new_tool_id": new_tid}


# ---------------------------------------------------------------------------
# Gallery
# ---------------------------------------------------------------------------


def gallery(db: Session, category: str | None) -> dict[str, Any]:
    """Curated discovery surface. SHOWCASE.md §4."""
    index_all(db)
    defs = repo.list_definitions(db)
    copy_counts = repo.copies_grouped(db)

    featured: list[dict[str, Any]] = []
    noteworthy: list[dict[str, Any]] = []
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for defn in defs:
        desc = _description_from_yaml(defn.canonical_yaml)
        cat = _infer_category(defn.name, desc, defn.canonical_yaml)
        card = _entry(
            defn,
            metric=float(copy_counts.get(defn.tool_id, 0)),
            metric_label="copies",
        )
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
# Compare
# ---------------------------------------------------------------------------


def compare(db: Session, heroes: str) -> dict[str, Any]:
    """Side-by-side hero comparison payload. SHOWCASE.md §3.

    `heroes` is a comma-separated list of 2-4 hero ids (UUID) or names."""
    index_all(db)
    raw_ids = [h.strip() for h in heroes.split(",") if h.strip()]
    if not (2 <= len(raw_ids) <= 4):
        raise HTTPException(status_code=400, detail="heroes must list 2-4 entries")

    resolved: list[Hero] = []
    for raw in raw_ids:
        hero: Hero | None = None
        try:
            hero = repo.get_hero_by_id(db, uuid.UUID(raw))
        except ValueError:
            hero = repo.get_hero_by_name(db, raw)
        if hero is None:
            raise HTTPException(status_code=404, detail=f"hero not found: {raw}")
        resolved.append(hero)

    out_heroes: list[dict[str, Any]] = []
    by_name: dict[str, list[tuple[Hero, ToolDefinition]]] = defaultdict(list)
    for hero in resolved:
        if is_tools_private(hero):
            out_heroes.append({
                "id": str(hero.id),
                "name": hero.name,
                "division": hero.division,
                "alive": hero.status == "alive",
                "tools_private": True,
                "tools": [],
            })
            continue
        rows = repo.list_hero_tools_for_hero(db, hero.id)
        tools_payload: list[dict[str, Any]] = []
        for ht in rows:
            defn = repo.get_definition(db, ht.tool_id)
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
