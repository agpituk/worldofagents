"""The Wyrm of the Sundering — the world's calendar event.

Every `WYRM_SPAWN_INTERVAL_TICKS`, a wyrm spawns in a random frontier zone.
It lives for at most `WYRM_LIFETIME_TICKS`. While alive, every spectator on
the home page sees a countdown banner; every hero in the zone gets a chance
at the kill. The killer is awarded a `dragon_scale` item — the only way to
obtain one.

Implementation notes:
  • Single global instance. Slug is the constant `WYRM_SLUG`. Spawn/despawn
    flips the existing NPC row's `alive` and `zone`/`pos`. No new rows.
  • Schedule lives in `tick_wyrm`, called once per tick from the engine.
    State is derived from the NPC row + Event log so it survives restarts.
  • No new table. The `world.wyrm.spawned` Event records the timestamp and
    the rolled zone; subsequent ticks check elapsed time off it.
"""

from __future__ import annotations

import logging
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Event, NPC, Zone

log = logging.getLogger("world.wyrm")


WYRM_SLUG = "wyrm_of_the_sundering"
WYRM_SPAWN_INTERVAL_TICKS = 1500   # ~150 minutes at 6s/tick
WYRM_LIFETIME_TICKS = 600          # ~60 minutes
FRONTIER_ZONES = ("lantern_road", "hush_wood")


def _ensure_wyrm_npc(db: Session) -> NPC:
    """Idempotently ensure the wyrm NPC row exists. Defaults to a despawned
    state — alive=False — until the schedule wakes it up."""
    existing = db.get(NPC, WYRM_SLUG)
    if existing is not None:
        return existing
    wyrm = NPC(
        slug=WYRM_SLUG,
        name="Wyrm of the Sundering",
        kind="mob",
        zone=FRONTIER_ZONES[0],
        pos_x=5,
        pos_y=5,
        description=(
            "An ancient thing of scale and breath, woken by the world's "
            "drift. It does not stay long. Bring blades, or stay home."
        ),
        merchant_stock=[],
        tameable=False,
        quest_offered=None,
        llm_persona=None,
        factions_aligned={"embered": 5},
        hostility="hostile",
        alive=False,
        hp_max=80,
        hp_current=80,
        ac=15,
        attack_bonus=4,
        damage_dice="2d6",
        loot_gold=300,
    )
    db.add(wyrm)
    db.flush()
    return wyrm


def _last_spawn_tick(db: Session) -> int | None:
    ev = db.scalar(
        select(Event)
        .where(Event.kind == "world.wyrm.spawned")
        .order_by(Event.id.desc())
        .limit(1)
    )
    return int(ev.tick_id) if ev else None


def tick_wyrm(db: Session, current_tick: int) -> None:
    """Schedule entry point — called from the tick engine each tick.
    Cheap path: a few indexed queries on Event + a single NPC fetch."""
    wyrm = _ensure_wyrm_npc(db)
    last_spawn = _last_spawn_tick(db)

    # Despawn pass: alive but lifetime expired → kill it (counts as escape).
    if wyrm.alive and last_spawn is not None and current_tick - last_spawn >= WYRM_LIFETIME_TICKS:
        wyrm.alive = False
        wyrm.hp_current = 0
        db.add(Event(
            tick_id=current_tick, hero_id=None, zone=wyrm.zone,
            kind="world.wyrm.expired",
            payload={"slug": WYRM_SLUG, "spawned_at_tick": last_spawn, "result": "escaped"},
        ))
        log.info("wyrm escaped after %d ticks in %s", current_tick - last_spawn, wyrm.zone)
        return

    # Spawn pass: dead and the cooldown has passed (or never spawned).
    if not wyrm.alive:
        cooled_down = last_spawn is None or (current_tick - last_spawn) >= WYRM_SPAWN_INTERVAL_TICKS
        if not cooled_down:
            return
        valid_zones = list(
            db.scalars(select(Zone).where(Zone.slug.in_(FRONTIER_ZONES)))
        )
        if not valid_zones:
            return
        zone = random.choice(valid_zones)
        wyrm.zone = zone.slug
        wyrm.pos_x = max(1, min(zone.width - 2, random.randint(2, max(2, zone.width - 3))))
        wyrm.pos_y = max(1, min(zone.height - 2, random.randint(2, max(2, zone.height - 3))))
        wyrm.alive = True
        wyrm.hp_current = wyrm.hp_max
        db.add(Event(
            tick_id=current_tick, hero_id=None, zone=wyrm.zone,
            kind="world.wyrm.spawned",
            payload={"slug": WYRM_SLUG, "zone": wyrm.zone, "lifetime": WYRM_LIFETIME_TICKS,
                     "pos": [wyrm.pos_x, wyrm.pos_y]},
        ))
        log.info("wyrm spawned in %s at [%d,%d]", wyrm.zone, wyrm.pos_x, wyrm.pos_y)


def current_wyrm_status(db: Session, current_tick: int) -> dict:
    """Read-only — used by /events/current for the home page banner."""
    wyrm = db.get(NPC, WYRM_SLUG)
    last_spawn = _last_spawn_tick(db)
    if wyrm is None or not wyrm.alive:
        next_spawn_at = (last_spawn or 0) + WYRM_SPAWN_INTERVAL_TICKS
        return {
            "active": False,
            "next_spawn_at_tick": next_spawn_at,
            "ticks_until_next": max(0, next_spawn_at - current_tick),
        }
    return {
        "active": True,
        "slug": WYRM_SLUG,
        "name": wyrm.name,
        "zone": wyrm.zone,
        "pos": [wyrm.pos_x, wyrm.pos_y],
        "hp": wyrm.hp_current,
        "hp_max": wyrm.hp_max,
        "spawned_at_tick": last_spawn,
        "expires_at_tick": (last_spawn or current_tick) + WYRM_LIFETIME_TICKS,
        "ticks_remaining": max(0, ((last_spawn or current_tick) + WYRM_LIFETIME_TICKS) - current_tick),
    }
