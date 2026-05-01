"""Stress-test for FIX_PLAN P0-2 done-when: a hero in a zone with 100 NPCs
and 100 inventory items produces a perception payload whose lengths are
deterministic and bounded by their WIS-derived caps.

Uses a SQLite in-memory engine — the schema's Postgres UUID columns
serialise as strings under SQLite, which is enough for these read-side
checks (no concurrent writers, no Postgres-specific operators)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.actions import perception_for
from app.core.database import Base
from app.core.hero_budgets import perception_budget
from app.core.models import NPC, Hero, Item, Zone


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _seed_hero(
    db: Session, *, wis: int, name: str = "test-hero", int_: int = 25
) -> Hero:
    """Seed a test hero. Default INT=25 ensures the perception_for token
    ceiling (P0-2 step 3) is generous enough to keep the WIS-cap list
    contents intact during these stress tests — otherwise high-WIS
    heroes get trimmed back to nothing under heavy-content floods."""
    if db.get(Zone, "market_square") is None:
        db.add(Zone(slug="market_square", name="Market", kind="sanctuary",
                    width=20, height=20, capacity_soft=40, description="", connections=[]))
    h = Hero(
        id=uuid.uuid4(), name=name, author="t", division="featherweight",
        bio="", str_=10, dex=10, con=10, int_=int_, wis=wis, cha=10,
        hp=30, status="alive", zone="market_square", pos_x=5, pos_y=5,
        manifest={}, memory={}, skills={}, equipped={},
        mana_max=10, mana_current=10, known_spells=[],
        faction_rep={}, auth_token=f"tok-{name}", born_at_tick=0,
    )
    db.add(h)
    db.flush()
    return h


def _flood_npcs(db: Session, count: int) -> None:
    """Pack the zone with NPCs all within the largest plausible look_radius
    so visibility, not range, is what bounds the list."""
    for i in range(count):
        db.add(NPC(
            slug=f"flood_{i:03d}", name=f"Flooder {i}", kind="mob",
            zone="market_square", pos_x=5 + (i % 5), pos_y=5 + ((i // 5) % 5),
            description="", merchant_stock=[], tameable=False, tamed_by_hero_id=None,
            quest_offered=None, llm_persona=None, factions_aligned={},
            hostility="hostile" if i % 3 == 0 else "peaceful",
            alive=True, hp_max=10, hp_current=10, ac=10, attack_bonus=0,
            damage_dice="1d4", loot_gold=0,
        ))
    db.flush()


def _flood_inventory(db: Session, hero: Hero, count: int) -> None:
    for i in range(count):
        db.add(Item(
            id=uuid.uuid4(), slug=f"junk_{i:03d}", name=f"Junk {i}",
            kind="material", description="", props={},
            owner_hero_id=hero.id, zone=None, pos_x=None, pos_y=None,
            quantity=1, stash_owner_hero_id=None,
        ))
    db.flush()


# ---- the headline P0-2 done-when test --------------------------------------


@pytest.mark.parametrize("wis", [5, 10, 25])
def test_perception_bounded_under_100_npcs_and_100_items(db: Session, wis: int):
    """The headline FIX_PLAN P0-2 done-when: at any WIS, perception_for
    returns lists capped by perception_budget(hero) — no leakage."""
    hero = _seed_hero(db, wis=wis)
    _flood_npcs(db, count=100)
    _flood_inventory(db, hero, count=100)

    p = perception_for(db, hero)
    budget = perception_budget(hero)

    # Every WIS-bounded list is at-or-under its cap. The 100 floods make
    # the truncation visible; without sort+cap these would all be 100.
    assert len(p["visible_npcs"]) <= budget.max_visible_npcs
    assert len(p["inventory"]) <= budget.max_inventory
    # No floods of heroes or memory tags here, but the keys must exist
    # so the perception shape stays stable across WIS.
    assert "visible_heroes" in p
    assert "memory_tags" in p


def test_high_wis_sees_more_than_low_wis(db: Session):
    """Sage vs fool: identical zone, identical inventory — but the sage
    must actually see more visible NPCs. This is the spirit-check
    FIX_PLAN cared about most: the stat must matter in the prompt.

    Uses a moderate NPC flood (12, between the two WIS caps) so the
    invariant rests on WIS caps. INT is the same for both heroes so
    the P0-2-step-3 token ceiling treats them symmetrically.
    """
    fool = _seed_hero(db, wis=5, name="fool")
    _flood_npcs(db, count=12)         # > fool's WIS 5 cap (6), < sage's WIS 25 cap (16)
    fool_perception = perception_for(db, fool)

    sage = _seed_hero(db, wis=25, name="sage")
    sage_perception = perception_for(db, sage)

    assert len(sage_perception["visible_npcs"]) > len(fool_perception["visible_npcs"]), (
        f"sage saw {len(sage_perception['visible_npcs'])} NPCs, "
        f"fool saw {len(fool_perception['visible_npcs'])}"
    )


def test_perception_is_deterministic(db: Session):
    """Two calls back-to-back with no state changes return the same lists
    in the same order. Deterministic perception is necessary for replays."""
    hero = _seed_hero(db, wis=10)
    _flood_npcs(db, count=100)

    a = perception_for(db, hero)
    b = perception_for(db, hero)
    assert a["visible_npcs"] == b["visible_npcs"]


def test_npcs_truncated_by_relevance_not_random(db: Session):
    """Hostile NPCs must beat peaceful ones for a slot in the budget —
    a low-WIS hero in a flood of mixed hostility still sees the threats."""
    hero = _seed_hero(db, wis=5)
    _flood_npcs(db, count=100)

    p = perception_for(db, hero)
    visible = p["visible_npcs"]
    # 1/3 of the 100 floods are hostile (i % 3 == 0). Within visible range
    # there are at most ~25 NPCs (5x5 packed grid), of which ~9 are hostile.
    # Truncation should preserve hostiles ahead of peaceful ones.
    hostile_visible = sum(1 for n in visible if n["hostility"] == "hostile")
    peaceful_visible = sum(1 for n in visible if n["hostility"] == "peaceful")
    if hostile_visible + peaceful_visible == len(visible):
        # All-hostile NPCs sit before any peaceful one in the result.
        first_peaceful = next(
            (idx for idx, n in enumerate(visible) if n["hostility"] == "peaceful"),
            len(visible),
        )
        last_hostile = max(
            (idx for idx, n in enumerate(visible) if n["hostility"] == "hostile"),
            default=-1,
        )
        assert last_hostile < first_peaceful, (
            "hostile NPCs should sort before peaceful ones in perception"
        )
