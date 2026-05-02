"""Contract board — the unified labor market.

Phase 4 of the build-diversity roadmap. Six kinds:

  bounty        — kill <target_hero>, paid to whoever lands the blow.
  assassination — kill <target_hero> inside a specific zone or window.
  defense       — claimer kills hostiles in poster's zone while adjacent.
  delivery      — claimer `give`s a specific item to a specific NPC in the
                  destination zone.
  escort        — claimer follows the poster across zones (auto-pay TODO).
  caravan       — heavy delivery (auto-pay on give; loot-on-death TODO).

GET /contracts                    — open contracts, filterable by kind / status / zone
GET /contracts/{id}               — single contract

POST verbs (`post_contract`, `claim_contract`, `cancel_contract`) live
on the agent action layer, not here — heroes act through the WS, not
HTTP. This router is the spectator + share-URL surface, plus the data
backend for `open_contracts_in_zone` perception bindings.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Contract

router = APIRouter(prefix="/contracts", tags=["contracts"])


VALID_KINDS = ("bounty", "assassination", "defense", "delivery", "escort", "caravan")
VALID_STATUSES = ("open", "claimed", "fulfilled", "expired", "all")


class ContractOut(BaseModel):
    id: str
    kind: str
    poster_hero_id: str | None
    poster_name: str
    target_hero_id: str | None
    target_ref: str | None
    reward_gold: int
    status: str
    zone_scope: str | None
    reason: str
    terms: dict[str, Any]
    created_at_tick: int
    expires_at_tick: int | None
    claimed_by_hero_id: str | None
    claimed_at_tick: int | None
    fulfilled_at_tick: int | None


def _serialise(c: Contract) -> ContractOut:
    return ContractOut(
        id=str(c.id),
        kind=c.kind,
        poster_hero_id=str(c.poster_hero_id) if c.poster_hero_id else None,
        poster_name=c.poster_name,
        target_hero_id=str(c.target_hero_id) if c.target_hero_id else None,
        target_ref=c.target_ref,
        reward_gold=int(c.reward_gold or 0),
        status=c.status,
        zone_scope=c.zone_scope,
        reason=c.reason,
        terms=dict(c.terms or {}),
        created_at_tick=int(c.created_at_tick or 0),
        expires_at_tick=c.expires_at_tick,
        claimed_by_hero_id=str(c.claimed_by_hero_id) if c.claimed_by_hero_id else None,
        claimed_at_tick=c.claimed_at_tick,
        fulfilled_at_tick=c.fulfilled_at_tick,
    )


@router.get("", response_model=list[ContractOut])
def list_contracts(
    db: Annotated[Session, Depends(get_db)],
    status: Literal["open", "claimed", "fulfilled", "expired", "all"] = "open",
    kind: str | None = None,
    zone: str | None = None,
    limit: int = 100,
):
    """List contracts. Defaults to status=open, all kinds, all zones."""
    q = select(Contract)
    if status != "all":
        q = q.where(Contract.status == status)
    if kind is not None:
        if kind not in VALID_KINDS:
            raise HTTPException(400, f"unknown kind '{kind}' (valid: {VALID_KINDS})")
        q = q.where(Contract.kind == kind)
    if zone is not None:
        q = q.where(Contract.zone_scope == zone)
    q = q.order_by(
        Contract.reward_gold.desc(),
        Contract.created_at_tick.desc(),
    ).limit(min(max(1, limit), 500))
    return [_serialise(c) for c in db.scalars(q)]


@router.get("/{contract_id}", response_model=ContractOut)
def get_contract(contract_id: str, db: Annotated[Session, Depends(get_db)]):
    try:
        cid = _uuid.UUID(contract_id)
    except ValueError:
        raise HTTPException(404, "contract not found")
    c = db.get(Contract, cid)
    if c is None:
        raise HTTPException(404, "contract not found")
    return _serialise(c)
