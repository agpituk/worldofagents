"""Templated narrator.

Turns raw event payloads into short prose lines for the spectator stream.
Pure function — no DB, no model. Returns None if an event isn't worth narrating
(skipping miss-spam keeps the stream readable).

Once a real LLM is wired into the gateway, narration can be elevated by
sending the raw event + prior context through it. This template version is
the always-available fallback and the v0.3 baseline.
"""

from __future__ import annotations

from typing import Any

# Pretty names for NPCs we know about. Falls back to slug.title() otherwise.
_NPC_NAMES = {
    "marek": "Marek",
    "ghada": "Captain Ghada",
    "rat_a": "the plague-stained rat",
    "rat_b": "the plague-stained rat",
    "rat_c": "the plague-stained rat",
}


def _name(slug: str | None) -> str:
    if slug is None:
        return "someone"
    return _NPC_NAMES.get(slug, slug.replace("_", " ").title())


def _item_pretty(slug: str | None) -> str:
    if not slug:
        return "thing"
    return slug.replace("_", " ")


def narrate(event: dict[str, Any]) -> str | None:
    kind = event.get("kind")
    payload = event.get("payload", {}) or {}

    if kind == "npc.reaction":
        npc = payload.get("npc")
        for eff in payload.get("effects", []):
            if "speak" in eff:
                return f'{_name(npc)}: "{eff["speak"]}"'
            if "gave_item" in eff:
                return f'{_name(npc)} hands over a {_item_pretty(eff["gave_item"])}.'
        return None

    if kind == "npc.received":
        npc = payload.get("npc")
        item = payload.get("item")
        return f'{_name(npc)} takes the {_item_pretty(item)}.'

    if kind == "mob.attack":
        mob = _name(payload.get("mob"))
        target = payload.get("target_name", "the hero")
        if payload.get("fumble"):
            return f"{mob} stumbles."
        if payload.get("died"):
            return f"{mob} drops {target} with a final blow. {target} falls."
        if payload.get("hit"):
            crit = " A vicious bite!" if payload.get("crit") else ""
            return f"{mob} bites {target} for {payload['damage']} damage.{crit}"
        # Miss — only narrate if defending (so the defend mechanic shows up).
        if payload.get("defending"):
            return f"{target} braces; {mob}'s attack skitters off."
        return None

    if kind == "action.resolved":
        outcome = payload.get("outcome") or {}
        verb = outcome.get("verb")

        if verb == "attack":
            target = _name(outcome.get("target"))
            if outcome.get("killed"):
                return f"{target} falls. Loot drops to the floor."
            if outcome.get("fumble"):
                return f"A fumble — the strike at {target} goes wide."
            if outcome.get("crit"):
                return f"A critical strike on {target} for {outcome['damage']} damage!"
            if outcome.get("hit"):
                return f"The blow lands on {target} for {outcome['damage']} damage."
            return None  # boring miss

        if verb == "attack_hero":
            target = outcome.get("target", "the hero")
            if outcome.get("killed"):
                loot = outcome.get("looted_gold", 0)
                tail = f" {loot} gold changes hands." if loot else ""
                return f"{target} falls — slain by another hero.{tail}"
            if outcome.get("fumble"):
                return f"A fumble — the swing at {target} sails wide."
            if outcome.get("crit"):
                return f"A critical PvP strike on {target} for {outcome['damage']} damage!"
            if outcome.get("hit"):
                return f"PvP: {outcome['damage']} damage dealt to {target}."
            return None

        if verb == "travel":
            return f"A traveller passes from {outcome.get('from')} to {outcome.get('to')}."

        if verb == "give":
            return f"A {_item_pretty(outcome.get('item', 'thing'))} changes hands."

        if verb == "flee":
            fleeing_from = outcome.get("fleeing_from")
            if fleeing_from:
                return f"Footsteps retreat from {_name(fleeing_from)}."
            return None

        if verb == "say":
            # The matching npc.reaction already narrates the dialogue. Skip.
            return None

        # wait, look, examine, pickup, drop, defend, move — usually too quiet to narrate.
        return None

    return None
