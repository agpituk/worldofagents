from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Item


class ItemService:
    @staticmethod
    def in_inventory(db: Session, hero_id: uuid.UUID) -> list[Item]:
        return list(db.scalars(select(Item).where(Item.owner_hero_id == hero_id)))

    @staticmethod
    def on_ground_in(db: Session, zone: str) -> list[Item]:
        return list(
            db.scalars(
                select(Item).where(Item.zone == zone, Item.owner_hero_id.is_(None))
            )
        )

    @staticmethod
    def at_tile(db: Session, zone: str, x: int, y: int) -> list[Item]:
        return list(
            db.scalars(
                select(Item).where(
                    Item.zone == zone,
                    Item.pos_x == x,
                    Item.pos_y == y,
                    Item.owner_hero_id.is_(None),
                )
            )
        )
