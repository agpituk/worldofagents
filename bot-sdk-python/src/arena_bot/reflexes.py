"""Declarative reflexes for hero bots.

Each reflex is `{when: <python-expr>, then: <action-dict>}`. The engine evaluates
expressions in order and returns the first matched action, or None if no rule
fires. Reflexes are FREE — no LLM call. They handle the routine 90% of decisions
(routing, travel, deterministic combat moves) and escalate to the LLM for
judgment calls via the special action `{do: invoke_llm}`.

This is the design's signature mechanic: a featherweight player who writes
good reflexes only burns LLM calls on dialogue and tactical targeting, which
is exactly what makes a Pi-hosted small-model hero competitive against a
heavyweight Opus hero.

## Expression language

Plain Python expressions evaluated against a context dict. Available bindings:

  Scalars:    hp, zone, pos_x, pos_y, gold
              <npc_slug>_state         (e.g. marek_state, ghada_state)
              <npc_slug>_visible       (bool)

  Functions:  adjacent_to(slug)        — within manhattan 1 of the NPC
              visible(slug)            — NPC is in perception
              in_inventory(slug)       — item slug is in your inventory
              enemy_in_range()         — any hostile NPC within manhattan 1
              hostile_visible()        — any hostile NPC visible at all
              connection(slug)         — `slug` is an adjacent zone

## Computed actions

The action dict supports a few "compiled" verbs that resolve against perception:

  {do: move_to_npc, slug: marek}        → move(target=marek.pos)
  {do: move_to_nearest_hostile}         → move(target=nearest_hostile.pos)
  {do: invoke_llm}                      → escalate to LLM (handled by Hero.decide)

Anything else passes through as a literal action.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger("arena_bot.reflexes")


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


def _manhattan(a: list[int], b: list[int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class _ReflexLocals(dict):
    """Eval locals that auto-default unknown `<slug>_state` to 'fresh' and
    `<slug>_visible` to False. Lets reflex authors reference NPCs the hero
    hasn't met yet without pre-declaring every possible NPC."""

    def __missing__(self, key: str):
        if key.endswith("_state"):
            return "fresh"
        if key.endswith("_visible"):
            return False
        raise KeyError(key)


def build_context(perception) -> dict[str, Any]:
    """Build the eval context. `perception` is a Perception dataclass."""
    s = perception.your_state
    v = perception.perception
    pos = s.get("pos", [0, 0])
    npcs = v.get("visible_npcs", []) or []
    heroes = v.get("visible_heroes", []) or []
    items = v.get("inventory", []) or []
    visible_items = v.get("visible_items", []) or []
    memory = v.get("memory", {}) or {}
    zone_info = v.get("zone", {}) or {}
    connections = zone_info.get("connections", []) or []
    zone_kind = zone_info.get("kind", "unknown")
    equipped = (s.get("equipped") if isinstance(s.get("equipped"), dict) else {}) or {}

    npc_states = (memory.get("npcs") or {})
    npc_state_vars = {
        f"{slug}_state": (data or {}).get("state", "fresh")
        for slug, data in npc_states.items()
    }
    visible_slugs = {n.get("slug") for n in npcs}
    npc_visible_vars = {
        f"{slug}_visible": (slug in visible_slugs)
        for slug in {*npc_states.keys(), *visible_slugs}
    }

    def adjacent_to(slug: str) -> bool:
        for n in npcs:
            if n.get("slug") == slug:
                return _manhattan(pos, n.get("pos", [0, 0])) <= 1
        return False

    def visible(slug: str) -> bool:
        return any(n.get("slug") == slug for n in npcs)

    def in_inventory(slug: str) -> bool:
        return any(i.get("slug") == slug for i in items)

    def enemy_in_range() -> bool:
        return any(
            n.get("hostility") == "hostile"
            and _manhattan(pos, n.get("pos", [0, 0])) <= 1
            for n in npcs
        )

    def hostile_visible() -> bool:
        return any(n.get("hostility") == "hostile" for n in npcs)

    def connection(slug: str) -> bool:
        return slug in connections

    def visible_hero(name: str) -> bool:
        return any(h.get("name") == name for h in heroes)

    def any_hero_visible() -> bool:
        return len(heroes) > 0

    def adjacent_to_hero(name: str | None = None) -> bool:
        for h in heroes:
            if name is not None and h.get("name") != name:
                continue
            if _manhattan(pos, h.get("pos", [0, 0])) <= 1:
                return True
        return False

    def any_hero_adjacent() -> bool:
        return any(_manhattan(pos, h.get("pos", [0, 0])) <= 1 for h in heroes)

    def in_pvp_zone() -> bool:
        return zone_kind != "sanctuary" and zone_kind != "unknown"

    memory_tags = set(v.get("memory_tags") or [])

    def recalled(tag: str) -> bool:
        """Has this tag ever appeared in the hero's journal? Cheap, free,
        works for milestones (e.g. recalled('death')) and player-curated
        tags (e.g. recalled('marek_promise'))."""
        return tag in memory_tags

    def recalled_any(*tags_args: str) -> bool:
        return any(t in memory_tags for t in tags_args)

    def weapon_equipped() -> bool:
        return bool(equipped.get("weapon"))

    def armor_equipped() -> bool:
        return bool(equipped.get("armor"))

    def item_at_my_tile(slot: str | None = None) -> str | None:
        """Return the slug of an item on my exact tile, optionally filtered by
        equipment slot ('weapon'/'armor'). None if nothing matches."""
        for it in visible_items:
            ip = it.get("pos") or [None, None]
            if ip != pos:
                continue
            if slot is not None and it.get("slot") != slot:
                continue
            return it.get("slug")
        return None

    def visible_item_kind(kind: str) -> bool:
        return any(it.get("kind") == kind for it in visible_items)

    ctx = _ReflexLocals()
    ctx.update({
        # Scalars
        "hp": s.get("hp"),
        "zone": s.get("zone"),
        "zone_kind": zone_kind,
        "pos_x": pos[0],
        "pos_y": pos[1],
        "gold": int(memory.get("gold", 0) or 0),
        # NPC state shorthands (override the default 'fresh' for known NPCs)
        **npc_state_vars,
        **npc_visible_vars,
        # Helpers
        "adjacent_to": adjacent_to,
        "visible": visible,
        "in_inventory": in_inventory,
        "enemy_in_range": enemy_in_range,
        "hostile_visible": hostile_visible,
        "connection": connection,
        "visible_hero": visible_hero,
        "any_hero_visible": any_hero_visible,
        "adjacent_to_hero": adjacent_to_hero,
        "any_hero_adjacent": any_hero_adjacent,
        "in_pvp_zone": in_pvp_zone,
        "weapon_equipped": weapon_equipped,
        "armor_equipped": armor_equipped,
        "item_at_my_tile": item_at_my_tile,
        "visible_item_kind": visible_item_kind,
        "equipped": equipped,
        "memory_tags": memory_tags,
        "recalled": recalled,
        "recalled_any": recalled_any,
        "_perception": perception,
    })
    return ctx


# ---------------------------------------------------------------------------
# Computed-verb resolver
# ---------------------------------------------------------------------------


def _nearest_hostile(perception):
    pos = perception.your_state.get("pos", [0, 0])
    hostiles = [
        n for n in (perception.perception.get("visible_npcs") or [])
        if n.get("hostility") == "hostile"
    ]
    if not hostiles:
        return None
    return min(hostiles, key=lambda n: _manhattan(pos, n.get("pos", [0, 0])))


def _nearest_hero(perception):
    pos = perception.your_state.get("pos", [0, 0])
    heroes = perception.perception.get("visible_heroes") or []
    if not heroes:
        return None
    return min(heroes, key=lambda h: _manhattan(pos, h.get("pos", [0, 0])))


def _nearest_hostile_pos(perception) -> list[int] | None:
    n = _nearest_hostile(perception)
    return list(n.get("pos", [0, 0])) if n else None


def _npc_pos(perception, slug: str) -> list[int] | None:
    for n in perception.perception.get("visible_npcs") or []:
        if n.get("slug") == slug:
            return list(n.get("pos", [0, 0]))
    return None


def resolve_action(action: dict[str, Any], perception) -> dict[str, Any]:
    verb = action.get("do")
    if verb == "move_to_npc":
        slug = action.get("slug")
        target = _npc_pos(perception, slug) if slug else None
        return {"do": "move", "target": target} if target else {"do": "wait"}
    if verb == "move_to_nearest_hostile":
        target = _nearest_hostile_pos(perception)
        return {"do": "move", "target": target} if target else {"do": "wait"}
    if verb == "attack_nearest_hostile":
        n = _nearest_hostile(perception)
        return {"do": "attack", "target": n["slug"]} if n else {"do": "wait"}
    if verb == "move_to_nearest_hero":
        h = _nearest_hero(perception)
        return {"do": "move", "target": list(h.get("pos", [0, 0]))} if h else {"do": "wait"}
    if verb == "attack_nearest_hero":
        h = _nearest_hero(perception)
        return {"do": "attack_hero", "target": h["name"]} if h else {"do": "wait"}
    return action


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


INVOKE_LLM = "invoke_llm"


class ReflexEngine:
    def __init__(self, specs: list[dict[str, Any]]):
        self.specs = specs or []

    def evaluate(self, perception) -> dict[str, Any] | None:
        action, _debug = self.evaluate_with_debug(perception)
        return action

    def evaluate_with_debug(self, perception) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Returns (action, debug_info). debug_info names the index, the `when`
        expression, and the resolved action — for the spectator UI's reflex
        debugger and for player iteration."""
        ctx = build_context(perception)
        for i, spec in enumerate(self.specs):
            expr = spec.get("when")
            if not expr:
                continue
            try:
                matched = bool(eval(expr, {"__builtins__": {}}, ctx))  # noqa: S307
            except Exception as exc:
                log.warning("reflex %d ('%s') eval error: %s", i, expr, exc)
                continue
            if not matched:
                continue
            then = spec.get("then") or {"do": "wait"}
            if not isinstance(then, dict) or "do" not in then:
                log.warning("reflex %d 'then' malformed: %r", i, then)
                continue
            log.debug("reflex %d fired: %s", i, then)
            debug = {"reflex_index": i, "when": expr, "then": dict(then)}
            if then["do"] == INVOKE_LLM:
                return then, debug
            resolved = resolve_action(dict(then), perception)
            debug["resolved"] = resolved
            return resolved, debug
        return None, None
