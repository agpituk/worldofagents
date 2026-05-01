from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Hero, Zone


class ZoneService:
    @staticmethod
    def list_all(db: Session) -> list[Zone]:
        return list(db.scalars(select(Zone).order_by(Zone.slug)))

    @staticmethod
    def get(db: Session, slug: str) -> Zone | None:
        return db.get(Zone, slug)

    @staticmethod
    def occupants(db: Session, slug: str) -> list[Hero]:
        return list(
            db.scalars(
                select(Hero).where(Hero.zone == slug, Hero.status == "alive").order_by(Hero.name)
            )
        )
