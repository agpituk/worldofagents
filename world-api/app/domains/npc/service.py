from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import NPC


class NPCService:
    @staticmethod
    def list_in_zone(db: Session, zone: str) -> list[NPC]:
        return list(db.scalars(select(NPC).where(NPC.zone == zone).order_by(NPC.slug)))

    @staticmethod
    def get(db: Session, slug: str) -> NPC | None:
        return db.get(NPC, slug)

    @staticmethod
    def adjacent_to(db: Session, zone: str, x: int, y: int, radius: int = 1) -> list[NPC]:
        npcs = NPCService.list_in_zone(db, zone)
        return [n for n in npcs if abs(n.pos_x - x) + abs(n.pos_y - y) <= radius]
