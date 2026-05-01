"""Highlight feed — auto-detected notable moments.

Read-only over the Event log. We don't write a separate "highlight" row;
instead we project existing events through a scoring filter on each request.
The clip page (per moment) returns the 30-tick window of events around a
given Event.id so spectators can replay the moments.

Notable signals (today):
  • action.resolved with outcome.killed=true on attack_hero (PvP kill)
  • action.resolved with outcome.killed=true on attack against the wyrm
  • hero.died (every permadeath)
  • npc.reaction tagged with `tournament_won` payload
  • world.wyrm.spawned / world.wyrm.expired
  • world.tide.closed (winning faction announcement)
  • discovery milestones (first hidden craft per recipe)
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Event, Hero, JournalEntry

router = APIRouter(tags=["highlights"])


# Score table — higher = more newsworthy. The home-page feed ranks by score
# desc, recency tiebreak.
_KIND_SCORES = {
    "hero.died": 8,
    "world.wyrm.spawned": 6,
    "world.wyrm.expired": 5,
    "world.tide.closed": 7,
}


def _score_event(ev: Event) -> int:
    """Return a 0-10 newsworthiness score, or 0 to skip."""
    if ev.kind in _KIND_SCORES:
        return _KIND_SCORES[ev.kind]
    if ev.kind == "action.resolved":
        outcome = (ev.payload or {}).get("outcome") or {}
        if outcome.get("killed"):
            verb = outcome.get("verb")
            if verb == "attack_hero":
                # PvP kill — the rare drama signal.
                return 9
            if outcome.get("target") == "wyrm_of_the_sundering":
                return 10
            # Mob kill on a high-value target — score modestly.
            return 3
        if outcome.get("verb") == "claim_reward" and outcome.get("title"):
            # Title-earning quest claim (Warden's Recruit etc.)
            return 6
        if outcome.get("verb") == "craft" and outcome.get("discovery"):
            return 7
    return 0


def _summarise(ev: Event, db: Session) -> dict[str, Any]:
    """Render a one-line headline for the home-page feed."""
    payload = ev.payload or {}
    outcome = payload.get("outcome") or {}
    hero = db.get(Hero, ev.hero_id) if ev.hero_id else None
    actor = hero.name if hero else "—"

    if ev.kind == "hero.died":
        killer = payload.get("killer") or "the world"
        kk = payload.get("killer_kind")
        return {"headline": f"{payload.get('name', 'A hero')} fell to {killer}", "killer_kind": kk}
    if ev.kind == "world.wyrm.spawned":
        return {"headline": f"The Wyrm of the Sundering rose in {payload.get('zone')}"}
    if ev.kind == "world.wyrm.expired":
        return {"headline": "The Wyrm slipped away — no one struck the killing blow"}
    if ev.kind == "world.tide.closed":
        winner = payload.get("winner") or "no one"
        return {"headline": f"The tide turned: {winner} claimed {payload.get('claimed_zone')}"}
    if ev.kind == "action.resolved":
        verb = outcome.get("verb")
        if verb == "attack_hero" and outcome.get("killed"):
            return {"headline": f"{actor} killed {outcome.get('target')} in PvP"}
        if outcome.get("target") == "wyrm_of_the_sundering" and outcome.get("killed"):
            return {"headline": f"{actor} slew the Wyrm of the Sundering"}
        if verb == "claim_reward" and outcome.get("title"):
            return {"headline": f"{actor} earned the title: {outcome['title']}"}
        if verb == "craft" and outcome.get("discovery"):
            return {"headline": f"{actor} discovered a new recipe: {outcome.get('produced')}"}
    return {"headline": ev.kind}


@router.get("/highlights")
def list_highlights(db: Annotated[Session, Depends(get_db)], limit: int = 30):
    """Top notable moments across the world. Ranked by score, then recency."""
    candidates = list(
        db.scalars(
            select(Event)
            .where(or_(
                Event.kind.in_(list(_KIND_SCORES.keys())),
                Event.kind == "action.resolved",
            ))
            .order_by(desc(Event.id))
            .limit(500)
        )
    )
    scored: list[tuple[int, Event]] = []
    for ev in candidates:
        s = _score_event(ev)
        if s > 0:
            scored.append((s, ev))
    scored.sort(key=lambda pair: (-pair[0], -pair[1].id))
    out = []
    for score, ev in scored[:limit]:
        summary = _summarise(ev, db)
        out.append({
            "event_id": ev.id,
            "tick_id": ev.tick_id,
            "kind": ev.kind,
            "zone": ev.zone,
            "hero_id": str(ev.hero_id) if ev.hero_id else None,
            "score": score,
            **summary,
        })
    return out


@router.get("/clip/{event_id}")
def get_clip(event_id: int, db: Annotated[Session, Depends(get_db)], window: int = 15):
    """Return a 2*`window`-tick slice of events centred on the moment.
    Defaults to ±15 ticks (~3 minutes of real-time before/after)."""
    pivot = db.get(Event, event_id)
    if pivot is None:
        raise HTTPException(404, "event not found")
    lo = max(0, pivot.tick_id - window)
    hi = pivot.tick_id + window

    rows = list(
        db.scalars(
            select(Event)
            .where(Event.tick_id >= lo, Event.tick_id <= hi)
            .where(or_(
                Event.zone == pivot.zone,
                Event.hero_id == pivot.hero_id,
                Event.id == pivot.id,
            ))
            .order_by(Event.id.asc())
        )
    )
    journal = list(
        db.scalars(
            select(JournalEntry)
            .where(JournalEntry.tick_id >= lo, JournalEntry.tick_id <= hi)
            .order_by(JournalEntry.id.asc())
        )
    )
    pivot_summary = _summarise(pivot, db)
    return {
        "pivot_event_id": pivot.id,
        "pivot_tick": pivot.tick_id,
        "pivot_kind": pivot.kind,
        "headline": pivot_summary.get("headline"),
        "window": [lo, hi],
        "events": [
            {
                "id": e.id,
                "tick_id": e.tick_id,
                "kind": e.kind,
                "zone": e.zone,
                "hero_id": str(e.hero_id) if e.hero_id else None,
                "payload": e.payload,
            }
            for e in rows
        ],
        "journal": [
            {
                "id": j.id,
                "tick_id": j.tick_id,
                "hero_id": str(j.hero_id),
                "kind": j.kind,
                "text": j.text,
                "tags": list(j.tags or []),
            }
            for j in journal
        ],
    }
