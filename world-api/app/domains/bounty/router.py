"""Bounty board — public hits on heroes.

GET  /bounties               — open bounties (sorted by gold desc, latest tiebreak)
POST /bounties               — spectator-posted bounty (no auth, capped, rate-limited)
GET  /bounties/{id}          — single bounty
"""

from __future__ import annotations

import time
import uuid as _uuid
from collections import defaultdict, deque
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Bounty, Hero, Tick

router = APIRouter(prefix="/bounties", tags=["bounties"])


class BountyOut(BaseModel):
    id: str
    target_hero_id: str
    target_name: str
    poster_hero_id: str | None
    poster_name: str
    reason: str
    gold: int
    status: str
    created_at_tick: int
    claimed_by_hero_id: str | None
    claimed_at_tick: int | None


def _serialise(b: Bounty) -> BountyOut:
    return BountyOut(
        id=str(b.id),
        target_hero_id=str(b.target_hero_id),
        target_name=b.target_name,
        poster_hero_id=str(b.poster_hero_id) if b.poster_hero_id else None,
        poster_name=b.poster_name,
        reason=b.reason,
        gold=b.gold,
        status=b.status,
        created_at_tick=b.created_at_tick,
        claimed_by_hero_id=str(b.claimed_by_hero_id) if b.claimed_by_hero_id else None,
        claimed_at_tick=b.claimed_at_tick,
    )


@router.get("", response_model=list[BountyOut])
def list_open_bounties(
    db: Annotated[Session, Depends(get_db)],
    status: Literal["open", "claimed", "expired", "all"] = "open",
):
    q = select(Bounty)
    if status != "all":
        q = q.where(Bounty.status == status)
    q = q.order_by(Bounty.gold.desc(), Bounty.created_at_tick.desc())
    return [_serialise(b) for b in db.scalars(q)]


@router.get("/{bounty_id}", response_model=BountyOut)
def get_bounty(bounty_id: str, db: Annotated[Session, Depends(get_db)]):
    try:
        bid = _uuid.UUID(bounty_id)
    except ValueError:
        raise HTTPException(404, "bounty not found")
    b = db.get(Bounty, bid)
    if b is None:
        raise HTTPException(404, "bounty not found")
    return _serialise(b)


# Spectator-posted bounties: no auth, capped low, rate-limited per client IP.
# This is sandbox mode — the gold is created out of thin air, not paid by a
# real account. Lets viewers feel like participants without payment infra.
SPECTATOR_BOUNTY_MAX_GOLD = 100
SPECTATOR_BOUNTY_RATE_WINDOW_S = 3600     # 1 hour
SPECTATOR_BOUNTY_RATE_LIMIT = 3           # 3 bounties per window per IP

_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


def _rate_limit_check(ip: str) -> tuple[bool, int]:
    """Sliding-window per-IP rate limit. Returns `(allowed, seconds_until_next)`.
    In-memory only; resets on world-api restart. Good enough for sandbox-mode
    anti-spam."""
    now = time.time()
    bucket = _rate_buckets[ip]
    while bucket and now - bucket[0] > SPECTATOR_BOUNTY_RATE_WINDOW_S:
        bucket.popleft()
    if len(bucket) >= SPECTATOR_BOUNTY_RATE_LIMIT:
        seconds_until = max(1, int(SPECTATOR_BOUNTY_RATE_WINDOW_S - (now - bucket[0])))
        return False, seconds_until
    bucket.append(now)
    return True, 0


class SpectatorBountyIn(BaseModel):
    target_name: str = Field(min_length=2, max_length=120)
    gold: int = Field(ge=10, le=SPECTATOR_BOUNTY_MAX_GOLD)
    reason: str = Field(default="", max_length=280)
    poster_name: str = Field(default="anonymous spectator", max_length=80)
    # Honeypot: a real human leaves this empty (it's CSS-hidden in the
    # form). Bots crawl + fill every text input they see, so a non-empty
    # value is a strong bot signal. We accept the request and return a
    # plausible-looking response, but never write the bounty.
    confirm_email: str = Field(default="", max_length=200)


@router.post("", response_model=BountyOut, status_code=201)
def post_spectator_bounty(
    body: SpectatorBountyIn,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    """Spectator-posted bounty (no auth). The gold is created from thin air —
    sandbox mode. Capped at 100g and rate-limited per client IP. Posters
    cannot self-target a hero (they have no hero) so anti-griefing comes
    from rate limits."""
    # Honeypot — silent reject. Return a fake-looking response so bots think
    # it worked, but write nothing. Real users won't fill the hidden field.
    if body.confirm_email.strip():
        return BountyOut(
            id=str(_uuid.uuid4()), target_hero_id="", target_name=body.target_name,
            poster_hero_id=None, poster_name=body.poster_name, reason=body.reason,
            gold=body.gold, status="open", created_at_tick=0,
            claimed_by_hero_id=None, claimed_at_tick=None,
        )

    ip = (request.client.host if request.client else "unknown") or "unknown"
    allowed, seconds_until = _rate_limit_check(ip)
    if not allowed:
        raise HTTPException(
            429,
            detail={
                "error": "rate_limit",
                "message": f"rate limit exceeded ({SPECTATOR_BOUNTY_RATE_LIMIT}/h per IP)",
                "retry_after_seconds": seconds_until,
            },
        )

    target = db.scalar(select(Hero).where(Hero.name == body.target_name))
    if target is None:
        raise HTTPException(404, f"no hero named '{body.target_name}'")
    if target.status != "alive":
        raise HTTPException(409, "target is already dead")

    current_tick = int(db.scalar(select(func.max(Tick.id))) or 0)
    poster_name = body.poster_name.strip()[:80] or "anonymous spectator"
    bounty = Bounty(
        id=_uuid.uuid4(),
        target_hero_id=target.id, target_name=target.name,
        poster_hero_id=None, poster_name=poster_name,
        reason=body.reason[:280], gold=body.gold, status="open",
        created_at_tick=current_tick,
    )
    db.add(bounty)
    db.commit()
    db.refresh(bounty)
    return _serialise(bounty)
