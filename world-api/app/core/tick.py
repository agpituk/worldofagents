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

# P1-2: bound the per-hero perception build. With sync SQLAlchemy a slow
# retriever for one hero can stall the read pass for everyone; the
# watchdog skips the offender and the rest of the world ticks normally.
PERCEPTION_BUILD_TIMEOUT_SEC = 0.5


def _build_perception_payload_sync(
    *, hero_id_str: str, tick_id: int, recent: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Build one hero's perception payload using a fresh DB session.

    Module-level (not a method) so asyncio.to_thread can pickle it
    cheaply. Returns None if the hero has died or vanished between
    the write commit and this read."""
    with SessionLocal() as db:
        hero = db.get(Hero, uuid.UUID(hero_id_str))
        if hero is None or hero.status != "alive":
            return None
        hero_recent = [
            {
                "kind": e["kind"], "tick_id": e["tick_id"], "zone": e["zone"],
                "payload": e["payload"],
                "by_self": e["hero_id"] == hero_id_str,
            }
            for e in recent
            if e["zone"] == hero.zone or e["hero_id"] == hero_id_str
        ]
        return {
            "type": "perception",
            "tick_id": tick_id,
            "gateway_permission_token": issue_permission_token(
                hero_id=str(hero.id), max_tokens=max_tokens_per_tick(hero),
            ),
            "your_state": {
                "id": str(hero.id), "name": hero.name, "hp": hero.hp,
                "mana": hero.mana_current, "mana_max": hero.mana_max,
                "zone": hero.zone, "pos": [hero.pos_x, hero.pos_y],
                "equipped": hero.equipped or {}, "skills": hero.skills or {},
                "known_spells": list(hero.known_spells or []),
            },
            "perception": {
                **perception_for(db, hero),
                "recent_events": hero_recent,
            },
            "deadline_ms": int(settings.world_tick_seconds * 1000),
        }


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

    # --- parallel perception read pass (P1-2) ------------------------------------

    async def _build_perceptions_parallel(
        self,
        *,
        tick_id: int,
        alive_ids: list[str],
        recent: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Run perception_for + payload assembly concurrently per hero.

        Each task takes its own SessionLocal in a worker thread so the
        sync SQLAlchemy I/O parallelises across the asyncio loop. Per-
        hero timeout (PERCEPTION_BUILD_TIMEOUT_SEC) bounds the worst
        case so one slow retriever can't stall the world."""

        async def _one(hero_id_str: str) -> tuple[str, dict[str, Any]] | None:
            if hero_id_str not in self._connections:
                return None
            try:
                payload = await asyncio.wait_for(
                    asyncio.to_thread(
                        _build_perception_payload_sync,
                        hero_id_str=hero_id_str, tick_id=tick_id, recent=recent,
                    ),
                    timeout=PERCEPTION_BUILD_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "perception build for %s exceeded %.2fs — skipped this tick",
                    hero_id_str, PERCEPTION_BUILD_TIMEOUT_SEC,
                )
                return None
            except Exception:
                logger.exception("perception build raised for %s", hero_id_str)
                return None
            if payload is None:
                return None
            return hero_id_str, payload

        results = await asyncio.gather(*(_one(h) for h in alive_ids))
        return dict(r for r in results if r is not None)

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

            # Phase 2 — status effect tick. Apply per-tick payloads
            # (bleed deals damage, regrowth heals) before they expire,
            # then prune expired rows so they stop affecting attack/AC
            # rolls and stop appearing in perception.
            from app.core.actions import _evict_expired_sandbox_heroes, tick_statuses
            tick_statuses(db, tick_id)
            # Phase 8 — sandbox auto-eviction. Heroes who've used up
            # their training window get bumped into market_square so
            # the open world claims them.
            _evict_expired_sandbox_heroes(db, tick_id)

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

            # Materialise alive hero ids + recent events as plain data
            # before the session closes — the parallel read pass below
            # opens its own per-thread sessions, and the spectator
            # fan-out runs without any session.
            alive_ids = [str(h.id) for h in db.scalars(
                select(Hero).where(Hero.status == "alive")
            )]
            recent_dicts = [
                {
                    "kind": e.kind, "tick_id": e.tick_id, "zone": e.zone,
                    "payload": e.payload,
                    "hero_id": str(e.hero_id) if e.hero_id else None,
                }
                for e in db.scalars(
                    select(Event)
                    .where(Event.tick_id == tick_id)
                    .order_by(Event.id.desc())
                    .limit(50)
                )
            ]
            alive_count = len(alive_ids)

        # P1-2 read pass — build perception for every connected alive
        # hero CONCURRENTLY in worker threads. Each thread takes its own
        # SessionLocal so a slow retriever for one hero can't stall the
        # others. The write pass already committed; per-thread reads
        # see consistent state. Each build is bounded by
        # PERCEPTION_BUILD_TIMEOUT_SEC; on timeout, the hero is skipped
        # for this tick and a warning logged.
        perception_payloads = await self._build_perceptions_parallel(
            tick_id=tick_id, alive_ids=alive_ids, recent=recent_dicts,
        )

        logger.info(
            "tick %d · %d alive · %d connected · %d resolved",
            tick_id, alive_count, len(self._connections), resolved_count,
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
        for ev in recent_dicts:
            if ev["zone"] is None:
                continue
            subs = self._zone_subscribers.get(ev["zone"])
            if not subs:
                continue
            payload = {
                "tick_id": ev["tick_id"],
                "zone": ev["zone"],
                "kind": ev["kind"],
                "hero_id": ev["hero_id"],
                "payload": ev["payload"],
            }
            for q in subs:
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass  # spectator falling behind; drop frames is acceptable


tick_engine = TickEngine()
