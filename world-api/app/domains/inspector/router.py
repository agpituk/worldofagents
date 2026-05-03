"""Inspector API — surfaces per-hero tool stats and per-tick LLM
reasoning to the spectator UI.

Phase 5 of the agent-tools rollout. The data lives in the existing
Event table — `action.resolved` rows carry a `debug.tool_events` list
populated by the managed runner (see `world-api/app/managed/runner.py`).
This router is a thin glue layer; aggregation lives in `service.py` and
queries live in `repository.py`.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import optional_owner_token
from app.core.database import get_db
from app.core.models import Hero
from app.domains.inspector import service

router = APIRouter(prefix="/api/heroes", tags=["inspector"])


def _hero_id_or_404(db: Session, hero_id: str) -> uuid.UUID:
    try:
        hid = uuid.UUID(hero_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid hero_id")
    if db.get(Hero, hid) is None:
        raise HTTPException(status_code=404, detail="hero not found")
    return hid


@router.get("/{hero_id}/tools/summary")
def tools_summary(
    db: Annotated[Session, Depends(get_db)],
    hero_id: str,
) -> dict[str, Any]:
    hid = _hero_id_or_404(db, hero_id)
    return service.tools_summary(db, hero_id, hid)


@router.get("/{hero_id}/tools/{tool_name}")
def tool_detail(
    db: Annotated[Session, Depends(get_db)],
    hero_id: str,
    tool_name: str,
) -> dict[str, Any]:
    hid = _hero_id_or_404(db, hero_id)
    out = service.tool_detail(db, hid, tool_name)
    if out is None:
        raise HTTPException(status_code=404, detail="tool not found on this hero")
    return out


@router.get("/{hero_id}/ticks/{tick}/llm-call")
def tick_llm_call(
    db: Annotated[Session, Depends(get_db)],
    hero_id: str,
    tick: int,
    owner_token: Annotated[str | None, Depends(optional_owner_token)] = None,
) -> dict[str, Any]:
    hid = _hero_id_or_404(db, hero_id)
    try:
        return service.tick_llm_call(db, hid, tick, owner_token=owner_token)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{hero_id}/llm-call/latest")
def latest_llm_call(
    db: Annotated[Session, Depends(get_db)],
    hero_id: str,
    owner_token: Annotated[str | None, Depends(optional_owner_token)] = None,
) -> dict[str, Any]:
    hid = _hero_id_or_404(db, hero_id)
    return service.latest_llm_call(db, hid, owner_token=owner_token)
