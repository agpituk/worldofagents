from __future__ import annotations

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.core.database import get_db
from app.core.narrator import narrate
from app.core.tick import tick_engine
from app.domains.npc.service import NPCService
from app.domains.zone.service import ZoneService

router = APIRouter(prefix="/zones", tags=["zones"])


class ZoneOut(BaseModel):
    slug: str
    name: str
    kind: str
    width: int
    height: int
    capacity_soft: int
    description: str
    connections: list[str] = []


class OccupantOut(BaseModel):
    id: str
    name: str
    pos: list[int]
    hp: int
    status: str
    # Visual richness: leading faction colors the glyph; division sizes it;
    # ticks_alive draws a gold ring on >1d-old heroes; has_active_quest
    # adds a corner indicator. All derived from already-loaded Hero rows.
    division: str = "featherweight"
    leading_faction: str | None = None
    born_at_tick: int = 0
    ticks_alive: int = 0
    has_active_quest: bool = False


class ZoneNPCOut(BaseModel):
    slug: str
    name: str
    kind: str
    pos: list[int]
    hostility: str
    alive: bool
    hp: int
    hp_max: int
    merchant_stock: list[dict] = []


class BuildingOut(BaseModel):
    slug: str
    name: str
    pos: list[int]
    width: int
    height: int
    kind: str
    owner_hero_id: str | None
    gold_cost: int


class ResourceOut(BaseModel):
    slug: str
    name: str
    kind: str
    pos: list[int]
    yield_item_slug: str
    depleted_until_tick: int | None


class ZoneDetailOut(ZoneOut):
    occupants: list[OccupantOut]
    npcs: list[ZoneNPCOut] = []
    buildings: list[BuildingOut] = []
    resource_nodes: list[ResourceOut] = []


@router.get("", response_model=list[ZoneOut])
def list_zones(db: Annotated[Session, Depends(get_db)]):
    rows = ZoneService.list_all(db)
    return [
        ZoneOut(
            slug=z.slug, name=z.name, kind=z.kind, width=z.width, height=z.height,
            capacity_soft=z.capacity_soft, description=z.description,
            connections=z.connections or [],
        )
        for z in rows
    ]


@router.get("/{slug}", response_model=ZoneDetailOut)
def get_zone(slug: str, db: Annotated[Session, Depends(get_db)]):
    z = ZoneService.get(db, slug)
    if z is None:
        raise HTTPException(404, "zone not found")
    from sqlalchemy import func as _func
    from app.core.models import Quest, Tick
    current_tick = int(db.scalar(__import__("sqlalchemy", fromlist=["select"]).select(_func.max(Tick.id))) or 0)
    occupant_rows = list(ZoneService.occupants(db, slug))
    occupants = []
    for h in occupant_rows:
        rep = h.faction_rep or {}
        leading = max(rep, key=lambda k: rep.get(k, 0)) if rep and any(v > 0 for v in rep.values()) else None
        from sqlalchemy import select as _sel
        active_quest = db.scalar(
            _sel(Quest.id).where(Quest.hero_id == h.id, Quest.status == "active").limit(1)
        )
        born = int(h.born_at_tick or 0)
        end_tick = h.died_at_tick if h.died_at_tick is not None else current_tick
        occupants.append(
            OccupantOut(
                id=str(h.id), name=h.name, pos=[h.pos_x, h.pos_y], hp=h.hp, status=h.status,
                division=h.division, leading_faction=leading,
                born_at_tick=born, ticks_alive=max(0, int(end_tick) - born),
                has_active_quest=active_quest is not None,
            )
        )
    npcs = [
        ZoneNPCOut(
            slug=n.slug, name=n.name, kind=n.kind, pos=[n.pos_x, n.pos_y],
            hostility=n.hostility, alive=bool(n.alive), hp=n.hp_current, hp_max=n.hp_max,
            merchant_stock=list(n.merchant_stock or []),
        )
        for n in NPCService.list_in_zone(db, slug)
    ]
    from sqlalchemy import select
    from app.core.models import Building, ResourceNode
    buildings = list(db.scalars(select(Building).where(Building.zone == slug)))
    nodes = list(db.scalars(select(ResourceNode).where(ResourceNode.zone == slug)))

    return ZoneDetailOut(
        slug=z.slug, name=z.name, kind=z.kind, width=z.width, height=z.height,
        capacity_soft=z.capacity_soft, description=z.description,
        connections=z.connections or [],
        occupants=occupants, npcs=npcs,
        buildings=[
            BuildingOut(
                slug=b.slug, name=b.name, pos=[b.pos_x, b.pos_y],
                width=b.width, height=b.height, kind=b.kind,
                owner_hero_id=str(b.owner_hero_id) if b.owner_hero_id else None,
                gold_cost=b.gold_cost,
            )
            for b in buildings
        ],
        resource_nodes=[
            ResourceOut(
                slug=n.slug, name=n.name, kind=n.kind, pos=[n.pos_x, n.pos_y],
                yield_item_slug=n.yield_item_slug,
                depleted_until_tick=n.depleted_until_tick,
            )
            for n in nodes
        ],
    )


@router.get("/{slug}/stream")
async def stream_zone(slug: str, db: Annotated[Session, Depends(get_db)]):
    """Server-Sent Events stream of all events occurring in this zone.

    Open with `curl -N http://localhost:47800/zones/<slug>/stream` to watch
    activity in real time. The frontend will consume the same protocol.
    """
    z = ZoneService.get(db, slug)
    if z is None:
        raise HTTPException(404, "zone not found")

    queue = tick_engine.subscribe_zone(slug)

    async def event_generator():
        yield {"event": "hello", "data": json.dumps({"zone": slug, "name": z.name})}
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield {"event": "tick", "data": json.dumps(payload)}
                    line = narrate(payload)
                    if line:
                        yield {
                            "event": "narrator",
                            "data": json.dumps({"tick_id": payload.get("tick_id"), "text": line}),
                        }
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            tick_engine.unsubscribe_zone(slug, queue)

    return EventSourceResponse(event_generator())
