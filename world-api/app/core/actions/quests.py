"""Quest-related action verbs (accept, claim_reward, steal).

Steal lives here because it's a faction-rep operation and shares the
quest-economy mental model: a one-shot social move with a roll, a
reputation cost, and (occasionally) a positive outcome."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actions._helpers import (
    _add_to_inventory,
    _grant_rep,
    _grant_xp,
    _hero_gold,
    _journal_milestone,
    _set_hero_gold,
    _skill_level,
)
from app.core.actions._result import ResolutionResult
from app.core.dice import d20
from app.core.memory import update_memory
from app.core.models import Hero, NPC, Quest, QuestTemplate


def _resolve_accept_quest(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Pick up the quest an adjacent NPC offers."""
    target_slug = action.get("target")
    if not target_slug:
        return ResolutionResult(False, {"verb": "accept_quest", "error": "missing target"})
    npc = db.get(NPC, str(target_slug))
    if npc is None or npc.zone != hero.zone:
        return ResolutionResult(False, {"verb": "accept_quest", "error": "target not in this zone"})
    if abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "accept_quest", "error": "target not adjacent"})
    if not npc.quest_offered:
        return ResolutionResult(False, {"verb": "accept_quest", "error": f"{npc.slug} offers no quest"})

    tpl = db.get(QuestTemplate, npc.quest_offered)
    if tpl is None:
        return ResolutionResult(False, {"verb": "accept_quest", "error": "quest template missing"})

    existing = db.scalar(
        select(Quest).where(
            Quest.hero_id == hero.id,
            Quest.template_slug == tpl.slug,
            Quest.status.in_(["active", "done"]),
        )
    )
    if existing is not None:
        return ResolutionResult(False, {"verb": "accept_quest", "error": "already on this quest"})

    db.add(Quest(
        id=uuid.uuid4(),
        hero_id=hero.id,
        template_slug=tpl.slug,
        status="active",
        count_done=0,
    ))
    return ResolutionResult(
        True,
        {
            "verb": "accept_quest", "from": npc.slug, "quest": tpl.slug,
            "name": tpl.name, "kind": tpl.kind, "target": tpl.target,
            "count_required": tpl.count_required,
            "reward_gold": tpl.reward_gold,
            "reward_faction": tpl.reward_faction,
            "reward_faction_amount": tpl.reward_faction_amount,
        },
    )


def _resolve_claim_reward(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Turn in a completed quest. Must be adjacent to the offering NPC."""
    quest_slug = action.get("quest")
    if not quest_slug:
        return ResolutionResult(False, {"verb": "claim_reward", "error": "missing quest"})

    tpl = db.get(QuestTemplate, str(quest_slug))
    if tpl is None:
        return ResolutionResult(False, {"verb": "claim_reward", "error": "quest template missing"})

    quest = db.scalar(
        select(Quest).where(
            Quest.hero_id == hero.id,
            Quest.template_slug == tpl.slug,
            Quest.status == "done",
        )
    )
    if quest is None:
        return ResolutionResult(False, {"verb": "claim_reward", "error": "quest not done"})

    npc = db.get(NPC, tpl.offered_by)
    if npc is None or npc.zone != hero.zone or abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "claim_reward", "error": f"return to {tpl.offered_by} to claim"})

    quest.status = "claimed"
    if tpl.reward_gold:
        _set_hero_gold(db, hero, _hero_gold(hero) + tpl.reward_gold, source="quest_reward")
    if tpl.reward_faction and tpl.reward_faction_amount:
        _grant_rep(hero, tpl.reward_faction, tpl.reward_faction_amount, db=db)
    _journal_milestone(
        db, hero,
        text=f"Claimed reward from {npc.name} for '{tpl.name}': {tpl.reward_gold}g.",
        tags=["milestone", "quest_claimed", tpl.slug],
    )

    # Main-quest chain: advance to next step or award title if this was a
    # main-quest stage. The award is folded into the outcome so the
    # spectator stream can pick it up.
    from app.domains.quest.main_quest import advance_main_quest
    awarded = advance_main_quest(db, hero, tpl.slug)
    if awarded and awarded.get("title"):
        _journal_milestone(
            db, hero,
            text=f"You are now known as: {awarded['title']}.",
            tags=["milestone", "title_earned", awarded["title"].lower().replace(" ", "_")],
            dedupe=False,
        )

    return ResolutionResult(
        True,
        {
            "verb": "claim_reward", "quest": tpl.slug,
            "reward_gold": tpl.reward_gold,
            "reward_faction": tpl.reward_faction,
            "reward_faction_amount": tpl.reward_faction_amount,
            "gold_now": _hero_gold(hero),
            **(awarded or {}),
        },
    )


def _resolve_steal(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Attempt to filch an item from a merchant's stock without paying.

    Mechanics:
      • d20 + DEX/4 + stealth_lvl/4 vs target's awareness DC (15 by default)
      • on success: 1 unit of the item moves to inventory, no gold paid
      • on failure: NPC's `aware_of_thief` flag in their merchant_stock
        meta gets set; future buy/sell prices for this hero are inflated 2×
        and reputation drops. (Reputation system tba — for v0.6.4 we just
        log the event.)
      • on natural 1: dropped (caught red-handed). Visible loud event.
    """
    target_slug = action.get("target")
    item_slug = action.get("item") or action.get("slug")
    if not target_slug or not item_slug:
        return ResolutionResult(False, {"verb": "steal", "error": "need target + item"})

    npc = db.get(NPC, str(target_slug))
    if npc is None or npc.zone != hero.zone:
        return ResolutionResult(False, {"verb": "steal", "error": "target not in this zone"})
    if abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "steal", "error": "target not adjacent"})

    stock_list = list(npc.merchant_stock or [])
    idx = next((i for i, s in enumerate(stock_list) if s.get("slug") == item_slug), None)
    if idx is None:
        return ResolutionResult(False, {"verb": "steal", "error": f"target doesn't carry '{item_slug}'"})
    entry = stock_list[idx]
    avail = entry.get("qty")
    if avail is not None and int(avail) <= 0:
        return ResolutionResult(False, {"verb": "steal", "error": "out of stock"})

    awareness_dc = 15
    stealth_lvl = _skill_level(hero, "stealth")
    roll_d20 = d20()
    total = roll_d20 + (hero.dex // 4) + (stealth_lvl // 4)
    fumble = roll_d20 == 1
    success = (not fumble) and (roll_d20 == 20 or total >= awareness_dc)

    outcome: dict[str, Any] = {
        "verb": "steal",
        "from": npc.slug,
        "item": entry["slug"],
        "roll": roll_d20,
        "total": total,
        "dc": awareness_dc,
        "stealth_lvl": stealth_lvl,
        "success": success,
    }

    if success:
        _add_to_inventory(
            db, hero,
            slug=entry["slug"],
            name=entry.get("name", entry["slug"]),
            kind=entry.get("kind", "trinket"),
            props=entry.get("props", {}),
            description=entry.get("description", ""),
            qty=1,
        )
        if avail is not None:
            new_entry = dict(entry)
            new_entry["qty"] = max(0, int(avail) - 1)
            stock_list[idx] = new_entry
            npc.merchant_stock = stock_list
        _grant_xp(hero, "stealth", 2)
        outcome["stealth_xp"] = int((hero.skills or {}).get("stealth", 0) or 0)
    else:
        mem = hero.memory if isinstance(hero.memory, dict) else {}
        notes = dict(mem.get("npcs", {}))
        npc_entry = dict(notes.get(npc.slug, {}))
        npc_entry["aware_of_theft"] = True
        notes[npc.slug] = npc_entry
        update_memory(db, hero, source="steal_caught", npcs=notes)
        outcome["caught"] = True

    # Stealing always carries a faction cost — caught or not, the act is
    # against the Free Council's order. -3 council rep per attempt.
    _grant_rep(hero, "council", -3)
    outcome["council_rep_delta"] = -3
    return ResolutionResult(True, outcome)
