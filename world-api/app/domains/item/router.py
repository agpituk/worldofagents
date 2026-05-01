from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.item.service import ItemService

router = APIRouter(prefix="/items", tags=["items"])


class ItemOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    kind: str
    description: str
    owner_hero_id: uuid.UUID | None
    zone: str | None
    pos: list[int] | None


def _serialise(i) -> ItemOut:
    return ItemOut(
        id=i.id,
        slug=i.slug,
        name=i.name,
        kind=i.kind,
        description=i.description,
        owner_hero_id=i.owner_hero_id,
        zone=i.zone,
        pos=[i.pos_x, i.pos_y] if i.pos_x is not None and i.pos_y is not None else None,
    )


@router.get("/inventory/{hero_id}", response_model=list[ItemOut])
def hero_inventory(hero_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]):
    return [_serialise(i) for i in ItemService.in_inventory(db, hero_id)]


@router.get("/in-zone/{zone}", response_model=list[ItemOut])
def items_in_zone(zone: str, db: Annotated[Session, Depends(get_db)]):
    return [_serialise(i) for i in ItemService.on_ground_in(db, zone)]
