from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Hero, Tournament, TournamentEntry

router = APIRouter(prefix="/tournaments", tags=["tournaments"])


class TournamentOut(BaseModel):
    slug: str
    name: str
    description: str
    division: str
    zone: str
    status: str
    starts_at_tick: int
    ends_at_tick: int
    max_entries: int
    prize_gold: int
    prize_faction: str | None
    prize_faction_amount: int
    entries: int = 0


class LeaderboardRow(BaseModel):
    hero_id: str
    name: str
    kills: int
    status: str


class TournamentDetailOut(TournamentOut):
    leaderboard: list[LeaderboardRow] = []


def _serialise(t: Tournament, entries: int = 0) -> TournamentOut:
    return TournamentOut(
        slug=t.slug, name=t.name, description=t.description, division=t.division,
        zone=t.zone, status=t.status,
        starts_at_tick=t.starts_at_tick, ends_at_tick=t.ends_at_tick,
        max_entries=t.max_entries, prize_gold=t.prize_gold,
        prize_faction=t.prize_faction, prize_faction_amount=t.prize_faction_amount,
        entries=entries,
    )


@router.get("", response_model=list[TournamentOut])
def list_tournaments(db: Annotated[Session, Depends(get_db)]):
    rows = list(db.scalars(select(Tournament).order_by(Tournament.slug)))
    out = []
    for t in rows:
        n = db.scalar(
            select(TournamentEntry).where(TournamentEntry.tournament_slug == t.slug).limit(1).with_only_columns(TournamentEntry.id)
        )
        # cheap count — query length of subquery via scalar count
        from sqlalchemy import func as _func
        count = int(db.scalar(
            select(_func.count(TournamentEntry.id)).where(TournamentEntry.tournament_slug == t.slug)
        ) or 0)
        out.append(_serialise(t, entries=count))
    return out


@router.get("/{slug}", response_model=TournamentDetailOut)
def get_tournament(slug: str, db: Annotated[Session, Depends(get_db)]):
    t = db.get(Tournament, slug)
    if t is None:
        raise HTTPException(404, "tournament not found")
    entries = list(
        db.scalars(
            select(TournamentEntry).where(TournamentEntry.tournament_slug == slug)
            .order_by(TournamentEntry.kills.desc(), TournamentEntry.registered_at_tick.asc())
        )
    )
    leaderboard: list[LeaderboardRow] = []
    for e in entries:
        h = db.get(Hero, e.hero_id)
        if h is None:
            continue
        leaderboard.append(LeaderboardRow(
            hero_id=str(h.id), name=h.name, kills=e.kills, status=e.status,
        ))
    return TournamentDetailOut(
        **_serialise(t, entries=len(entries)).model_dump(),
        leaderboard=leaderboard,
    )
