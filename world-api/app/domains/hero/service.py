"""Hero domain service.

The router is a thin HTTP adapter; everything else — registration,
manifest parsing, leaderboards, death-page assembly, perception — lives
here. Cross-domain reads (Quest, JournalEntry, Event) stay inside this
service because they're hero-centric assemblies; the alternative
(calling QuestService / EventService for hero-scoped reads) would be
heavier than the read justifies.
"""

from __future__ import annotations

import secrets
import uuid
from typing import Any

import yaml
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.models import Event, Hero, JournalEntry, Quest, QuestTemplate, Tick
from app.domains.hero.schemas import HeroManifest


class HeroService:
    # ---------------------------------------------------------------------
    # Manifest + registration
    # ---------------------------------------------------------------------

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
        born_at = int(db.scalar(select(func.max(Tick.id))) or 0)

        # Phase 8 — sandbox tutorial. New heroes spawn in `sandbox`
        # under a 50-tick safety net unless their manifest opts out.
        # `extras.skip_sandbox: true` skips the tutorial and lands them
        # at market_square at full risk — for advanced authors who don't
        # want the protected window.
        skip_sandbox = bool(manifest.extras.get("skip_sandbox"))
        sandbox_protection_ticks = int(manifest.extras.get("sandbox_ticks", 50) or 50)
        if skip_sandbox:
            spawn_zone = "market_square"
            protected_until_tick = 0
        else:
            spawn_zone = "sandbox"
            protected_until_tick = born_at + max(0, sandbox_protection_ticks)

        hero = Hero(
            id=uuid.uuid4(),
            name=manifest.name,
            author=manifest.author,
            division=manifest.division,
            bio=manifest.bio,
            born_at_tick=born_at,
            protected_until_tick=protected_until_tick,
            str_=manifest.build.str_,
            dex=manifest.build.dex,
            con=manifest.build.con,
            int_=manifest.build.int_,
            wis=manifest.build.wis,
            cha=manifest.build.cha,
            hp=hp,
            status="alive",
            zone=spawn_zone,
            pos_x=4,
            pos_y=4,
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
    def respawn(
        db: Session,
        manifest: HeroManifest,
        *,
        new_name: str,
    ) -> Hero:
        """Respawn after permadeath. Validates the previous hero of the
        same name is dead, then registers a new hero with the supplied
        new name and the same build."""
        original = db.scalar(select(Hero).where(Hero.name == manifest.name))
        if original is None:
            raise LookupError(f"no prior hero named '{manifest.name}' to respawn from")
        if original.status != "dead":
            raise ValueError(f"hero '{manifest.name}' is still alive — cannot respawn")
        if not new_name:
            raise ValueError("new_name required for respawn")

        parsed_dict = manifest.model_dump(by_alias=True)
        parsed_dict["name"] = new_name
        parsed_v2 = manifest.__class__.model_validate(parsed_dict)
        return HeroService.register(db, parsed_v2)

    # ---------------------------------------------------------------------
    # Reads
    # ---------------------------------------------------------------------

    @staticmethod
    def get_by_id(db: Session, hero_id: uuid.UUID) -> Hero | None:
        return db.get(Hero, hero_id)

    @staticmethod
    def get_by_name(db: Session, name: str) -> Hero | None:
        return db.scalar(select(Hero).where(Hero.name == name))

    @staticmethod
    def get_by_auth_token(db: Session, token: str) -> Hero | None:
        return db.scalar(select(Hero).where(Hero.auth_token == token))

    @staticmethod
    def list_all(db: Session) -> list[Hero]:
        return list(db.scalars(select(Hero).order_by(Hero.created_at.desc())))

    @staticmethod
    def list_alive(db: Session) -> list[Hero]:
        return list(db.scalars(select(Hero).where(Hero.status == "alive")))

    @staticmethod
    def list_dead_by_lifespan(db: Session, limit: int) -> list[Hero]:
        return list(db.scalars(
            select(Hero)
            .where(Hero.status == "dead")
            .order_by(desc(Hero.died_at_tick - Hero.born_at_tick))
            .limit(limit)
        ))

    @staticmethod
    def current_tick(db: Session) -> int:
        return int(db.scalar(select(func.max(Tick.id))) or 0)

    # ---------------------------------------------------------------------
    # Composite reads
    # ---------------------------------------------------------------------

    @staticmethod
    def longevity(db: Session, limit: int) -> dict[str, Any]:
        """Two leaderboards in one payload — `alive` (current streaks,
        sorted by ticks_alive desc) and `hall_of_fame` (dead heroes,
        sorted by ticks they survived). Headline metric of the game."""
        current = HeroService.current_tick(db)
        alive_rows = HeroService.list_alive(db)
        dead_rows = HeroService.list_dead_by_lifespan(db, limit)

        def _row(h: Hero, end_tick: int) -> dict[str, Any]:
            return {
                "id": str(h.id),
                "name": h.name,
                "author": h.author,
                "division": h.division,
                "zone": h.zone,
                "born_at_tick": int(h.born_at_tick or 0),
                "died_at_tick": h.died_at_tick,
                "ticks_alive": max(0, int(end_tick) - int(h.born_at_tick or 0)),
            }

        alive = [_row(h, current) for h in alive_rows]
        alive.sort(key=lambda r: -r["ticks_alive"])
        return {
            "current_tick": current,
            "alive": alive[:limit],
            "hall_of_fame": [_row(h, h.died_at_tick or current) for h in dead_rows],
        }

    @staticmethod
    def skill_leaderboards(db: Session, top: int) -> dict[str, Any]:
        """Per-skill top-N heroes by XP, plus their rendered title rank.

        Phase 5 of the build-diversity roadmap: identity surface for the
        "GM Fisherman" / "Expert Smith" world. Computes once across all
        skills the world knows about — both currently-grindable
        (mining / smithing / fishing / …) and combat (melee / magic /
        stealth) — so a hero who never swings a sword still has a board
        to appear on. Heroes with no XP in a skill are omitted from
        that skill's board."""
        from app.core.actions import _SKILL_TITLE_NOUN, _skill_rank, top_title_for

        rows = HeroService.list_all(db)
        boards: dict[str, list[dict[str, Any]]] = {}
        for skill_name in _SKILL_TITLE_NOUN:
            scored: list[tuple[int, Hero]] = []
            for h in rows:
                xp = int((h.skills or {}).get(skill_name, 0) or 0)
                if xp <= 0:
                    continue
                scored.append((xp, h))
            scored.sort(key=lambda p: -p[0])
            boards[skill_name] = [
                {
                    "id": str(h.id),
                    "name": h.name,
                    "author": h.author,
                    "division": h.division,
                    "status": h.status,
                    "xp": xp,
                    "level": min(100, xp // 10),
                    "rank": _skill_rank(min(100, xp // 10)),
                    "top_title": top_title_for(h.skills),
                }
                for xp, h in scored[:top]
            ]
        return {"top": top, "boards": boards}

    @staticmethod
    def memory_trace(db: Session, hero: Hero) -> dict[str, Any]:
        """The hero's recall surface — what the LLM sees as "memories
        you carry" each tick. Surfaces:
          • `recall_tags`: manifest-declared retrieval bias
          • `journal_relevant`: top-K retriever hits
          • `retriever_name`: which backend served the hits
        Players use this page to debug *why* their hero remembers what
        it does."""
        from app.core.actions import _journal_relevant
        from app.core.retriever import get_retriever
        mem = hero.memory if isinstance(hero.memory, dict) else {}
        return {
            "hero_id": str(hero.id),
            "name": hero.name,
            "recall_tags": list(mem.get("recall_tags") or []),
            "system_summary": mem.get("system_summary"),
            "discovered_recipes": list(mem.get("discovered_recipes") or []),
            "titles": list(mem.get("titles") or []),
            "retriever_name": get_retriever().name,
            "journal_relevant": _journal_relevant(db, hero, n=10),
        }

    @staticmethod
    def perception(db: Session, hero: Hero) -> dict[str, Any]:
        """Phase 8 — dry-run perception. JSON the LLM would see this
        tick. Useful for "why didn't my reflex fire?" debugging. No
        state mutation; safe to poll."""
        from app.core.actions import perception_for
        return perception_for(db, hero)

    @staticmethod
    def quests(db: Session, hero_id: uuid.UUID) -> list[dict[str, Any]]:
        """All quests for a hero, joined with template metadata."""
        rows = list(db.scalars(
            select(Quest)
            .where(Quest.hero_id == hero_id)
            .order_by(Quest.accepted_at.desc())
        ))
        out: list[dict[str, Any]] = []
        for q in rows:
            tpl = db.get(QuestTemplate, q.template_slug)
            if tpl is None:
                continue
            out.append({
                "id": str(q.id),
                "template_slug": q.template_slug,
                "name": tpl.name,
                "description": tpl.description,
                "kind": tpl.kind,
                "target": tpl.target,
                "count_done": q.count_done,
                "count_required": tpl.count_required,
                "status": q.status,
                "reward_gold": tpl.reward_gold,
                "reward_faction": tpl.reward_faction,
                "reward_faction_amount": tpl.reward_faction_amount,
                "offered_by": tpl.offered_by,
            })
        return out

    @staticmethod
    def journal(db: Session, hero_id: uuid.UUID, limit: int) -> list[dict[str, Any]]:
        """The hero's episodic memory — milestone entries (auto) +
        player entries (LLM-curated). Newest last."""
        rows = list(db.scalars(
            select(JournalEntry)
            .where(JournalEntry.hero_id == hero_id)
            .order_by(JournalEntry.id.desc())
            .limit(min(limit, 500))
        ))
        rows.reverse()
        return [
            {
                "id": r.id,
                "tick_id": r.tick_id,
                "kind": r.kind,
                "text": r.text,
                "tags": list(r.tags or []),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    @staticmethod
    def death_page(db: Session, hero: Hero) -> dict[str, Any]:
        """The hero's death page: when, where, killed by, last 30
        thoughts. The viral monument."""
        if hero.status != "dead":
            raise ValueError("hero is alive")

        death_event = db.scalar(
            select(Event)
            .where(Event.hero_id == hero.id, Event.kind == "hero.died")
            .order_by(Event.id.desc())
            .limit(1)
        )
        last_thoughts = list(db.scalars(
            select(Event)
            .where(
                Event.hero_id == hero.id,
                Event.kind.in_(["action.resolved", "npc.reaction"]),
            )
            .order_by(Event.id.desc())
            .limit(30)
        ))

        return {
            "id": str(hero.id),
            "name": hero.name,
            "author": hero.author,
            "division": hero.division,
            "bio": hero.bio,
            "build": {
                "str": hero.str_, "dex": hero.dex, "con": hero.con,
                "int": hero.int_, "wis": hero.wis, "cha": hero.cha,
            },
            "died_at_zone": hero.zone,
            "died_at_pos": [hero.pos_x, hero.pos_y],
            "killer": (death_event.payload or {}).get("killer") if death_event else None,
            "killer_kind": (death_event.payload or {}).get("killer_kind") if death_event else None,
            "killer_id": (death_event.payload or {}).get("killer_id") if death_event else None,
            "looted_gold": (death_event.payload or {}).get("looted_gold", 0) if death_event else 0,
            "final_gold": (hero.memory or {}).get("gold", 0) if isinstance(hero.memory, dict) else 0,
            "born_at_tick": int(hero.born_at_tick or 0),
            "died_at_tick": hero.died_at_tick,
            "ticks_alive": max(0, int(hero.died_at_tick or 0) - int(hero.born_at_tick or 0)),
            "faction_rep": dict(hero.faction_rep or {}),
            "epitaph_thoughts": [
                {"kind": e.kind, "tick_id": e.tick_id, "payload": e.payload}
                for e in last_thoughts
            ],
        }
