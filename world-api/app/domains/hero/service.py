from __future__ import annotations

import secrets
import uuid

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Hero, Tick
from app.domains.hero.schemas import HeroManifest


class HeroService:
    @staticmethod
    def parse_manifest(raw: bytes | str) -> HeroManifest:
        """Parse a YAML or JSON manifest into a HeroManifest. Raises if invalid."""
        data = yaml.safe_load(raw) if isinstance(raw, (bytes, str)) else raw
        if not isinstance(data, dict):
            raise ValueError("manifest must be a mapping")

        # Manifests can be wrapped in a top-level `hero:` block (as in DESIGN.md §7),
        # or be flat. Accept both.
        if "hero" in data and isinstance(data["hero"], dict) and "name" not in data:
            inner = data["hero"]
        else:
            inner = data

        # Capture extras (everything beyond the strict schema fields)
        known = {"name", "author", "division", "bio", "build"}
        extras = {k: v for k, v in inner.items() if k not in known}
        payload = {k: v for k, v in inner.items() if k in known}
        payload["extras"] = extras

        return HeroManifest.model_validate(payload)

    @staticmethod
    def register(db: Session, manifest: HeroManifest, *, managed: bool = False) -> Hero:
        existing = db.scalar(select(Hero).where(Hero.name == manifest.name))
        if existing is not None:
            raise ValueError(f"hero name '{manifest.name}' already taken")

        hp = 20 + manifest.build.con
        mana_max = max(1, 5 + manifest.build.int_ * 2)
        # Initialise mutable memory from manifest.memory.initial (if provided).
        # Also pull two structured slots that influence how the hero remembers
        # things during play:
        #   - recall_tags: tags the retriever biases toward when building the
        #     `journal_relevant` slice in perception. The hero's "what matters
        #     to me" filter on long-term memory.
        #   - system_summary: durable persona context the runner injects into
        #     every LLM prompt. Survives across reflexes / model swaps / crashes.
        memory_init: dict = {}
        memory_block = manifest.extras.get("memory") or {}
        if isinstance(memory_block, dict):
            initial = memory_block.get("initial")
            if isinstance(initial, dict):
                memory_init = dict(initial)
            recall_tags = memory_block.get("recall_tags")
            if isinstance(recall_tags, list):
                memory_init["recall_tags"] = [str(t)[:32] for t in recall_tags][:16]
            system_summary = memory_block.get("system_summary")
            if isinstance(system_summary, str) and system_summary.strip():
                memory_init["system_summary"] = system_summary.strip()[:600]
        memory_init.setdefault("npcs", {})

        # Stamp birth tick — the lifespan counter starts ticking now.
        from sqlalchemy import func as _func
        born_at = int(db.scalar(select(_func.max(Tick.id))) or 0)
        hero = Hero(
            id=uuid.uuid4(),
            name=manifest.name,
            author=manifest.author,
            division=manifest.division,
            bio=manifest.bio,
            born_at_tick=born_at,
            str_=manifest.build.str_,
            dex=manifest.build.dex,
            con=manifest.build.con,
            int_=manifest.build.int_,
            wis=manifest.build.wis,
            cha=manifest.build.cha,
            hp=hp,
            status="alive",
            zone="market_square",
            pos_x=5,
            pos_y=5,
            mana_max=mana_max,
            mana_current=mana_max,
            known_spells=[],
            skills={},
            equipped={},
            manifest=manifest.model_dump(by_alias=True),
            memory=memory_init,
            auth_token=secrets.token_urlsafe(32),
            managed=managed,
        )
        db.add(hero)
        db.flush()  # need hero.id assigned before granting the starter quest

        # Plant the starter arc — every new hero begins with step 1 of the
        # Warden's Recruit chain. This is the difference between "spawned"
        # and "summoned": the world hands them a reason on Day 1.
        from app.domains.quest.main_quest import auto_grant_first_quest
        auto_grant_first_quest(db, hero)

        db.commit()
        db.refresh(hero)
        return hero

    @staticmethod
    def get_by_id(db: Session, hero_id: uuid.UUID) -> Hero | None:
        return db.get(Hero, hero_id)

    @staticmethod
    def get_by_auth_token(db: Session, token: str) -> Hero | None:
        return db.scalar(select(Hero).where(Hero.auth_token == token))

    @staticmethod
    def list_all(db: Session) -> list[Hero]:
        return list(db.scalars(select(Hero).order_by(Hero.created_at.desc())))
