"""Action dispatcher — `resolve()`.

The single switch that routes a hero's submitted action to its
category-specific handler. Every primitive verb in `app.core.verbs`
maps to exactly one handler imported below; unknown verbs return a
structured error so the spectator stream can surface them.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.actions._helpers import _validate_action_shape, defending_this_tick
from app.core.actions._result import ResolutionResult
from app.core.actions.combat import (
    _resolve_attack,
    _resolve_attack_hero,
    _resolve_flee,
)
from app.core.actions.contracts import (
    _resolve_accept_offer,
    _resolve_cancel_contract,
    _resolve_claim_contract,
    _resolve_offer,
    _resolve_post_contract,
    _resolve_recall,
    _resolve_register_tournament,
    _resolve_reject_offer,
)
from app.core.actions.equipment import _resolve_equip, _resolve_unequip
from app.core.actions.gathering import _resolve_craft, _resolve_fish, _resolve_gather
from app.core.actions.inventory import (
    _resolve_buy_house,
    _resolve_journal_write,
    _resolve_store,
    _resolve_withdraw,
)
from app.core.actions.magic import _resolve_cast, _resolve_learn, _resolve_tame
from app.core.actions.movement import _resolve_move, _resolve_travel
from app.core.actions.perception import (
    _visible_heroes_in_zone,
    _visible_items_in_zone,
    _visible_npcs_in_zone,
)
from app.core.actions.quests import (
    _resolve_accept_quest,
    _resolve_claim_reward,
    _resolve_steal,
)
from app.core.actions.sandbox import _resolve_leave_sandbox
from app.core.actions.social import (
    _resolve_drop,
    _resolve_examine,
    _resolve_give,
    _resolve_pickup,
    _resolve_say,
)
from app.core.actions.trade import _resolve_buy, _resolve_sell
from app.core.hero_budgets import look_radius
from app.core.models import Hero


def resolve(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    # P1-4: dead heroes cannot act. The tick loop already filters alive
    # heroes when scheduling, but managed bots can race a death write
    # over WebSocket — without this guard, a corpse mutates the world.
    if hero.status != "alive":
        return ResolutionResult(False, {"error": "hero is dead", "reason": "dead", "verb": None})

    if not isinstance(action, dict):
        return ResolutionResult(False, {"error": "action must be a dict", "verb": None})

    verb = action.get("do")
    # P2-5: shape-check the action's required fields before dispatching.
    # Catches the FIX_PLAN done-when case ({"do":"attack","target":42})
    # with a structured reason="bad_action_shape" so it lands in the
    # parse_failure stream rather than as a downstream "no such NPC".
    if isinstance(verb, str):
        shape_err = _validate_action_shape(verb, action)
        if shape_err is not None:
            return ResolutionResult(False, {
                "verb": verb,
                "error": shape_err,
                "reason": "bad_action_shape",
            })

    if verb == "wait":
        return ResolutionResult(True, {"verb": "wait"})

    if verb == "look":
        radius = look_radius(hero)
        return ResolutionResult(
            True,
            {
                "verb": "look",
                "radius": radius,
                "heroes": _visible_heroes_in_zone(db, hero, radius),
                "npcs": _visible_npcs_in_zone(db, hero, radius),
                "items": _visible_items_in_zone(db, hero, radius),
            },
        )

    if verb == "move":
        return _resolve_move(db, hero, action)

    if verb == "say":
        return _resolve_say(db, hero, action)

    if verb == "examine":
        return _resolve_examine(db, hero, action)

    if verb == "pickup":
        return _resolve_pickup(db, hero, action)

    if verb == "drop":
        return _resolve_drop(db, hero, action)

    if verb == "give":
        return _resolve_give(db, hero, action)

    if verb == "travel":
        return _resolve_travel(db, hero, action)

    if verb == "equip":
        return _resolve_equip(db, hero, action)

    if verb == "unequip":
        return _resolve_unequip(db, hero, action)

    if verb == "gather":
        return _resolve_gather(db, hero, action)

    if verb == "fish":
        return _resolve_fish(db, hero, action)

    if verb == "craft":
        return _resolve_craft(db, hero, action)

    if verb == "buy":
        return _resolve_buy(db, hero, action)

    if verb == "sell":
        return _resolve_sell(db, hero, action)

    if verb == "cast":
        return _resolve_cast(db, hero, action)

    if verb == "learn":
        return _resolve_learn(db, hero, action)

    if verb == "steal":
        return _resolve_steal(db, hero, action)

    if verb == "tame":
        return _resolve_tame(db, hero, action)

    if verb == "accept_quest":
        return _resolve_accept_quest(db, hero, action)

    if verb == "claim_reward":
        return _resolve_claim_reward(db, hero, action)

    if verb == "journal_write":
        return _resolve_journal_write(db, hero, action)

    if verb == "recall":
        return _resolve_recall(db, hero, action)

    if verb == "store":
        return _resolve_store(db, hero, action)

    if verb == "withdraw":
        return _resolve_withdraw(db, hero, action)

    if verb == "buy_house":
        return _resolve_buy_house(db, hero, action)

    if verb == "offer":
        return _resolve_offer(db, hero, action)

    if verb == "accept_offer":
        return _resolve_accept_offer(db, hero, action)

    if verb == "reject_offer":
        return _resolve_reject_offer(db, hero, action)

    if verb == "register_tournament":
        return _resolve_register_tournament(db, hero, action)

    if verb == "post_bounty":
        # Phase 4: post_bounty is a thin alias over post_contract with
        # kind="bounty" so existing manifests keep working. The action's
        # `gold` field maps to post_contract's `reward`.
        rewritten = {
            "do": "post_contract",
            "kind": "bounty",
            "target": action.get("target"),
            "reward": action.get("gold") or action.get("reward"),
            "reason": action.get("reason", ""),
        }
        return _resolve_post_contract(db, hero, rewritten)

    if verb == "post_contract":
        return _resolve_post_contract(db, hero, action)

    if verb == "claim_contract":
        return _resolve_claim_contract(db, hero, action)

    if verb == "cancel_contract":
        return _resolve_cancel_contract(db, hero, action)

    if verb == "attack":
        return _resolve_attack(db, hero, action)

    if verb == "attack_hero":
        return _resolve_attack_hero(db, hero, action)

    if verb == "defend":
        defending_this_tick.add(str(hero.id))
        return ResolutionResult(True, {"verb": "defend", "ac_bonus": 5})

    if verb == "flee":
        return _resolve_flee(db, hero, action)

    if verb == "leave_sandbox":
        return _resolve_leave_sandbox(db, hero, action)

    return ResolutionResult(
        False,
        {"verb": verb, "error": f"unknown verb '{verb}'", "reason": "unknown_verb"},
    )
