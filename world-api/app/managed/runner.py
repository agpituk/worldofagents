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

        # Lazy imports — the SDK install must be on PYTHONPATH (it is in
        # production via the docker layer; in tests via conftest).
        from arena_bot.hero_runtime import (
            HeroDecisionState, parse_abilities, parse_persona,
        )
        from arena_bot.reflexes import ReflexEngine
        from arena_bot.tool_dispatch import HeroToolset

        inner = manifest.get("hero") if isinstance(manifest.get("hero"), dict) else manifest
        self._inner = inner or {}

        persona = parse_persona(manifest)
        self._bio = persona["bio"]
        self._goal = persona["goal"] or "Survive."
        self._system_summary = persona["system_summary"]
        self._model_id = persona["model_id"]

        self._reflexes = ReflexEngine(self._inner.get("reflexes") or [])
        self._abilities = parse_abilities(manifest)
        self._toolset = HeroToolset.from_manifest(manifest)
        self._state = HeroDecisionState()

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
        from arena_bot.hero_runtime import decide_one

        perception = Perception(
            tick_id=msg["tick_id"],
            your_state=msg["your_state"],
            perception=msg["perception"],
            deadline_ms=msg.get("deadline_ms", 6000),
            gateway_permission_token=msg.get("gateway_permission_token"),
        )

        # Per-tick trace event accumulator — the dispatcher pushes
        # tool.* events here, and we forward them to the action
        # submission so they land in the Event table under the
        # action.resolved row's debug payload. The Inspector reads
        # them back from there.
        self._tick_trace: list[dict[str, Any]] = []

        # The shared hero_runtime owns reflex-eval, composite-drain
        # (with P2-2 interrupt re-check), and invoke_llm dispatch.
        # The transport-specific bit is _call_llm, which we inject.
        action, debug = await decide_one(
            state=self._state, perception=perception,
            reflex_engine=self._reflexes, abilities=self._abilities,
            on_invoke_llm=self._call_llm,
        )
        kind = "llm" if (debug or {}).get("via") == "invoke_llm" else "reflex"

        # Attach the captured tool events (if any) to debug.
        if self._tick_trace:
            debug = dict(debug or {})
            debug["tool_events"] = list(self._tick_trace)
        return action, debug, kind

    # ------------------------------------------------------------------
    # Gateway call
    # ------------------------------------------------------------------

    async def _call_llm(self, perception: "Perception") -> dict[str, Any]:  # type: ignore[name-defined]
        from arena_bot.actions import DEFAULT_TOOLS
        from arena_bot.client import build_tool_action_prompt, parse_json_action
        from arena_bot.reflexes import build_context
        from arena_bot.tool_dispatch import expand_tool_call
        from arena_bot.tools import (
            build_tool_index, build_tool_specs_for_hero,
        )

        manifest_tools = (
            list(self._toolset.composites.values())
            + list(self._toolset.overrides.values())
        )
        specs = build_tool_specs_for_hero(list(DEFAULT_TOOLS), manifest_tools)
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
            chosen_name = first.get("name", "")
            chosen_args = first.get("arguments") or {}

            # Composite or override — expand and queue the tail through
            # the same composite_queue mechanism abilities use.
            if (
                self._toolset.is_composite(chosen_name)
                or self._toolset.is_override(chosen_name)
            ):
                namespace = build_context(perception)
                trace_buf = getattr(self, "_tick_trace", None)

                def _trace(event: str, payload: dict[str, Any]) -> None:
                    if trace_buf is not None:
                        trace_buf.append({"event": event, "payload": payload})

                # Stash the LLM-facing tool list and reasoning so the
                # Inspector's "why didn't my tool fire?" view has data.
                if trace_buf is not None:
                    trace_buf.append({
                        "event": "llm.tools_offered",
                        "payload": {
                            "chosen_tool": chosen_name,
                            "chosen_args": chosen_args,
                            "tools_offered": [
                                {
                                    "name": s["function"]["name"],
                                    "description": s["function"]["description"][:240],
                                }
                                for s in specs
                            ],
                            "reasoning_trace": (body.get("completion") or "")[:500],
                        },
                    })

                result = expand_tool_call(
                    chosen_name, chosen_args,
                    toolset=self._toolset, namespace=namespace,
                    trace=_trace,
                )
                if not result.actions:
                    return {"do": "wait"}
                head, *tail = result.actions
                if tail:
                    self._state.composite_queue = list(tail)
                    self._state.composite_name = chosen_name
                return head

            fn = index.get(chosen_name)
            if fn is not None:
                try:
                    return fn(**chosen_args)
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
