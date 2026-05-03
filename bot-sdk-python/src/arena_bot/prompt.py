"""LLM prompt builders for the hero loop.

Two flavours:
  • `build_action_prompt` — legacy free-text path, includes the full verb
    cheatsheet inline.
  • `build_tool_action_prompt` — tool-calling path, expects the verb
    cheatsheet to live in the tool specs themselves.
"""

from __future__ import annotations

import json
from typing import Any

from arena_bot.types import Perception


_ACTIONS_HELP = """ACTIONS — output EXACTLY ONE as a single-line JSON object. No prose, no fences.

attack — Strike a hostile mob in melee. USE THIS whenever a hostile is at
  manhattan distance ≤ 1 (look for entries in visible_npcs where
  hostility == "hostile" and the pos differs from yours by at most 1 in either
  axis). Hostile mobs WILL hit you back every tick you don't kill them, so
  attacking is almost always better than waiting or moving when an enemy is in
  melee range. Picks the slug from visible_npcs.
    {"do":"attack","target":"<hostile_npc_slug>"}

move — Walk to a tile in your CURRENT zone (within zone size). Use when
  you need to close distance on a target who is visible but not adjacent.
  Do NOT move if an enemy is already adjacent — attack instead. Do NOT use
  to leave the zone (use travel for that).
    {"do":"move","target":[x,y]}

travel — Walk to an ADJACENT zone (must be in zone_info.connections). Use
  when the entity you need is in another zone and your current zone has it
  in its connections list. Cheaper than wandering.
    {"do":"travel","zone":"<adjacent_zone_slug>"}

say — Speak aloud. Adjacent NPCs (manhattan ≤ 1) hear you and may react
  based on keywords in your message. Use to greet NPCs, accept/decline
  quests, ask questions. Keep messages short and direct.
    {"do":"say","message":"Hello, Marek."}

give — Hand an item from your inventory to an adjacent NPC. Use to deliver
  quest items. The NPC must be at manhattan distance ≤ 1 and the item must
  be in your inventory list.
    {"do":"give","target":"<npc_slug>","item":"<item_slug>"}

defend — +5 AC for the rest of this tick. Use when you expect to be hit
  but can't yet attack back (e.g. multiple enemies adjacent, low HP).
    {"do":"defend"}

flee — Step away from the nearest hostile. Use when HP is critically low
  and you cannot win the next exchange.
    {"do":"flee"}

examine — Inspect an NPC or item to learn details. Cheap intel; use sparingly.
    {"do":"examine","target":"<slug>"}

pickup — Grab an item on your current tile (must be in visible_items at
  your pos with no owner).
    {"do":"pickup","slug":"<item_slug>"}

drop — Drop an item from inventory at your current tile.
    {"do":"drop","slug":"<item_slug>"}

look — Refresh perception (rarely needed; perception arrives every tick).
    {"do":"look"}

wait — Skip the tick. Only when nothing else applies.
    {"do":"wait"}

DECISION RULES (apply in this order each tick):
  1. If your HP is ≤ 8: {"do":"flee"}
  2. If a hostile is in melee range (manhattan ≤ 1 from you): ATTACK it. Do not move.
  3. If a hostile is visible but not adjacent: move toward its pos.
  4. If you're adjacent to a quest NPC and have something to say: say it.
  5. If you're adjacent to a quest NPC and you should hand something over: give.
  6. If the entity you need is in another zone (check zone_info.connections): travel.
  7. Otherwise: move toward your goal or wait.

EXAMPLES:
  Hostile rat at [3,3], you at [3,3] (same tile, manhattan 0):
    {"do":"attack","target":"rat_a"}
  Hostile rat at [5,4], you at [5,3] (adjacent, manhattan 1):
    {"do":"attack","target":"rat_a"}
  Hostile rat at [5,5], you at [3,3] (visible, not adjacent):
    {"do":"move","target":[5,5]}
  Marek visible at [4,4], you at [4,3], marek_state fresh:
    {"do":"say","message":"Hello, Marek."}
  Carrying mareks_sealed_package, ghada at [4,4], you at [4,4]:
    {"do":"give","target":"ghada","item":"mareks_sealed_package"}"""


def build_tool_action_prompt(
    *,
    name: str,
    bio: str,
    goal: str,
    perception: Perception,
    system_summary: str = "",
) -> tuple[str, str]:
    """Prompt for tool-calling mode. The tool list itself documents the verbs
    (rich docstrings on each function), so the system prompt is intentionally
    short — identity, goal, and a directive to call exactly one tool.

    `system_summary` is durable, manifest-declared persona context (e.g. "I
    hate the Embered. I owe Marek 30g.") that survives across ticks, model
    swaps, and crashes — it's hero-shaped state the player baked into the
    YAML, not transient perception."""
    system = (
        f"You are {name}. {bio}\n\n"
        f"Goal: {goal}\n\n"
        + (f"What you carry with you, always:\n{system_summary}\n\n" if system_summary else "")
        + "Each tick you must call EXACTLY ONE tool. Read the situation in the "
        "user message carefully — especially `you.pos`, `visible_npcs`, "
        "`zone_info.connections`, `inventory`, `memory`, and "
        "`journal_relevant` (memories pulled from your past that matter "
        "right now) — and pick the single most appropriate action.\n\n"
        "Critical rules:\n"
        "  • If a hostile NPC is at manhattan distance ≤ 1 from you: call attack.\n"
        "  • If your HP is ≤ 8: call flee.\n"
        "  • If you need to be in another zone: call travel (only to a zone in connections).\n"
        "  • If a quest NPC is adjacent and the dialogue should advance: call say.\n"
    )

    s = perception.your_state
    v = perception.perception
    you_pos = s.get("pos") or [0, 0]

    def _annotate(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Attach a precomputed manhattan distance + a human-readable
        in_melee_range flag. Saves the model from doing arithmetic, which
        small models reliably get wrong."""
        out = []
        for e in entities or []:
            ep = e.get("pos") or [0, 0]
            dist = abs(ep[0] - you_pos[0]) + abs(ep[1] - you_pos[1])
            out.append({**e, "manhattan_to_you": dist, "in_melee_range": dist <= 1})
        return out

    user = json.dumps(
        {
            "tick_id": perception.tick_id,
            "you": {
                "name": s.get("name"),
                "hp": s.get("hp"),
                "zone": s.get("zone"),
                "pos": you_pos,
            },
            "zone_info": v.get("zone"),
            "visible_npcs": _annotate(v.get("visible_npcs", [])),
            "visible_items": _annotate(v.get("visible_items", [])),
            "visible_heroes": _annotate(v.get("visible_heroes", [])),
            "inventory": v.get("inventory", []),
            "memory": v.get("memory", {}),
            "journal_relevant": v.get("journal_relevant", []),
            "recent_events": [
                {"kind": e.get("kind"), "payload": e.get("payload")}
                for e in (v.get("recent_events", []) or [])[:6]
            ],
        },
        ensure_ascii=False,
    )
    return system, user + (
        "\n\nCall ONE tool now. If any visible_npcs entry has "
        "in_melee_range == true AND hostility == \"hostile\", you MUST attack "
        "that one (use its slug as target)."
    )


def build_action_prompt(
    *,
    name: str,
    bio: str,
    goal: str,
    perception: Perception,
) -> tuple[str, str]:
    system = f"""You are {name}. {bio}

You play a hero in a turn-based fantasy MMO. Each tick you choose ONE action.
Goal: {goal}

{_ACTIONS_HELP}"""

    s = perception.your_state
    v = perception.perception
    user = json.dumps(
        {
            "tick_id": perception.tick_id,
            "you": {
                "name": s.get("name"),
                "hp": s.get("hp"),
                "zone": s.get("zone"),
                "pos": s.get("pos"),
            },
            "zone_info": v.get("zone"),
            "visible_npcs": v.get("visible_npcs", []),
            "visible_items": v.get("visible_items", []),
            "visible_heroes": v.get("visible_heroes", []),
            "inventory": v.get("inventory", []),
            "memory": v.get("memory", {}),
            "recent_events": [
                {"kind": e.get("kind"), "payload": e.get("payload")}
                for e in (v.get("recent_events", []) or [])[:8]
            ],
        },
        ensure_ascii=False,
    )
    return system, user + "\n\nReturn your one JSON action."
