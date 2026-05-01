from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.npc.service import NPCService

router = APIRouter(prefix="/npcs", tags=["npcs"])


class NPCOut(BaseModel):
    slug: str
    name: str
    kind: str
    zone: str
    pos: list[int]
    description: str


@router.get("", response_model=list[NPCOut])
def list_npcs(zone: str | None = None, db: Annotated[Session, Depends(get_db)] = None):
    if zone:
        rows = NPCService.list_in_zone(db, zone)
    else:
        from sqlalchemy import select
        from app.core.models import NPC
        rows = list(db.scalars(select(NPC).order_by(NPC.slug)))
    return [
        NPCOut(slug=n.slug, name=n.name, kind=n.kind, zone=n.zone, pos=[n.pos_x, n.pos_y], description=n.description)
        for n in rows
    ]


@router.get("/{slug}", response_model=NPCOut)
def get_npc(slug: str, db: Annotated[Session, Depends(get_db)]):
    n = NPCService.get(db, slug)
    if n is None:
        raise HTTPException(404, "npc not found")
    return NPCOut(
        slug=n.slug, name=n.name, kind=n.kind, zone=n.zone, pos=[n.pos_x, n.pos_y], description=n.description
    )
