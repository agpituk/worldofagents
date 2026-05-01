"""Mob retaliation phase. Runs after hero actions each tick.

Each alive hostile NPC scans for adjacent (radius 1) alive heroes in the same
zone and attacks one if any are present. Damage applied, hero death tracked.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actions import _current_tick, defending_this_tick
from app.core.dice import d20, roll
from app.core.models import Hero, NPC


def _step_pet_toward_owner(pet: NPC, owner: Hero) -> None:
    """One-tile move toward owner. Pets stick close so they're useful in combat."""
    if pet.zone != owner.zone:
        # Snap to owner's zone if separated (simple v0.7 behavior).
        pet.zone = owner.zone
        pet.pos_x = owner.pos_x
        pet.pos_y = owner.pos_y
        return
    dist = abs(pet.pos_x - owner.pos_x) + abs(pet.pos_y - owner.pos_y)
    if dist <= 1:
        return
    if abs(owner.pos_x - pet.pos_x) >= abs(owner.pos_y - pet.pos_y):
        pet.pos_x += 1 if owner.pos_x > pet.pos_x else -1
    else:
        pet.pos_y += 1 if owner.pos_y > pet.pos_y else -1


def _run_pet_phase(db: Session, payloads: list[dict[str, Any]]) -> None:
    """Tamed pets: move toward owner; if a hostile is adjacent, swing at it."""
    pets = list(
        db.scalars(select(NPC).where(NPC.hostility == "tamed", NPC.alive.is_(True), NPC.tamed_by_hero_id.isnot(None)))
    )
    for pet in pets:
        owner = db.get(Hero, pet.tamed_by_hero_id)
        if owner is None or owner.status != "alive":
            continue
        # Pets attack hostiles before moving (they don't run away from a fight).
        nearby_hostiles = list(
            db.scalars(
                select(NPC).where(
                    NPC.zone == pet.zone, NPC.hostility == "hostile", NPC.alive.is_(True)
                )
            )
        )
        adj = [m for m in nearby_hostiles if abs(m.pos_x - pet.pos_x) + abs(m.pos_y - pet.pos_y) <= 1]
        if adj:
            target = adj[0]
            attack_roll = d20()
            attack_total = attack_roll + max(0, pet.attack_bonus)
            if attack_total >= target.ac or attack_roll == 20:
                damage = roll(pet.damage_dice or "1d2")
                target.hp_current = max(0, target.hp_current - damage)
                died = target.hp_current <= 0
                if died:
                    target.alive = False
                payloads.append({
                    "pet": pet.slug, "owner_id": str(owner.id), "target_mob": target.slug,
                    "hit": True, "damage": damage, "died": died,
                })
                continue
            payloads.append({"pet": pet.slug, "target_mob": target.slug, "hit": False})
            continue
        _step_pet_toward_owner(pet, owner)


def run_mob_phase(db: Session) -> list[dict[str, Any]]:
    """Returns a list of mob-action event payloads (one per attack made)."""
    payloads: list[dict[str, Any]] = []
    _run_pet_phase(db, payloads)

    mobs = list(db.scalars(select(NPC).where(NPC.hostility == "hostile", NPC.alive.is_(True))))
    for mob in mobs:
        targets = list(
            db.scalars(
                select(Hero).where(Hero.zone == mob.zone, Hero.status == "alive")
            )
        )
        adjacent = [
            h for h in targets if abs(h.pos_x - mob.pos_x) + abs(h.pos_y - mob.pos_y) <= 1
        ]
        if not adjacent:
            continue
        # Pick the lowest-HP adjacent hero (mobs gang up on the wounded).
        target = min(adjacent, key=lambda h: h.hp)

        attack_roll = d20()
        attack_total = attack_roll + mob.attack_bonus
        crit = attack_roll == 20
        fumble = attack_roll == 1
        defending = str(target.id) in defending_this_tick
        ac = (20 + target.dex // 4) if defending else (10 + target.dex // 4)

        if fumble:
            payloads.append({
                "mob": mob.slug, "target_hero_id": str(target.id), "target_name": target.name,
                "roll": attack_roll, "total": attack_total, "ac": ac,
                "hit": False, "fumble": True, "damage": 0,
            })
            continue

        hit = crit or attack_total >= ac
        if not hit:
            payloads.append({
                "mob": mob.slug, "target_hero_id": str(target.id), "target_name": target.name,
                "roll": attack_roll, "total": attack_total, "ac": ac,
                "hit": False, "fumble": False, "damage": 0, "defending": defending,
            })
            continue

        damage = roll(mob.damage_dice or "1d1")
        if crit:
            damage *= 2
        target.hp = max(0, target.hp - damage)
        died = target.hp <= 0
        if died:
            target.status = "dead"
            target.died_at_tick = _current_tick(db)

        payloads.append({
            "mob": mob.slug, "target_hero_id": str(target.id), "target_name": target.name,
            "roll": attack_roll, "total": attack_total, "ac": ac,
            "hit": True, "crit": crit, "fumble": False,
            "damage": damage, "target_hp_remaining": target.hp,
            "died": died, "defending": defending,
        })

    return payloads
