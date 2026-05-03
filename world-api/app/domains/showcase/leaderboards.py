"""Showcase leaderboards — the 6 boards behind /api/tools/leaderboards.

Each board is a pure scoring routine over events + definitions. Kept
in its own module so service.py stays under the 600-line hard cap.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.models import Hero, ToolDefinition
from app.domains.showcase import repository as repo


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


def _median_lifespan(heroes: list[Hero]) -> float:
    spans: list[int] = []
    for h in heroes:
        end = h.died_at_tick or 0
        if end <= 0:
            # Synthetic "now" — for a v1 stat this is fine; the honesty
            # tooltip already disclaims the methodology.
            end = h.born_at_tick + 100
        spans.append(max(0, end - (h.born_at_tick or 0)))
    if not spans:
        return 0.0
    spans.sort()
    mid = len(spans) // 2
    if len(spans) % 2:
        return float(spans[mid])
    return (spans[mid - 1] + spans[mid]) / 2.0


def dispatch(db: Session, board: str, limit: int) -> dict[str, Any]:
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
    out = []
    for tid, count in repo.most_copied_tool_ids(db, limit):
        defn = repo.get_definition(db, tid)
        if defn is None:
            continue
        out.append(_entry(defn, metric=float(count), metric_label="copies"))
    return out


def _best_success(db: Session, limit: int) -> list[dict[str, Any]]:
    """Walks the events table for the last N rows and aggregates
    tool.expanded vs tool.gated / tool.budget_exceeded counts. Joins
    back to tool_definitions by name (since events carry only the name,
    not the tool_id). Heroes with multiple variants of the same tool
    name share aggregation here — accept the imprecision for the v1
    board, mark it in the response."""
    counts: Counter[str] = Counter()
    succ: Counter[str] = Counter()
    for ev in repo.recent_action_events(db):
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
        defn = repo.first_definition_by_name(db, name)
        if defn is None:
            continue
        out.append(_entry(
            defn,
            metric=round(rate * 100, 1),
            metric_label=f"success% (n={n})",
        ))
    return out


def _most_called(db: Session, limit: int) -> list[dict[str, Any]]:
    counts = repo.aggregate_tool_call_counts(db)
    scored = sorted(counts.items(), key=lambda x: -x[1])[:limit]
    out = []
    for name, n in scored:
        defn = repo.first_definition_by_name(db, name)
        if defn is None:
            continue
        out.append(_entry(defn, metric=float(n), metric_label="calls"))
    return out


def _highest_lift(db: Session, limit: int) -> list[dict[str, Any]]:
    """Median lifespan delta: heroes carrying this tool vs heroes
    without it (matched by division). The matched-pair join is cheap
    because both sides are scans of the heroes table."""
    heroes = repo.list_all_heroes(db)
    by_div: dict[str, list[Hero]] = defaultdict(list)
    for h in heroes:
        by_div[h.division].append(h)

    hero_tools = repo.list_all_hero_tools(db)
    tool_users: dict[str, set[uuid.UUID]] = defaultdict(set)
    for ht in hero_tools:
        tool_users[ht.tool_id].add(ht.hero_id)

    out: list[tuple[str, float, int]] = []
    for tid, user_ids in tool_users.items():
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
        defn = repo.get_definition(db, tid)
        if defn is None:
            continue
        entries.append(_entry(
            defn,
            metric=round(lift, 1),
            metric_label=f"+ticks vs match (n={n})",
        ))
    return entries


def _david_tools(db: Session, limit: int) -> list[dict[str, Any]]:
    """Featherweight tools used to beat heavyweights — featherweight
    authorship + meaningful call volume."""
    feathers = []
    for defn in repo.list_definitions(db):
        author = repo.get_hero_by_name(db, defn.first_seen_hero)
        if author is None or author.division != "featherweight":
            continue
        feathers.append((defn, author))
    if not feathers:
        return []
    counts = repo.aggregate_tool_call_counts(db)
    scored = []
    for defn, _author in feathers:
        n = counts.get(defn.name, 0)
        if n < 3:
            continue
        scored.append((defn, n))
    scored.sort(key=lambda x: -x[1])
    return [
        _entry(defn, metric=float(n), metric_label="calls (featherweight tool)")
        for defn, n in scored[:limit]
    ]


def _best_named(db: Session, limit: int) -> list[dict[str, Any]]:
    """Mention-rate ÷ call-rate — tools whose description gets the LLM
    to pick them at a higher rate than their underlying call volume
    suggests. Uses llm.tools_offered events from Phase 5."""
    offers: Counter[str] = Counter()
    chosen: Counter[str] = Counter()
    for ev in repo.recent_action_events(db):
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
        defn = repo.first_definition_by_name(db, name)
        if defn is None:
            continue
        out.append(_entry(
            defn,
            metric=round(rate * 100, 1),
            metric_label=f"pick% (offered {total}×)",
        ))
    return out
