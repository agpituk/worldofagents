"""Spellcasting + spell-effect dispatch + scroll learning + taming.

`cast` is the entry point for all magic; the heavy effect-kind dispatch
(apply_status / dispel / blink / push / summon / reveal) lives in
`_resolve_spell_effect` so the dispatcher stays readable. Tame is here
because it's a CHA+WIS-driven roll that lives next to status apply,
and learn is the only way to acquire new spells in-game.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actions._helpers import (
    _consume_from_inventory,
    _current_tick,
    _grant_xp,
    _hero_gold,
    _increment_kills,
    _inventory_stack,
    _journal_milestone,
    _set_hero_gold,
    _skill_level,
)
from app.core.actions._result import ResolutionResult
from app.core.actions.statuses import _apply_status
from app.core.dice import d20, roll
from app.core.models import Hero, NPC, Spell, Status, Zone


def _resolve_spell_effect(
    db: Session, hero: Hero, spell: Spell, action: dict[str, Any],
    target_arg: Any, skill_lvl: int, outcome: dict[str, Any],
) -> ResolutionResult:
    """Phase 2 effect-kind dispatch: apply_status / dispel / move_self /
    move_target / summon_npc / reveal. Uses the spell's `payload` JSON
    for kind-specific tunables. Unknown kinds fall through with an
    error so a misspelled `effect_kind` in the seed is loud, not silent.
    """
    payload = dict(spell.payload or {})
    kind = spell.effect_kind

    def _resolve_target_hero(arg: Any) -> Hero | None:
        if not arg:
            return None
        return db.scalar(select(Hero).where(Hero.name == str(arg)))

    def _check_range(t_pos_x: int, t_pos_y: int) -> bool:
        return abs(t_pos_x - hero.pos_x) + abs(t_pos_y - hero.pos_y) <= spell.range

    if kind == "apply_status":
        slug = str(payload.get("status") or "")
        duration = int(payload.get("duration_ticks") or 10)
        bonus_payload = dict(payload.get("payload") or {})
        if not slug:
            return ResolutionResult(False, {"verb": "cast", "error": "spell missing payload.status"})
        if spell.target_kind == "self":
            target = hero
        elif spell.target_kind == "hero":
            target = _resolve_target_hero(target_arg)
            if target is None or target.zone != hero.zone or target.status != "alive":
                return ResolutionResult(False, {"verb": "cast", "error": "target hero not reachable"})
            if not _check_range(target.pos_x, target.pos_y):
                return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
        elif spell.target_kind == "enemy":
            target = _resolve_target_hero(target_arg)
            if target is None or target.id == hero.id:
                return ResolutionResult(False, {"verb": "cast", "error": "enemy target not found"})
            zone = db.get(Zone, hero.zone)
            if zone is None or zone.kind == "sanctuary":
                return ResolutionResult(False, {"verb": "cast", "error": "PvP magic forbidden in sanctuary"})
            if target.zone != hero.zone or not _check_range(target.pos_x, target.pos_y):
                return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
        else:
            return ResolutionResult(False, {"verb": "cast", "error": f"apply_status target_kind '{spell.target_kind}' not supported"})
        _apply_status(
            db, target, slug=slug, duration_ticks=duration,
            source_hero_id=hero.id, payload=bonus_payload or None,
        )
        outcome.update(target=target.name, target_kind="hero", status_applied=slug, duration_ticks=duration)

    elif kind == "dispel":
        slugs_to_strip = list(payload.get("slugs") or ["bleed", "blind", "fear", "slow", "sleep"])
        target = hero if spell.target_kind == "self" else _resolve_target_hero(target_arg)
        if target is None:
            return ResolutionResult(False, {"verb": "cast", "error": "target not found"})
        if target.zone != hero.zone:
            return ResolutionResult(False, {"verb": "cast", "error": "target not in this zone"})
        if target.id != hero.id and not _check_range(target.pos_x, target.pos_y):
            return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
        stripped = list(
            db.scalars(
                select(Status).where(
                    Status.hero_id == target.id, Status.slug.in_(slugs_to_strip)
                )
            )
        )
        for s in stripped:
            db.delete(s)
        outcome.update(target=target.name, target_kind="hero", dispelled=[s.slug for s in stripped])

    elif kind == "move_self":
        zone = db.get(Zone, hero.zone)
        if zone is None:
            return ResolutionResult(False, {"verb": "cast", "error": "unknown zone"})
        if not (isinstance(target_arg, list) and len(target_arg) == 2):
            return ResolutionResult(False, {"verb": "cast", "error": "blink target must be [x, y]"})
        try:
            tx, ty = int(target_arg[0]), int(target_arg[1])
        except (TypeError, ValueError):
            return ResolutionResult(False, {"verb": "cast", "error": "blink coords must be ints"})
        if not (0 <= tx < zone.width and 0 <= ty < zone.height):
            return ResolutionResult(False, {"verb": "cast", "error": "blink out of bounds"})
        if abs(tx - hero.pos_x) + abs(ty - hero.pos_y) > spell.range:
            return ResolutionResult(False, {"verb": "cast", "error": "blink out of range"})
        old = (hero.pos_x, hero.pos_y)
        hero.pos_x, hero.pos_y = tx, ty
        outcome.update(blinked_from=list(old), blinked_to=[tx, ty])

    elif kind == "move_target":
        target = _resolve_target_hero(target_arg)
        if target is None or target.zone != hero.zone:
            return ResolutionResult(False, {"verb": "cast", "error": "target not in this zone"})
        if not _check_range(target.pos_x, target.pos_y):
            return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
        push = int(payload.get("push_tiles") or 2)
        zone = db.get(Zone, target.zone)
        dx = (target.pos_x - hero.pos_x)
        dy = (target.pos_y - hero.pos_y)
        if abs(dx) >= abs(dy):
            step_x = (1 if dx >= 0 else -1) * push
            new_x = max(0, min((zone.width if zone else 10) - 1, target.pos_x + step_x))
            new_y = target.pos_y
        else:
            step_y = (1 if dy >= 0 else -1) * push
            new_x = target.pos_x
            new_y = max(0, min((zone.height if zone else 10) - 1, target.pos_y + step_y))
        old = (target.pos_x, target.pos_y)
        target.pos_x, target.pos_y = new_x, new_y
        outcome.update(target=target.name, target_kind="hero", pushed_from=list(old), pushed_to=[new_x, new_y])

    elif kind == "summon_npc":
        mob_slug_template = str(payload.get("mob") or "summoned_wisp")
        mob_name = str(payload.get("name") or "Summoned Wisp")
        mob_hp = int(payload.get("hp") or 1)
        new_slug = f"{mob_slug_template}_{uuid.uuid4().hex[:8]}"
        adjacent_pos = (hero.pos_x + 1, hero.pos_y)
        npc = NPC(
            slug=new_slug, name=mob_name, kind="mob",
            zone=hero.zone, pos_x=adjacent_pos[0], pos_y=adjacent_pos[1],
            hp_max=mob_hp, hp_current=mob_hp, ac=8,
            hostility="peaceful", alive=True, loot_gold=0,
            tameable=False, tamed_by_hero_id=hero.id,
        )
        db.add(npc)
        outcome.update(summoned_slug=new_slug, summoned_at=list(adjacent_pos))

    elif kind == "reveal":
        in_range: list[Hero] = []
        for h in db.scalars(select(Hero).where(Hero.zone == hero.zone, Hero.id != hero.id)):
            if _check_range(h.pos_x, h.pos_y):
                in_range.append(h)
        revealed: list[str] = []
        for h in in_range:
            stealth = db.scalar(
                select(Status).where(Status.hero_id == h.id, Status.slug == "stealth")
            )
            if stealth is not None:
                db.delete(stealth)
                revealed.append(h.name)
        outcome.update(revealed=revealed)

    else:
        return ResolutionResult(False, {"verb": "cast", "error": f"unsupported effect_kind '{kind}'"})

    hero.mana_current -= spell.mana_cost
    _grant_xp(hero, spell.skill_required, 1)
    outcome["mana_remaining"] = hero.mana_current
    outcome["skill_xp"] = int((hero.skills or {}).get(spell.skill_required, 0) or 0)
    outcome["effect_kind"] = kind
    return ResolutionResult(True, outcome)


def _resolve_cast(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Cast a spell the hero has learned."""
    spell_slug = action.get("spell")
    if not spell_slug:
        return ResolutionResult(False, {"verb": "cast", "error": "missing spell"})

    known = list(hero.known_spells or [])
    if spell_slug not in known:
        return ResolutionResult(False, {"verb": "cast", "error": f"spell '{spell_slug}' not known"})

    spell = db.get(Spell, str(spell_slug))
    if spell is None:
        return ResolutionResult(False, {"verb": "cast", "error": f"unknown spell '{spell_slug}'"})

    if hero.mana_current < spell.mana_cost:
        return ResolutionResult(
            False, {"verb": "cast", "error": f"insufficient mana ({hero.mana_current} < {spell.mana_cost})"}
        )

    skill_lvl = _skill_level(hero, spell.skill_required)
    if skill_lvl < spell.skill_min:
        return ResolutionResult(
            False, {"verb": "cast", "error": f"{spell.skill_required} too low ({skill_lvl} < {spell.skill_min})"}
        )

    target_arg = action.get("target")
    outcome: dict[str, Any] = {
        "verb": "cast", "spell": spell.slug, "school": spell.school,
        "mana_cost": spell.mana_cost,
    }

    # Phase 2: spells with a non-default effect_kind dispatch to a
    # dedicated handler. The default (`damage_or_heal`) keeps the v0.6
    # damage/heal flow below intact for firebolt/frost_lance/mend.
    effect_kind = getattr(spell, "effect_kind", "damage_or_heal") or "damage_or_heal"
    if effect_kind != "damage_or_heal":
        return _resolve_spell_effect(
            db, hero, spell, action, target_arg, skill_lvl, outcome,
        )

    if spell.target_kind == "self":
        if spell.heal_dice and spell.heal_dice != "0d0":
            heal = roll(spell.heal_dice) + skill_lvl // 8
            new_hp = min(20 + hero.con, hero.hp + heal)
            healed_for = new_hp - hero.hp
            hero.hp = new_hp
            outcome.update(target=hero.name, heal=healed_for, target_hp=hero.hp)

    elif spell.target_kind == "enemy":
        if not target_arg:
            return ResolutionResult(False, {"verb": "cast", "error": "missing target"})
        target_npc = db.get(NPC, str(target_arg))
        target_hero = db.scalar(select(Hero).where(Hero.name == str(target_arg)))
        zone = db.get(Zone, hero.zone)

        if target_npc is not None and target_npc.alive and target_npc.zone == hero.zone:
            if abs(target_npc.pos_x - hero.pos_x) + abs(target_npc.pos_y - hero.pos_y) > spell.range:
                return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
            damage = roll(spell.damage_dice) + skill_lvl // 4
            target_npc.hp_current = max(0, target_npc.hp_current - damage)
            killed = target_npc.hp_current <= 0
            loot_gold = 0
            if killed:
                target_npc.alive = False
                loot_gold = target_npc.loot_gold
                if loot_gold > 0:
                    _set_hero_gold(
                        db, hero, _hero_gold(hero) + loot_gold,
                        source="attack_loot",
                    )
            outcome.update(
                target=target_npc.slug, target_kind="npc", damage=damage,
                target_hp_remaining=target_npc.hp_current, killed=killed, loot_gold=loot_gold,
            )

        elif target_hero is not None and target_hero.id != hero.id:
            if zone is None or zone.kind == "sanctuary":
                return ResolutionResult(False, {"verb": "cast", "error": "PvP magic forbidden in sanctuary"})
            if target_hero.zone != hero.zone:
                return ResolutionResult(False, {"verb": "cast", "error": "target not in this zone"})
            if abs(target_hero.pos_x - hero.pos_x) + abs(target_hero.pos_y - hero.pos_y) > spell.range:
                return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
            damage = roll(spell.damage_dice) + skill_lvl // 4
            target_hero.hp = max(0, target_hero.hp - damage)
            fatal = target_hero.hp <= 0
            killed = False
            if fatal:
                from app.core.actions.combat import _resolve_hero_death_or_respawn
                killed = _resolve_hero_death_or_respawn(
                    db, target_hero, current_tick=_current_tick(db)
                )
                if killed:
                    _increment_kills(db, hero, victim_kind="hero")
            outcome.update(
                target=target_hero.name, target_kind="hero", damage=damage,
                target_hp_remaining=target_hero.hp, killed=killed,
            )

        else:
            return ResolutionResult(False, {"verb": "cast", "error": "target not found"})

    elif spell.target_kind == "hero":
        if not target_arg:
            return ResolutionResult(False, {"verb": "cast", "error": "missing target"})
        target_hero = db.scalar(select(Hero).where(Hero.name == str(target_arg)))
        if target_hero is None or target_hero.zone != hero.zone or target_hero.status != "alive":
            return ResolutionResult(False, {"verb": "cast", "error": "target hero not reachable"})
        if abs(target_hero.pos_x - hero.pos_x) + abs(target_hero.pos_y - hero.pos_y) > spell.range:
            return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
        if spell.heal_dice and spell.heal_dice != "0d0":
            heal = roll(spell.heal_dice) + skill_lvl // 8
            new_hp = min(20 + target_hero.con, target_hero.hp + heal)
            healed_for = new_hp - target_hero.hp
            target_hero.hp = new_hp
            outcome.update(target=target_hero.name, target_kind="hero", heal=healed_for, target_hp=target_hero.hp)

    else:
        return ResolutionResult(False, {"verb": "cast", "error": f"unsupported target_kind '{spell.target_kind}'"})

    hero.mana_current -= spell.mana_cost
    _grant_xp(hero, spell.skill_required, 1)
    outcome["mana_remaining"] = hero.mana_current
    outcome["skill_xp"] = int((hero.skills or {}).get(spell.skill_required, 0) or 0)
    return ResolutionResult(True, outcome)


def _resolve_tame(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Attempt to tame an adjacent tameable mob.

    Roll: d20 + CHA/4 + WIS/4 vs DC 12. Nat 1 = mob attacks back next tick;
    nat 20 = automatic. On success the mob's hostility flips to "tamed",
    tamed_by_hero_id is set, and the pet starts following the hero around
    (handled in tick.py mob phase).
    """
    target_slug = action.get("target")
    if not target_slug:
        return ResolutionResult(False, {"verb": "tame", "error": "missing target"})

    target = db.get(NPC, str(target_slug))
    if target is None or target.zone != hero.zone:
        return ResolutionResult(False, {"verb": "tame", "error": "target not in this zone"})
    if not target.alive:
        return ResolutionResult(False, {"verb": "tame", "error": "target is dead"})
    if not target.tameable:
        return ResolutionResult(False, {"verb": "tame", "error": "target is not tameable"})
    if target.tamed_by_hero_id is not None:
        return ResolutionResult(False, {"verb": "tame", "error": "already tamed"})
    if abs(target.pos_x - hero.pos_x) + abs(target.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "tame", "error": "target not adjacent"})

    dc = 12
    roll_d20 = d20()
    total = roll_d20 + hero.cha // 4 + hero.wis // 4
    success = roll_d20 == 20 or (roll_d20 != 1 and total >= dc)
    if success:
        target.hostility = "tamed"
        target.tamed_by_hero_id = hero.id
        _grant_xp(hero, "taming", 3)
        _journal_milestone(
            db, hero,
            text=f"Tamed {target.name}. They follow me now.",
            tags=["milestone", "tamed", target.slug],
        )
    return ResolutionResult(
        True,
        {
            "verb": "tame", "target": target.slug, "success": bool(success),
            "roll": roll_d20, "total": total, "dc": dc,
            "now_tamed_by": str(hero.id) if success else None,
        },
    )


def _resolve_learn(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Consume a scroll item from inventory; add the spell it teaches."""
    scroll_slug = action.get("scroll") or action.get("slug")
    if not scroll_slug:
        return ResolutionResult(False, {"verb": "learn", "error": "missing scroll"})
    item = _inventory_stack(db, hero, str(scroll_slug))
    if item is None:
        return ResolutionResult(False, {"verb": "learn", "error": f"no '{scroll_slug}' in inventory"})
    teaches = (item.props or {}).get("teaches")
    if not teaches:
        return ResolutionResult(False, {"verb": "learn", "error": f"'{scroll_slug}' teaches nothing"})

    spell = db.get(Spell, str(teaches))
    if spell is None:
        return ResolutionResult(False, {"verb": "learn", "error": f"unknown spell '{teaches}'"})

    known = list(hero.known_spells or [])
    if spell.slug in known:
        return ResolutionResult(False, {"verb": "learn", "error": f"already know '{spell.slug}'"})

    known.append(spell.slug)
    hero.known_spells = known
    _consume_from_inventory(db, hero, item.slug, 1)
    return ResolutionResult(
        True, {"verb": "learn", "spell": spell.slug, "consumed_scroll": scroll_slug}
    )
