"""Melee combat: attack mob, attack hero (PvP), flee, hero death/respawn.

`_resolve_hero_death_or_respawn` is the single chokepoint for "did this
fatal blow stick?" so the three call sites (mob retaliation,
attack_hero PvP, cast PvP) share one rule. Bounty / tournament
side-effects only fire when True is returned.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actions._helpers import (
    _add_to_inventory,
    _current_tick,
    _equipped_armor_bonus,
    _equipped_weapon,
    _grant_rep,
    _grant_xp,
    _hero_gold,
    _increment_kills,
    _journal_milestone,
    _move_speed,
    _quest_progress,
    _set_hero_gold,
    _skill_level,
    defending_this_tick,
)
from app.core.actions._result import ResolutionResult
from app.core.actions.contracts import (
    _claim_bounties_on_kill,
    _resolve_defense_contracts_on_kill,
)
from app.core.actions.statuses import _status_modifier
from app.core.dice import d20, roll
from app.core.models import Hero, NPC, Tournament, TournamentEntry, Zone


_SANCTUARY_KINDS = {"sanctuary", "sandbox"}


def _resolve_attack(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("target")
    if not target_slug:
        return ResolutionResult(False, {"verb": "attack", "error": "missing target"})

    target = db.get(NPC, str(target_slug))
    if target is None:
        return ResolutionResult(False, {"verb": "attack", "error": "target not found"})
    if target.zone != hero.zone:
        return ResolutionResult(False, {"verb": "attack", "error": "target not in this zone"})
    if not target.alive:
        return ResolutionResult(False, {"verb": "attack", "error": "target already dead"})
    if target.hostility != "hostile":
        return ResolutionResult(False, {"verb": "attack", "error": "target is peaceful"})
    if abs(target.pos_x - hero.pos_x) + abs(target.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "attack", "error": "target out of melee range"})

    weapon = _equipped_weapon(db, hero)
    weapon_props = weapon.props if weapon and isinstance(weapon.props, dict) else {}
    weapon_bonus = int(weapon_props.get("attack_bonus", 0) or 0)
    weapon_dice = weapon_props.get("damage_dice") or "1d2"
    melee_lvl = _skill_level(hero, "melee")
    skill_bonus = melee_lvl // 4  # +1 attack at level 4, +5 at level 20

    # Phase 2 — to-hit shifts from active statuses (bless +1, blind -3,
    # fear -2, sleep -10). NPC targets don't carry hero statuses so AC
    # adjustments only land on PvP targets (handled in attack_hero).
    status_to_hit = _status_modifier(db, hero, kind="to_hit_bonus")
    # Phase 7 — affix bonuses on the equipped weapon. `to_hit_bonus_extra`
    # comes from suffixes like `of_the_bear`; `crit_bonus` widens the
    # crit window from 20 to 19-20 with `keen`.
    affix_to_hit = int(weapon_props.get("to_hit_bonus_extra", 0) or 0)
    affix_crit_bonus = int(weapon_props.get("crit_bonus", 0) or 0)
    attack_roll = d20()
    attack_total = attack_roll + (hero.str_ // 4) + weapon_bonus + skill_bonus + status_to_hit + affix_to_hit
    crit_threshold = 20 - affix_crit_bonus
    crit = attack_roll >= crit_threshold
    fumble = attack_roll == 1

    if fumble:
        return ResolutionResult(
            True,
            {
                "verb": "attack", "target": target.slug, "roll": attack_roll, "total": attack_total,
                "ac": target.ac, "hit": False, "crit": False, "fumble": True, "damage": 0,
                "weapon": weapon.slug if weapon else None, "melee_lvl": melee_lvl,
                "status_to_hit": status_to_hit,
            },
        )
    hit = crit or attack_total >= target.ac
    if not hit:
        return ResolutionResult(
            True,
            {
                "verb": "attack", "target": target.slug, "roll": attack_roll, "total": attack_total,
                "ac": target.ac, "hit": False, "crit": False, "fumble": False, "damage": 0,
                "weapon": weapon.slug if weapon else None, "melee_lvl": melee_lvl,
            },
        )

    # Phase 7 — quality multiplier on weapon damage; prefix `flaming` /
    # `frostbound` adds `extra_damage_dice`; `thirsty` heals on hit.
    # `of_silver_blood` rolls bonus dice against undead (skeleton/revenant).
    damage_mult = float(weapon_props.get("damage_multiplier", 1.0) or 1.0)
    base_damage = roll(weapon_dice) + (hero.str_ // 4)
    extra_dice = weapon_props.get("extra_damage_dice")
    extra_damage = roll(str(extra_dice)) if extra_dice else 0
    undead_bonus_dice = weapon_props.get("undead_bonus_dice")
    if undead_bonus_dice and target.slug.startswith(("skeleton", "revenant")):
        extra_damage += roll(str(undead_bonus_dice))
    damage = int(base_damage * damage_mult) + extra_damage
    if crit:
        damage *= 2
    target.hp_current = max(0, target.hp_current - damage)
    heal_on_hit = int(weapon_props.get("heal_on_hit", 0) or 0)
    if heal_on_hit > 0:
        hero.hp = min(20 + hero.con, hero.hp + heal_on_hit)
    _grant_xp(hero, "melee", 1)

    killed = target.hp_current <= 0
    loot_gold = 0
    completed_quests: list[str] = []
    if killed:
        target.alive = False
        loot_gold = target.loot_gold
        if loot_gold > 0:
            _set_hero_gold(
                db, hero, _hero_gold(hero) + loot_gold,
                source="attack_mob_loot",
            )
        _grant_xp(hero, "melee", 5)
        _increment_kills(db, hero, victim_kind="mob")
        # Defense contracts: claimer killed a hostile while adjacent to
        # their poster in the protected zone.
        _resolve_defense_contracts_on_kill(
            db, hero, victim_kind="mob", current_tick=_current_tick(db)
        )
        completed_quests = _quest_progress(db, hero, "kill_count", target.slug, 1)
        _grant_rep(hero, "council", 1, db=db)
        for faction, delta in (target.factions_aligned or {}).items():
            try:
                _grant_rep(hero, str(faction), int(delta), db=db)
            except (TypeError, ValueError):
                continue
        _journal_milestone(
            db, hero,
            text=f"First slain: {target.name} ({target.slug}). Loot: {loot_gold}g.",
            tags=["milestone", "first_kill", target.slug],
        )
        if target.slug == "wyrm_of_the_sundering":
            _add_to_inventory(
                db, hero,
                slug="dragon_scale",
                name="Dragon Scale",
                kind="trinket",
                description="A scale prized off the Wyrm of the Sundering. Heavy, warm to the touch.",
                qty=1,
            )
            _journal_milestone(
                db, hero,
                text="Slew the Wyrm of the Sundering. Took a scale from its body.",
                tags=["milestone", "wyrm_slain", "dragon_scale"],
                dedupe=False,
            )
        loot_drops = _roll_mob_loot_drops(db, hero, target)
        if loot_drops:
            for drop in loot_drops:
                _journal_milestone(
                    db, hero,
                    text=f"Looted {drop['name']} from {target.name}.",
                    tags=["milestone", "loot_drop", drop["slug"]],
                    dedupe=False,
                )
        for tpl_slug in completed_quests:
            _journal_milestone(
                db, hero,
                text=f"Quest complete: {tpl_slug.replace('_', ' ')}. Return for the reward.",
                tags=["milestone", "quest_done", tpl_slug],
            )

    return ResolutionResult(
        True,
        {
            "verb": "attack",
            "target": target.slug,
            "roll": attack_roll,
            "total": attack_total,
            "ac": target.ac,
            "hit": True,
            "crit": crit,
            "fumble": False,
            "damage": damage,
            "target_hp_remaining": target.hp_current,
            "killed": killed,
            "loot_gold": loot_gold,
            "weapon": weapon.slug if weapon else None,
            "melee_lvl": melee_lvl,
            "melee_xp": int((hero.skills or {}).get("melee", 0) or 0),
            "quests_completed": completed_quests,
        },
    )


def _resolve_hero_death_or_respawn(
    db: Session, victim: Hero, *, current_tick: int
) -> bool:
    """Phase 8 — sandbox protection. Heroes inside their protection
    window OR standing in a sandbox zone respawn at full HP instead of
    permadying. Returns True if the hero actually died, False if they
    were rescued."""
    zone = db.get(Zone, victim.zone)
    in_sandbox_zone = zone is not None and zone.kind == "sandbox"
    in_protection_window = current_tick < int(victim.protected_until_tick or 0)
    if in_sandbox_zone or in_protection_window:
        victim.hp = 20 + victim.con
        victim.status = "alive"
        _journal_milestone(
            db, victim,
            text="The sandbox caught me before the floor did. Back on my feet.",
            tags=["milestone", "sandbox_respawn"],
            dedupe=False,
        )
        return False
    victim.status = "dead"
    victim.died_at_tick = current_tick
    return True


# Phase 7 — mob loot tables. Each entry is a slug-keyed list of
# possible drops with chance, item template, and affix-roll knobs. The
# Wyrm's special drop is kept inline at the kill site (it predates
# this table); everything else lives here so adding a new drop is one
# small dict edit. None of this needs new schema — drops spawn through
# the existing `_add_to_inventory` path with affix-rolled props.
_MOB_LOOT_TABLE: dict[str, list[dict[str, Any]]] = {
    "revenant_a": [
        {
            "chance": 1.0,
            "slug": "captain_blade",
            "name": "Captain's Longsword",
            "kind": "weapon",
            "description": "Plain steel kept too well for a corpse. Rim sharp.",
            "base_props": {"slot": "weapon", "damage_dice": "1d10", "attack_bonus": 1},
            "force_quality": "exceptional",
            "prefix_chance": 0.6,
            "suffix_chance": 0.4,
        },
    ],
    "brigand_a": [
        {
            "chance": 0.4,
            "slug": "brigand_dagger",
            "name": "Brigand's Dagger",
            "kind": "weapon",
            "description": "A worn, balanced dagger with a leather-wrapped grip.",
            "base_props": {"slot": "weapon", "damage_dice": "1d4", "attack_bonus": 1},
            "force_quality": "fine",
            "prefix_chance": 0.15,
            "suffix_chance": 0.0,
        },
    ],
    "brigand_b": [
        {
            "chance": 0.4,
            "slug": "brigand_dagger",
            "name": "Brigand's Dagger",
            "kind": "weapon",
            "description": "A worn, balanced dagger with a leather-wrapped grip.",
            "base_props": {"slot": "weapon", "damage_dice": "1d4", "attack_bonus": 1},
            "force_quality": "fine",
            "prefix_chance": 0.15,
            "suffix_chance": 0.0,
        },
    ],
}


def _roll_mob_loot_drops(db: Session, hero: Hero, target: NPC) -> list[dict[str, Any]]:
    """Roll the loot table for `target.slug`. Returns a list of
    {slug, name} dicts so the caller can emit a journal milestone per
    drop. Items spawn directly into the killer's inventory."""
    import random
    table = _MOB_LOOT_TABLE.get(target.slug, [])
    if not table:
        return []
    from app.core.affixes import render_affixed_name, roll_affixes
    drops: list[dict[str, Any]] = []
    for entry in table:
        if random.random() > entry.get("chance", 1.0):
            continue
        base_props = dict(entry.get("base_props") or {})
        rolled_props = roll_affixes(
            base_props,
            skill_level=0,
            prefix_chance=float(entry.get("prefix_chance", 0.0) or 0.0),
            suffix_chance=float(entry.get("suffix_chance", 0.0) or 0.0),
            force_quality=entry.get("force_quality"),
        )
        rolled_name = render_affixed_name(entry["name"], rolled_props)
        _add_to_inventory(
            db, hero,
            slug=entry["slug"],
            name=rolled_name,
            kind=entry["kind"],
            description=entry.get("description", ""),
            props=rolled_props,
            qty=1,
        )
        drops.append({"slug": entry["slug"], "name": rolled_name})
    return drops


def _credit_tournament_kill(db: Session, killer: Hero, victim_zone: str, current_tick: int) -> None:
    """If the killer is registered in an in-window tournament whose zone matches
    the kill's zone, bump their kills count. Used by attack_hero on a fatal blow."""
    entries = list(
        db.scalars(select(TournamentEntry).where(TournamentEntry.hero_id == killer.id))
    )
    for e in entries:
        t = db.get(Tournament, e.tournament_slug)
        if t is None or t.status not in ("open", "in_progress"):
            continue
        if t.zone != victim_zone:
            continue
        if t.starts_at_tick and current_tick < t.starts_at_tick:
            continue
        if t.ends_at_tick and current_tick > t.ends_at_tick:
            continue
        e.kills += 1


def _resolve_attack_hero(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """PvP hero-vs-hero attack. Refuses inside sanctuaries."""
    target_name = action.get("target")
    if not target_name:
        return ResolutionResult(False, {"verb": "attack_hero", "error": "missing target"})

    zone = db.get(Zone, hero.zone)
    if zone is None or zone.kind in _SANCTUARY_KINDS:
        zone_kind = zone.kind if zone else "unknown"
        return ResolutionResult(
            False,
            {
                "verb": "attack_hero",
                "error": f"PvP forbidden in this zone (kind={zone_kind})",
                "zone_kind": zone_kind,
            },
        )

    target = db.scalar(select(Hero).where(Hero.name == str(target_name)))
    if target is None:
        return ResolutionResult(False, {"verb": "attack_hero", "error": "target hero not found"})
    if target.id == hero.id:
        return ResolutionResult(False, {"verb": "attack_hero", "error": "cannot attack yourself"})
    if target.zone != hero.zone:
        return ResolutionResult(False, {"verb": "attack_hero", "error": "target not in this zone"})
    if target.status != "alive":
        return ResolutionResult(False, {"verb": "attack_hero", "error": "target already dead"})
    if abs(target.pos_x - hero.pos_x) + abs(target.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "attack_hero", "error": "target out of melee range"})

    # Phase 2 — status modifiers on both sides of the roll. The
    # attacker's bless/blind shifts to-hit; the target's stoneskin
    # raises AC; sleep tanks both sides of the defender's stats.
    attacker_to_hit = _status_modifier(db, hero, kind="to_hit_bonus")
    target_ac_status = _status_modifier(db, target, kind="ac_bonus")
    target_to_hit_status = _status_modifier(db, target, kind="to_hit_bonus")  # sleep penalty
    attack_roll = d20()
    attack_total = attack_roll + (hero.str_ // 4) + attacker_to_hit
    crit = attack_roll == 20
    fumble = attack_roll == 1

    target_ac = 10 + target.dex // 4 + _equipped_armor_bonus(target, db) + target_ac_status
    if target_to_hit_status <= -10:
        # Asleep — caster's roll auto-meets-AC for narrative impact.
        target_ac = 0
    if str(target.id) in defending_this_tick:
        target_ac += 5

    outcome: dict[str, Any] = {
        "verb": "attack_hero",
        "target": target.name,
        "target_id": str(target.id),
        "roll": attack_roll,
        "total": attack_total,
        "ac": target_ac,
        "crit": crit,
        "fumble": fumble,
        "zone_kind": zone.kind,
    }

    if fumble:
        outcome.update(hit=False, damage=0)
        return ResolutionResult(True, outcome)

    hit = crit or attack_total >= target_ac
    if not hit:
        outcome.update(hit=False, damage=0)
        return ResolutionResult(True, outcome)

    damage = roll("1d2") + (hero.str_ // 4)
    if crit:
        damage *= 2
    target.hp = max(0, target.hp - damage)
    fatal = target.hp <= 0
    killed = False
    looted_gold = 0
    if fatal:
        killed = _resolve_hero_death_or_respawn(db, target, current_tick=_current_tick(db))
    if killed:
        _increment_kills(db, hero, victim_kind="hero")
        _credit_tournament_kill(db, hero, hero.zone, _current_tick(db))
        bounty_payouts = _claim_bounties_on_kill(db, hero, target.id, _current_tick(db))
        if bounty_payouts:
            outcome["bounties_claimed"] = bounty_payouts
        # 50% of victim's gold goes to the killer (per DESIGN.md §6 #6).
        victim_gold = _hero_gold(target)
        looted_gold = victim_gold // 2
        if looted_gold > 0:
            _set_hero_gold(db, target, victim_gold - looted_gold, source="pvp_looted")
            _set_hero_gold(db, hero, _hero_gold(hero) + looted_gold, source="pvp_loot")

    outcome.update(
        hit=True, damage=damage,
        target_hp_remaining=target.hp,
        killed=killed,
        looted_gold=looted_gold,
    )
    return ResolutionResult(True, outcome)


def _resolve_flee(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Step away from the nearest threat — hostile NPC OR another hero in a
    PvP zone. If nothing nearby, drift one tile to break standoffs."""
    zone = db.get(Zone, hero.zone)
    speed = _move_speed(hero)

    threats: list[tuple[int, int, str]] = []  # (x, y, label)
    for n in db.scalars(
        select(NPC).where(NPC.zone == hero.zone, NPC.hostility == "hostile", NPC.alive.is_(True))
    ):
        threats.append((n.pos_x, n.pos_y, n.slug))
    if zone is not None and zone.kind != "sanctuary":
        for h in db.scalars(
            select(Hero).where(Hero.zone == hero.zone, Hero.id != hero.id, Hero.status == "alive")
        ):
            threats.append((h.pos_x, h.pos_y, h.name))

    if not threats:
        nudge_x = 1 if hero.pos_x < ((zone.width if zone else 10) // 2) else -1
        new_x = max(0, min((zone.width if zone else 10) - 1, hero.pos_x + nudge_x))
        old = (hero.pos_x, hero.pos_y)
        hero.pos_x = new_x
        return ResolutionResult(True, {"verb": "flee", "from": list(old), "to": [new_x, hero.pos_y], "no_threats": True})

    tx, ty, label = min(threats, key=lambda t: abs(t[0] - hero.pos_x) + abs(t[1] - hero.pos_y))
    dx, dy = hero.pos_x - tx, hero.pos_y - ty
    if dx == 0 and dy == 0:
        dx = 1 if hero.pos_x < (zone.width // 2 if zone else 5) else -1
    if abs(dx) >= abs(dy):
        step_x = max(-speed, min(speed, dx)) or (1 if dx >= 0 else -1)
        step_y = 0
    else:
        step_y = max(-speed, min(speed, dy)) or (1 if dy >= 0 else -1)
        step_x = 0
    new_x = max(0, min((zone.width if zone else 10) - 1, hero.pos_x + step_x))
    new_y = max(0, min((zone.height if zone else 10) - 1, hero.pos_y + step_y))
    old = (hero.pos_x, hero.pos_y)
    hero.pos_x, hero.pos_y = new_x, new_y
    return ResolutionResult(
        True,
        {"verb": "flee", "from": list(old), "to": [new_x, new_y], "fleeing_from": label},
    )
