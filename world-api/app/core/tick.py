"""The world tick scheduler.

Each tick:
  1. Drain pending actions submitted since last tick
  2. Resolve them in DEX-initiative order (out-of-combat for now)
  3. Run NPC reactions for `say` actions adjacent to NPCs
  4. Persist hero state changes + events
  5. Build and push the next perception to every connected agent
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.actions import defending_this_tick, perception_for, resolve
from app.core.combat import run_mob_phase
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.gateway_permission import issue_permission_token
from app.core.hero_budgets import mana_regen_per_tick, max_tokens_per_tick
from app.core.models import NPC, Event, Hero, Item, Tick
from app.domains.npc.behaviors import apply_effects, react_to_receive, react_to_say

logger = logging.getLogger("world.tick")


class TickEngine:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler()
        self.current_tick: int = 0
        self._connections: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._pending_actions: dict[str, dict[str, Any]] = {}
        # Spectator subscribers, keyed by zone slug. Multiple subscribers per zone OK.
        self._zone_subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}

    # --- agent connection registry -------------------------------------------------

    def register_agent(self, hero_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=8)
        self._connections[hero_id] = queue
        logger.info("agent connected: %s (total=%d)", hero_id, len(self._connections))
        return queue

    def unregister_agent(self, hero_id: str) -> None:
        self._connections.pop(hero_id, None)
        self._pending_actions.pop(hero_id, None)
        logger.info("agent disconnected: %s (total=%d)", hero_id, len(self._connections))

    def is_connected(self, hero_id: str) -> bool:
        return hero_id in self._connections

    def submit_action(self, hero_id: str, action_msg: dict[str, Any]) -> None:
        self._pending_actions[hero_id] = action_msg

    # --- spectator subscriptions --------------------------------------------------

    def subscribe_zone(self, zone_slug: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._zone_subscribers.setdefault(zone_slug, []).append(queue)
        logger.info("spectator joined %s (total=%d)", zone_slug, len(self._zone_subscribers[zone_slug]))
        return queue

    def unsubscribe_zone(self, zone_slug: str, queue: asyncio.Queue) -> None:
        subs = self._zone_subscribers.get(zone_slug)
        if subs and queue in subs:
            subs.remove(queue)
            if not subs:
                self._zone_subscribers.pop(zone_slug, None)

    # --- lifecycle ----------------------------------------------------------------

    def start(self) -> None:
        # Resume the tick counter from the DB so restarts don't reset the
        # event log's monotonic order.
        from sqlalchemy import func, select as _sel
        with SessionLocal() as db:
            last = db.scalar(_sel(func.max(Tick.id))) or 0
            self.current_tick = int(last)
        logger.info("resuming tick counter at %d", self.current_tick)

        self.scheduler.add_job(
            self._tick,
            "interval",
            seconds=settings.world_tick_seconds,
            id="world-tick",
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.start()
        logger.info("tick engine started (every %.1fs)", settings.world_tick_seconds)

    def shutdown(self) -> None:
        self.scheduler.shutdown(wait=False)

    # --- the tick itself ----------------------------------------------------------

    async def _tick(self) -> None:
        self.current_tick += 1
        tick_id = self.current_tick

        pending = self._pending_actions
        self._pending_actions = {}
        defending_this_tick.clear()

        with SessionLocal() as db:
            db.add(Tick(notes=f"tick #{tick_id}"))

            # Mana regen — INT-scaled per tick up to mana_max for every alive hero.
            for h in db.scalars(select(Hero).where(Hero.status == "alive")):
                if h.mana_current < h.mana_max:
                    h.mana_current = min(h.mana_max, h.mana_current + mana_regen_per_tick(h))

            # Faction invasions: every 240 ticks the Embered raise their dead.
            from app.domains.npc.seed import respawn_invasion_mobs
            respawned = respawn_invasion_mobs(db, tick_id)
            if respawned:
                logger.info("tick %d: invasion respawned %d mobs", tick_id, respawned)

            # Resolve tournaments whose window just ended.
            from app.domains.tournament.close import close_due_tournaments
            close_due_tournaments(db, tick_id)

            # World events — calendar layer. Spawns/despawns the Wyrm,
            # opens and closes faction tides on a 7000-tick cadence.
            from app.domains.world_event.wyrm import tick_wyrm
            from app.domains.world_event.faction_tide import tick_faction_tide
            tick_wyrm(db, tick_id)
            tick_faction_tide(db, tick_id)

            heroes = db.scalars(select(Hero).where(Hero.status == "alive")).all()
            heroes_sorted = sorted(heroes, key=lambda h: (-h.dex, -h.int_, str(h.id)))

            resolved_count = 0
            for hero in heroes_sorted:
                msg = pending.get(str(hero.id))
                if msg is None:
                    continue
                action = msg.get("action") or {}
                result = resolve(db, hero, action)
                resolved_count += 1
                db.add(
                    Event(
                        tick_id=tick_id,
                        hero_id=hero.id,
                        zone=hero.zone,
                        kind="action.resolved",
                        payload={
                            "action": action,
                            "ok": result.ok,
                            "outcome": result.outcome,
                            "kind": msg.get("kind"),
                            "debug": msg.get("debug"),
                        },
                    )
                )

                # Surface dispatcher-level validation failures
                # (unknown verb, bad arg shape) as parse_failure rows so
                # the spectator UI renders all "wasted ticks" with one
                # path, regardless of where in the stack they fail.
                _server_side_failures = {"unknown_verb", "bad_action_shape"}
                if not result.ok and result.outcome.get("reason") in _server_side_failures:
                    db.add(
                        Event(
                            tick_id=tick_id,
                            hero_id=hero.id,
                            zone=hero.zone,
                            kind="parse_failure",
                            payload={
                                "reason": result.outcome["reason"],
                                "error": result.outcome.get("error"),
                                "raw_output": str(action)[:500],
                                "fallback_action": {"do": "wait"},
                            },
                        )
                    )

                # NPC reactions: on a successful `say`, run scripted handlers
                # for every NPC within radius 1, in the same tick.
                if result.ok and action.get("do") == "say":
                    heard_by = result.outcome.get("heard_by_npcs", [])
                    for npc_slug in heard_by:
                        npc = db.get(NPC, npc_slug)
                        if npc is None:
                            continue
                        effects = react_to_say(db, npc, hero, action.get("message", ""))
                        if not effects:
                            continue
                        summaries = apply_effects(db, npc, hero, effects)
                        db.add(
                            Event(
                                tick_id=tick_id,
                                hero_id=hero.id,
                                zone=hero.zone,
                                kind="npc.reaction",
                                payload={"npc": npc.slug, "to_message": action.get("message"), "effects": summaries},
                            )
                        )

                # NPC reception: on a successful `give` to an NPC, the NPC reacts to the item.
                if result.ok and action.get("do") == "give":
                    # Flush so the just-mutated item (owner_hero_id=None, props.held_by_npc=...)
                    # is visible to the lookup query. Session has autoflush=False.
                    db.flush()
                    npc_slug = result.outcome.get("to")
                    item_slug = result.outcome.get("item")
                    if npc_slug and item_slug:
                        npc = db.get(NPC, npc_slug)
                        from sqlalchemy import select as _sel
                        item = db.scalar(
                            _sel(Item).where(
                                Item.slug == item_slug,
                                Item.owner_hero_id.is_(None),
                                Item.props["held_by_npc"].as_string() == npc_slug,
                            )
                        )
                        if npc is not None and item is not None:
                            effects = react_to_receive(db, npc, hero, item)
                            if effects:
                                summaries = apply_effects(db, npc, hero, effects)
                                db.add(
                                    Event(
                                        tick_id=tick_id,
                                        hero_id=hero.id,
                                        zone=hero.zone,
                                        kind="npc.received",
                                        payload={"npc": npc.slug, "item": item_slug, "effects": summaries},
                                    )
                                )

            # Mob retaliation phase — runs after all hero actions this tick.
            db.flush()  # make sure heroes' new positions are visible to mob adjacency check
            mob_results = run_mob_phase(db)
            for payload in mob_results:
                db.add(
                    Event(
                        tick_id=tick_id,
                        hero_id=None,
                        zone=None,
                        kind="mob.attack",
                        payload=payload,
                    )
                )
                if payload.get("died"):
                    target_id = payload.get("target_hero_id")
                    if target_id:
                        target_uuid = uuid.UUID(target_id) if isinstance(target_id, str) else target_id
                        db.add(
                            Event(
                                tick_id=tick_id,
                                hero_id=target_uuid,
                                zone=None,
                                kind="hero.died",
                                payload={
                                    "killer": payload.get("mob"),
                                    "killer_kind": "mob",
                                    "name": payload.get("target_name"),
                                },
                            )
                        )
                        # Final journal entry — the death page reads from this.
                        from app.core.models import JournalEntry
                        db.add(
                            JournalEntry(
                                hero_id=target_uuid,
                                tick_id=tick_id,
                                kind="milestone",
                                text=f"Died at the hands of {payload.get('mob', 'something')}.",
                                tags=["milestone", "death", "killed_by_mob", payload.get("mob") or "unknown"],
                            )
                        )

            # Detect PvP kills from this tick's resolved attack_hero events
            from sqlalchemy import select as _sel
            pvp_kills = list(
                db.scalars(
                    _sel(Event).where(
                        Event.tick_id == tick_id,
                        Event.kind == "action.resolved",
                    )
                )
            )
            for ev in pvp_kills:
                outcome = (ev.payload or {}).get("outcome", {}) or {}
                if outcome.get("verb") == "attack_hero" and outcome.get("killed"):
                    db.add(
                        Event(
                            tick_id=tick_id,
                            hero_id=uuid.UUID(outcome["target_id"]) if outcome.get("target_id") else None,
                            zone=None,
                            kind="hero.died",
                            payload={
                                "killer": outcome.get("target"),  # actually killer is the attacker
                                "killer_id": str(ev.hero_id) if ev.hero_id else None,
                                "killer_kind": "hero",
                                "name": outcome.get("target"),
                                "looted_gold": outcome.get("looted_gold", 0),
                            },
                        )
                    )

            db.commit()

            # Reload heroes (and the recent events) for fresh perception.
            alive = list(db.scalars(select(Hero).where(Hero.status == "alive")))

            # Pull the just-emitted events so we can fold them into perception.recent_events.
            recent = list(
                db.scalars(
                    select(Event)
                    .where(Event.tick_id == tick_id)
                    .order_by(Event.id.desc())
                    .limit(50)
                )
            )

            perception_payloads: dict[str, dict[str, Any]] = {}
            for hero in alive:
                if str(hero.id) not in self._connections:
                    continue
                hero_recent = [
                    {
                        "kind": e.kind,
                        "tick_id": e.tick_id,
                        "zone": e.zone,
                        "payload": e.payload,
                        "by_self": str(e.hero_id) == str(hero.id) if e.hero_id else False,
                    }
                    for e in recent
                    if e.zone == hero.zone or str(e.hero_id) == str(hero.id)
                ]
                perception_payloads[str(hero.id)] = {
                    "type": "perception",
                    "tick_id": tick_id,
                    "gateway_permission_token": issue_permission_token(
                        hero_id=str(hero.id),
                        max_tokens=max_tokens_per_tick(hero),
                    ),
                    "your_state": {
                        "id": str(hero.id),
                        "name": hero.name,
                        "hp": hero.hp,
                        "mana": hero.mana_current,
                        "mana_max": hero.mana_max,
                        "zone": hero.zone,
                        "pos": [hero.pos_x, hero.pos_y],
                        "equipped": hero.equipped or {},
                        "skills": hero.skills or {},
                        "known_spells": list(hero.known_spells or []),
                    },
                    "perception": {
                        **perception_for(db, hero),
                        "recent_events": hero_recent,
                    },
                    "deadline_ms": int(settings.world_tick_seconds * 1000),
                }

        logger.info(
            "tick %d · %d alive · %d connected · %d resolved",
            tick_id, len(alive), len(self._connections), resolved_count,
        )

        for hero_id, payload in perception_payloads.items():
            queue = self._connections.get(hero_id)
            if queue is None:
                continue
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("dropping perception for %s (queue full)", hero_id)

        # Fan out events to spectator subscribers, grouped by zone.
        for ev in recent:
            if ev.zone is None:
                continue
            subs = self._zone_subscribers.get(ev.zone)
            if not subs:
                continue
            payload = {
                "tick_id": ev.tick_id,
                "zone": ev.zone,
                "kind": ev.kind,
                "hero_id": str(ev.hero_id) if ev.hero_id else None,
                "payload": ev.payload,
            }
            for q in subs:
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass  # spectator falling behind; drop frames is acceptable


tick_engine = TickEngine()
