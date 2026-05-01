"""Scripted NPC behaviors.

Each NPC slug has a function that takes (hero, message) and returns a list of
*effects* the world applies. v0.2 supports two effect kinds:

  {"speak": "<message>"}                   — NPC says something back, recorded
                                             as an event the hero will see in
                                             their next perception
  {"give_item": {"slug": ..., "name": ..., "kind": ..., "description": ...}}
                                             — NPC creates an item owned by the hero

Quest state lives in `hero.memory["npcs"][slug]` so each NPC carries its own
relationship key with the hero, no cross-pollution.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

import logging

from sqlalchemy import select

from app.core.models import Hero, Item, NPC

log = logging.getLogger("world.npc.behaviors")

Effect = dict[str, Any]


def _hero_state_for(hero: Hero, slug: str) -> str:
    by_npc = hero.memory.get("npcs", {}) if isinstance(hero.memory, dict) else {}
    state = by_npc.get(slug, {}).get("state", "fresh")
    return state


def _set_hero_state(hero: Hero, slug: str, new_state: str) -> None:
    memory = dict(hero.memory) if isinstance(hero.memory, dict) else {}
    by_npc = dict(memory.get("npcs", {}))
    npc_entry = dict(by_npc.get(slug, {}))
    npc_entry["state"] = new_state
    by_npc[slug] = npc_entry
    memory["npcs"] = by_npc
    hero.memory = memory  # full reassign so SQLAlchemy sees a change on JSON


def _create_item_for(db: Session, hero: Hero, spec: dict[str, Any]) -> Item:
    item = Item(
        id=uuid.uuid4(),
        slug=spec["slug"],
        name=spec["name"],
        kind=spec.get("kind", "trinket"),
        description=spec.get("description", ""),
        props=spec.get("props", {}),
        owner_hero_id=hero.id,
        zone=None,
        pos_x=None,
        pos_y=None,
    )
    db.add(item)
    return item


# -----------------------------------------------------------------------------
# Marek
# -----------------------------------------------------------------------------


def _marek_react(hero: Hero, message: str) -> list[Effect]:
    msg = message.lower().strip()
    state = _hero_state_for(hero, "marek")

    if state == "fresh":
        if any(g in msg for g in ("hello", "hi", "greetings", "marek")):
            return [
                {
                    "speak": (
                        f"Adventurer. Sit, sit — I won't keep you. My old friend Ghada at the Watch "
                        f"is owed a delivery. A small sealed thing. Will you carry it for me, "
                        f"{hero.name.split()[0]}?"
                    )
                },
                {"set_state": "asked"},
            ]
        return [{"speak": "Hmph. Take a seat or take the door, traveller."}]

    if state == "asked":
        accept_words = (
            "yes", "yeah", "aye", "sure", "ok", "okay", "alright", "deal", "fine",
            "i will", "i'll", "ill", "carry", "take it", "take the", "deliver",
            "of course", "happily", "consider it",
        )
        if any(y in msg for y in accept_words):
            return [
                {
                    "give_item": {
                        "slug": "mareks_sealed_package",
                        "name": "Marek's Sealed Package",
                        "kind": "delivery",
                        "description": "A palm-sized package wrapped in waxed cloth. Light. Sealed.",
                        "props": {"deliver_to": "ghada", "given_by": "marek"},
                    }
                },
                {"speak": "Good. Take it to Ghada at the Watchman's Bastion. Tell her Marek sent you."},
                {"set_state": "carrying"},
            ]
        if any(n in msg for n in ("no", "not", "later", "decline")):
            return [{"speak": "Suit yourself. The offer stands if you change your mind."}]
        return [{"speak": "Yes or no, traveller. I'm not getting any younger."}]

    if state == "carrying":
        return [{"speak": "Off you go then. Ghada's at the Bastion."}]

    if state == "delivered":
        return [{"speak": "Aye, safe travels. Drink's on the house when you're back."}]

    return [{"speak": "..."}]


# -----------------------------------------------------------------------------
# Dispatch
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Ghada
# -----------------------------------------------------------------------------


def _ghada_react(hero: Hero, message: str) -> list[Effect]:
    msg = message.lower().strip()
    state = _hero_state_for(hero, "ghada")

    if state == "fresh":
        greet_words = ("hello", "hi", "hey", "greetings", "marek", "package", "delivery", "well met", "good day")
        if any(g in msg for g in greet_words):
            return [
                {
                    "speak": (
                        "State your business. If Marek sent you with a package, hand it over — "
                        "I'm not a courier dispatcher."
                    )
                },
                {"set_state": "expecting"},
            ]
        return [{"speak": "The Bastion's busy. Speak plainly or move along."}]

    if state == "expecting":
        return [{"speak": "Less talk. Hand me the package."}]

    if state == "received":
        return [{"speak": "Tell Marek I owe him a drink. Bounty board's on the wall when you want work."}]

    return [{"speak": "..."}]


def _ghada_react_to_item(hero: Hero, item: Item) -> list[Effect]:
    if item.slug != "mareks_sealed_package":
        return [{"speak": "I've no use for that. Take it back."}]
    return [
        {"speak": "Aye, that's Marek's hand. My thanks. Here — for your trouble."},
        {"set_state": "received"},
        {"set_state_for": ("marek", "delivered")},
        {"reward_gold": 25},
        {"grant_rep": ("council", 5)},  # solid for the Free Council
        {"grant_rep": ("wardens", 2)},  # mild for the Codex Wardens
        {"consume_item": str(item.id)},
    ]


# -----------------------------------------------------------------------------
# Dispatch
# -----------------------------------------------------------------------------

_SAY_HANDLERS = {
    "marek": _marek_react,
    "ghada": _ghada_react,
}

_RECV_HANDLERS = {
    "ghada": _ghada_react_to_item,
}


def react_to_say(db: Session, npc: NPC, hero: Hero, message: str) -> list[Effect]:
    # If the NPC has an LLM persona configured, use it. The world calls the
    # gateway server-side with the persona + recent dialogue context and parses
    # the structured response into Effects. Falls back to scripted handler on
    # any error or if no persona set.
    if npc.llm_persona:
        try:
            effects = _react_via_llm(db, npc, hero, message)
            if effects:
                return effects
        except Exception as exc:  # network / parse / etc.
            log.warning("LLM react failed for %s (%s) — falling back to scripted", npc.slug, exc)
    handler = _SAY_HANDLERS.get(npc.slug)
    if handler is None:
        return []
    return handler(hero, message)


def _react_via_llm(db: Session, npc: NPC, hero: Hero, message: str) -> list[Effect]:
    """Call the LLM gateway with the NPC's persona + the hero's message. Parse
    a JSON-shape response (`{speak, set_state?, give_item?}`) into Effects."""
    import json
    import os
    import urllib.request

    state = _hero_state_for(hero, npc.slug)
    inventory_summary = ", ".join(
        sorted({it.slug for it in hero.memory.get("inventory_seen", [])})  # type: ignore[union-attr]
    ) if isinstance(hero.memory, dict) else ""

    system = (
        f"You are {npc.name}. {npc.llm_persona}\n\n"
        f"Current dialogue state with this hero: {state}.\n"
        "Respond IN CHARACTER to whatever the hero just said. Keep your speech "
        "to 1-2 short sentences. If the conversation should advance to a new "
        "state, set it. If you should hand them something, give_item. If a "
        "faction should care, grant_rep.\n\n"
        "Output a JSON object only, with these optional fields:\n"
        "  speak (str)        — what you say back\n"
        "  set_state (str)    — new dialogue state (e.g. 'asked', 'carrying', 'delivered')\n"
        "  give_item (object) — {slug, name, kind, description?, props?}\n"
        "  grant_rep (object) — {faction: <amount>}, e.g. {\"council\": 1}\n"
        "No prose outside the JSON."
    )
    user = (
        f"Hero \"{hero.name}\" (HP {hero.hp}, gold {(hero.memory or {}).get('gold', 0)}, "
        f"inventory: {inventory_summary}) says: {message!r}"
    )

    gateway_url = os.environ.get("GATEWAY_BASE_URL", "http://llm-gateway:8001").rstrip("/")
    payload = {
        "hero_id": str(hero.id),
        "model": "qwen3-4b",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": 200,
    }
    req = urllib.request.Request(
        f"{gateway_url}/think",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    completion = (body.get("completion") or "").strip()

    parsed = _try_parse_json_object(completion)
    if not parsed:
        return [{"speak": completion[:280]}] if completion else []

    out: list[Effect] = []
    if parsed.get("speak"):
        out.append({"speak": str(parsed["speak"])[:280]})
    if parsed.get("set_state"):
        out.append({"set_state": str(parsed["set_state"])[:32]})
    if isinstance(parsed.get("give_item"), dict):
        out.append({"give_item": parsed["give_item"]})
    grant = parsed.get("grant_rep")
    if isinstance(grant, dict):
        for faction, amount in grant.items():
            try:
                out.append({"grant_rep": (str(faction)[:32], int(amount))})
            except (TypeError, ValueError):
                continue
    return out


def _try_parse_json_object(text: str) -> dict | None:
    import json
    import re
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", text, re.DOTALL)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, dict) else None


def react_to_receive(db: Session, npc: NPC, hero: Hero, item: Item) -> list[Effect]:
    handler = _RECV_HANDLERS.get(npc.slug)
    if handler is None:
        return []
    return handler(hero, item)


def apply_effects(db: Session, npc: NPC, hero: Hero, effects: list[Effect]) -> list[dict[str, Any]]:
    """Apply NPC effects, mutate world state, return summaries for the event log."""
    summaries: list[dict[str, Any]] = []
    for eff in effects:
        if "speak" in eff:
            summaries.append({"npc": npc.slug, "speak": eff["speak"]})
        if "set_state" in eff:
            _set_hero_state(hero, npc.slug, eff["set_state"])
            summaries.append({"npc": npc.slug, "state": eff["set_state"]})
        if "set_state_for" in eff:
            other_slug, new_state = eff["set_state_for"]
            _set_hero_state(hero, other_slug, new_state)
            summaries.append({"npc": other_slug, "state": new_state, "indirect": True})
        if "give_item" in eff:
            item = _create_item_for(db, hero, eff["give_item"])
            summaries.append({"npc": npc.slug, "gave_item": item.slug, "item_id": str(item.id)})
        if "grant_rep" in eff:
            faction, amount = eff["grant_rep"]
            rep = dict(hero.faction_rep) if isinstance(hero.faction_rep, dict) else {}
            rep[faction] = int(rep.get(faction, 0) or 0) + int(amount)
            hero.faction_rep = rep
            summaries.append({"npc": npc.slug, "rep_faction": faction, "rep_delta": int(amount)})
        if "reward_gold" in eff:
            # Hero gold field doesn't exist yet — record it for now, wire to a column later.
            memory = dict(hero.memory) if isinstance(hero.memory, dict) else {}
            memory["gold"] = int(memory.get("gold", 0)) + int(eff["reward_gold"])
            hero.memory = memory
            summaries.append({"npc": npc.slug, "reward_gold": eff["reward_gold"], "total_gold": memory["gold"]})
        if "consume_item" in eff:
            item_id = eff["consume_item"]
            try:
                target = db.scalar(select(Item).where(Item.id == item_id))
                if target is not None:
                    db.delete(target)
                    summaries.append({"npc": npc.slug, "consumed_item": item_id})
            except Exception:  # pragma: no cover
                summaries.append({"npc": npc.slug, "consumed_item": item_id, "error": "delete failed"})
    return summaries
