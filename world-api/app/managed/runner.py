"""Per-hero managed asyncio task. See app.managed.__init__ for context."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

import httpx

from app.core.database import SessionLocal
from app.core.models import Hero
from app.core.tick import tick_engine

log = logging.getLogger("world.managed")


def _gateway_base_url() -> str:
    # Inside the docker-compose network world-api can reach llm-gateway by
    # service name. GATEWAY_BASE_URL env is already set by compose.
    return os.environ.get("GATEWAY_BASE_URL", "http://llm-gateway:8001").rstrip("/")


class ManagedHeroTask:
    """One bot loop, in-process. Mirrors what a remote bot-sdk client does."""

    def __init__(self, hero_id: str, name: str, manifest: dict[str, Any]) -> None:
        self.hero_id = hero_id
        self.name = name
        self.manifest = manifest
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

        # Manifests can be wrapped in a top-level `hero:` block.
        inner = manifest.get("hero") if isinstance(manifest.get("hero"), dict) else manifest
        self._inner = inner or {}
        self._bio = self._inner.get("bio") or ""
        memory = self._inner.get("memory") or {}
        self._goal = (memory.get("initial") or {}).get("goal") or "Survive."
        self._system_summary = (memory.get("system_summary") or "").strip()

        models = self._inner.get("models") or {}
        alias = self._inner.get("model") or "cheap"
        spec = models.get(alias) if isinstance(models, dict) else None
        self._model_id = (spec or {}).get("model") if isinstance(spec, dict) else "qwen3-4b"

        # Lazy imports so the world-api still boots if the SDK install
        # somehow failed at container start.
        from arena_bot.reflexes import ReflexEngine
        self._reflexes = ReflexEngine(self._inner.get("reflexes") or [])

        # Composites: a reflex action with `do == ability_name` expands into
        # the named ability's primitive steps, dispatched one per tick.
        abilities = self._inner.get("abilities") or {}
        self._abilities: dict[str, list[dict[str, Any]]] = {}
        if isinstance(abilities, dict):
            for n, sp in abilities.items():
                if not isinstance(sp, dict):
                    continue
                steps = sp.get("steps") or sp.get("decompose") or []
                if isinstance(steps, list):
                    self._abilities[str(n)] = [s for s in steps if isinstance(s, dict) and s.get("do")]
        self._composite_queue: list[dict[str, Any]] = []
        self._composite_name: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=f"managed:{self.name}")
        log.info("managed task started for %s (%s)", self.name, self.hero_id)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    # ------------------------------------------------------------------
    # The bot loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        queue = tick_engine.register_agent(self.hero_id)
        try:
            while not self._stop.is_set():
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=3.0)
                except asyncio.TimeoutError:
                    if self._is_dead():
                        log.info("managed hero %s is dead — exiting loop", self.name)
                        return
                    continue

                if self._is_dead():
                    return

                action, debug, kind = await self._decide(msg)
                tick_engine.submit_action(self.hero_id, {
                    "type": "action",
                    "action": action,
                    "kind": kind,
                    "debug": debug,
                })
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("managed loop crashed for %s — task ending", self.name)
        finally:
            tick_engine.unregister_agent(self.hero_id)

    def _is_dead(self) -> bool:
        try:
            with SessionLocal() as db:
                hero = db.get(Hero, uuid.UUID(self.hero_id))
                return hero is None or hero.status != "alive"
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Decide one action
    # ------------------------------------------------------------------

    async def _decide(self, msg: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None, str]:
        from arena_bot.client import Perception

        perception = Perception(
            tick_id=msg["tick_id"],
            your_state=msg["your_state"],
            perception=msg["perception"],
            deadline_ms=msg.get("deadline_ms", 6000),
            gateway_permission_token=msg.get("gateway_permission_token"),
        )

        # If a composite is in flight, re-evaluate reflexes against fresh
        # perception BEFORE draining the next primitive step. This is the
        # P2-2 fix: an enemy that appears on step 2 of a 5-step gather
        # plan should interrupt the gather, not get gathered through.
        # Reflexes that produce the SAME composite the hero is currently
        # running don't trigger re-entry — that would loop forever.
        if self._composite_queue:
            interrupt_action, interrupt_debug = self._reflexes.evaluate_with_debug(perception)
            if interrupt_action is not None and interrupt_action.get("do") not in (
                self._composite_name,  # don't re-enter the same composite
                None,
            ):
                # The interrupt is genuinely different from the in-flight
                # composite. Abandon the queue, log a composite_interrupted
                # marker so the spectator UI can render the break, and
                # treat the interrupt as a fresh decision (which will go
                # through the composite-expansion / invoke_llm paths
                # below on its own).
                interrupted_name = self._composite_name
                remaining = len(self._composite_queue)
                self._composite_queue = []
                self._composite_name = None
                debug = {
                    "via": "composite_interrupted",
                    "interrupted_composite": interrupted_name,
                    "remaining_was": remaining,
                    "by_reflex_index": (interrupt_debug or {}).get("reflex_index"),
                    "when": (interrupt_debug or {}).get("when"),
                }
                # Recurse-style: re-enter the decision path with the queue
                # cleared. _decide_after_reflex handles composite expansion
                # / invoke_llm uniformly with the no-composite branch.
                action, _ = await self._decide_after_reflex(
                    perception, interrupt_action, interrupt_debug
                )
                # Annotate so the spectator can see "broke off X for Y".
                action_debug = {**(_ or {}), "interrupt": debug}
                return action, action_debug, "reflex" if action.get("do") != "invoke_llm" else "llm"

            step = self._composite_queue.pop(0)
            debug = {"via": "composite", "composite": self._composite_name,
                     "remaining": len(self._composite_queue)}
            if not self._composite_queue:
                self._composite_name = None
            return dict(step), debug, "reflex"

        action, debug = self._reflexes.evaluate_with_debug(perception)
        if action is None:
            return {"do": "wait"}, {"reflex_index": -1, "note": "no reflex matched"}, "reflex"
        result_action, result_debug = await self._decide_after_reflex(
            perception, action, debug
        )
        kind = "llm" if result_action.get("do") == "invoke_llm" else "reflex"
        return result_action, result_debug, kind

    async def _decide_after_reflex(
        self,
        perception: "Perception",  # type: ignore[name-defined]
        action: dict[str, Any],
        debug: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Common tail of _decide: given a reflex-selected action, expand
        composites, dispatch invoke_llm, or return the primitive action.
        Pulled out so the composite-interrupt path (P2-2) can share the
        same expansion logic as the cold-start path."""
        # Composite expansion.
        if action.get("do") in self._abilities:
            name = action["do"]
            steps = list(self._abilities[name])
            if steps:
                self._composite_name = name
                self._composite_queue = steps[1:]
                first = steps[0]
                d_debug = {"via": "composite_start", "composite": name,
                           "remaining": len(self._composite_queue),
                           "reflex_index": (debug or {}).get("reflex_index"),
                           "when": (debug or {}).get("when")}
                return dict(first), d_debug

        if action.get("do") == "invoke_llm":
            llm_action = await self._call_llm(perception)
            d_debug = {"via": "invoke_llm",
                       "reflex_index": (debug or {}).get("reflex_index"),
                       "when": (debug or {}).get("when")}
            return llm_action, d_debug

        return action, debug

    # ------------------------------------------------------------------
    # Gateway call
    # ------------------------------------------------------------------

    async def _call_llm(self, perception: "Perception") -> dict[str, Any]:  # type: ignore[name-defined]
        from arena_bot.actions import DEFAULT_TOOLS
        from arena_bot.client import build_tool_action_prompt, parse_json_action
        from arena_bot.tools import build_tool_index, build_tool_specs

        specs = build_tool_specs(list(DEFAULT_TOOLS))
        index = build_tool_index(list(DEFAULT_TOOLS))
        system, user = build_tool_action_prompt(
            name=self.name, bio=self._bio, goal=self._goal,
            perception=perception, system_summary=self._system_summary,
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        payload: dict[str, Any] = {
            "hero_id": self.hero_id,
            "model": self._model_id,
            "messages": messages,
            "tools": specs,
            "tool_choice": "auto",
            "tick_id": perception.tick_id,
        }
        if perception.gateway_permission_token:
            payload["permission_token"] = perception.gateway_permission_token
        try:
            async with httpx.AsyncClient(base_url=_gateway_base_url(), timeout=60.0) as client:
                r = await client.post("/think", json=payload)
                r.raise_for_status()
                body = r.json()
        except httpx.HTTPError as exc:
            log.warning("gateway call failed for %s: %s — falling back to wait", self.name, exc)
            return {"do": "wait"}

        tool_calls = body.get("tool_calls") or []
        if tool_calls:
            first = tool_calls[0]
            fn = index.get(first.get("name", ""))
            if fn is not None:
                try:
                    return fn(**(first.get("arguments") or {}))
                except TypeError as exc:
                    log.warning("managed: bad tool args for %s (%s) — wait fallback",
                                self.name, exc)
                    return {"do": "wait"}
        # Free-text fallback for providers that ignore tool specs.
        try:
            return parse_json_action(body.get("completion", ""))
        except ValueError:
            return {"do": "wait"}


# ---------------------------------------------------------------------------
# Registry — track running managed tasks across the world-api process
# ---------------------------------------------------------------------------


class ManagedRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, ManagedHeroTask] = {}

    def is_running(self, hero_id: str) -> bool:
        return hero_id in self._tasks

    def start(self, hero_id: str, name: str, manifest: dict[str, Any]) -> None:
        if hero_id in self._tasks:
            log.info("managed task for %s already running — skip", name)
            return
        try:
            task = ManagedHeroTask(hero_id, name, manifest)
        except Exception:
            log.exception("failed to construct managed task for %s", name)
            return
        task.start()
        self._tasks[hero_id] = task

    async def stop(self, hero_id: str) -> None:
        task = self._tasks.pop(hero_id, None)
        if task is not None:
            await task.stop()

    async def stop_all(self) -> None:
        for hero_id, task in list(self._tasks.items()):
            await task.stop()
        self._tasks.clear()


registry = ManagedRegistry()


def start_all_on_boot(db) -> int:
    """Scan the DB for managed alive heroes; spawn a task for each.
    Idempotent — safe to call after a world-api restart."""
    from sqlalchemy import select
    rows = list(db.scalars(select(Hero).where(Hero.managed.is_(True), Hero.status == "alive")))
    for h in rows:
        registry.start(str(h.id), h.name, h.manifest or {})
    if rows:
        log.info("managed: spawned %d task(s) on boot", len(rows))
    return len(rows)
