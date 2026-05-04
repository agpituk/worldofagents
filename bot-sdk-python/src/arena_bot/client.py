"""Hero client — WS connection + LLM driver helpers.

Two-layer decision API:
  • Low-level: override `decide(perception)` to return a Decision (reflex or llm).
  • Helpers: `think()` calls the gateway and returns (completion, token).
            `llm_action()` builds a standard prompt from perception, calls the
            gateway, parses JSON action, returns a Decision(kind="llm").

For dev iteration, use `Hero.connect()` instead of `register()`. It caches
credentials in `<manifest_dir>/.arena-cache/<slug>.json` and resumes across
runs and DB wipes.

The JSON parser, prompt builders, and Perception/Decision dataclasses live
in sibling modules (`parser`, `prompt`, `types`) — re-exported below for
back-compat with anything that historically imported them from this module.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import websockets

from arena_bot.parser import (
    PARSE_REASON_EMPTY,
    PARSE_REASON_INVALID_JSON,
    PARSE_REASON_MISSING_DO,
    PARSE_REASON_MULTIPLE_OBJECTS,
    PARSE_REASON_NO_JSON,
    PARSE_REASON_NOT_OBJECT,
    ParseError,
    parse_json_action,
)
from arena_bot.prompt import build_action_prompt, build_tool_action_prompt
from arena_bot.registration import (
    _hero_exists,
    _hero_id_by_name,
    _slugify,
    connect_or_register,
    register_hero as _register_hero,
)
from arena_bot.types import Decision, Perception

log = logging.getLogger("arena_bot")


# Re-export so existing `from arena_bot.client import …` imports keep working.
__all__ = [
    "Decision",
    "Hero",
    "PARSE_REASON_EMPTY",
    "PARSE_REASON_INVALID_JSON",
    "PARSE_REASON_MISSING_DO",
    "PARSE_REASON_MULTIPLE_OBJECTS",
    "PARSE_REASON_NO_JSON",
    "PARSE_REASON_NOT_OBJECT",
    "ParseError",
    "Perception",
    "build_action_prompt",
    "build_tool_action_prompt",
    "parse_json_action",
]


# `_slugify`, `_hero_exists`, `_hero_id_by_name` moved to registration.py
# and re-imported above for back-compat with anything that grew an
# `arena_bot.client` import for them.


class Hero:
    def __init__(
        self,
        *,
        hero_id: str,
        name: str,
        auth_token: str,
        world_url: str,
        gateway_url: str,
    ) -> None:
        self.hero_id = hero_id
        self.name = name
        self.auth_token = auth_token
        self.world_url = world_url.rstrip("/")
        self.gateway_url = gateway_url.rstrip("/")

    # ------------------------------------------------------------------ register
    @classmethod
    async def register(
        cls,
        *,
        manifest_path: str | Path,
        world_url: str,
        gateway_url: str,
    ) -> "Hero":
        hero_id, name, auth_token = await _register_hero(
            manifest_path=manifest_path, world_url=world_url
        )
        return cls(
            hero_id=hero_id, name=name, auth_token=auth_token,
            world_url=world_url, gateway_url=gateway_url,
        )

    # ------------------------------------------------------------------- connect
    @classmethod
    async def connect(
        cls,
        *,
        manifest_path: str | Path,
        world_url: str,
        gateway_url: str,
        cache_dir: str | Path | None = None,
        auth_token: str | None = None,
    ) -> "Hero":
        """Resolve a hero from cache, an injected `auth_token`, or a
        fresh registration — in that order. The hand-off logic lives
        in `registration.connect_or_register`; this method just wraps
        the result in a Hero instance with the gateway URL attached."""
        hero_id, name, token = await connect_or_register(
            manifest_path=manifest_path,
            world_url=world_url,
            cache_dir=cache_dir,
            auth_token=auth_token,
        )
        return cls(
            hero_id=hero_id, name=name, auth_token=token,
            world_url=world_url, gateway_url=gateway_url,
        )

    # --------------------------------------------------------------------- run
    async def run(self) -> None:
        """Run the bot. Auto-reconnects on WS drops with exponential backoff
        (1s → 30s cap), so world-api restarts don't kill the bot."""
        import asyncio as _asyncio

        backoff = 1.0
        while True:
            ws_url = self._ws_url()
            log.info("connecting to %s", ws_url)
            try:
                async with websockets.connect(ws_url) as ws:
                    backoff = 1.0  # reset on successful connect
                    async for raw in ws:
                        msg = json.loads(raw)
                        msg_type = msg.get("type")
                        if msg_type == "welcome":
                            log.info("welcomed: %s", msg)
                            continue
                        if msg_type == "perception":
                            p = Perception(
                                tick_id=msg["tick_id"],
                                your_state=msg["your_state"],
                                perception=msg["perception"],
                                deadline_ms=msg["deadline_ms"],
                                gateway_permission_token=msg.get("gateway_permission_token"),
                            )
                            await self._handle_perception(ws, p)
                        else:
                            log.debug("unknown msg: %s", msg)
            except (websockets.exceptions.ConnectionClosed, OSError) as exc:
                log.warning("WS dropped (%s) — reconnecting in %.1fs", exc, backoff)
                await _asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            except Exception:
                log.exception("unexpected WS loop error — reconnecting in %.1fs", backoff)
                await _asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    # --------------------------------------------------------------- override
    async def decide(self, perception: Perception) -> Decision:
        return Decision(kind="reflex", action={"do": "wait"})

    # --------------------------------------------------------- LLM helpers
    async def think(
        self,
        *,
        messages: list[dict[str, str]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        tick_id: int | None = None,
        retries: int = 3,
        permission_token: str | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Call the gateway. Retries up to `retries` times on 502/503/504/timeout
        with exponential backoff (0.5s → 1s → 2s) so a brief llamafile blip
        doesn't deadlock the bot.

        `permission_token` is the world-api-signed cap on max_tokens for this
        tick; the gateway rejects calls that exceed it. Callers should pass
        `perception.gateway_permission_token` through.
        """
        import asyncio as _asyncio

        payload: dict[str, Any] = {
            "hero_id": self.hero_id,
            "model": model,
            "messages": messages,
            "tick_id": tick_id,
        }
        if tools is not None:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        if permission_token is not None:
            payload["permission_token"] = permission_token
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        backoff = 0.5
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(base_url=self.gateway_url, timeout=60.0) as client:
                    r = await client.post("/think", json=payload)
                    if r.status_code in (502, 503, 504):
                        raise httpx.HTTPStatusError(
                            f"gateway provider error {r.status_code}",
                            request=r.request, response=r,
                        )
                    r.raise_for_status()
                    return r.json()
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= retries:
                    break
                log.info("gateway hiccup (%s) — retry %d/%d in %.1fs", exc, attempt + 1, retries, backoff)
                await _asyncio.sleep(backoff)
                backoff = min(backoff * 2, 4.0)
        assert last_exc is not None
        raise last_exc

    async def llm_action(
        self,
        *,
        perception: Perception,
        model: str,
        bio: str = "",
        goal: str = "",
        fallback: dict[str, Any] | None = None,
    ) -> Decision:
        """Legacy free-text path: ask the model for raw JSON, parse it. Kept
        as a fallback for providers that don't support tool-calling. Prefer
        `llm_tool_action()` — it's more reliable for small models because the
        model can't emit malformed JSON."""
        fallback = fallback or {"do": "wait"}
        system, user = build_action_prompt(
            name=self.name, bio=bio, goal=goal, perception=perception
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            body = await self.think(
                messages=messages, model=model, tick_id=perception.tick_id,
                permission_token=perception.gateway_permission_token,
            )
        except httpx.HTTPError as exc:
            log.warning("LLM action HTTP failed (%s) — falling back to %s", exc, fallback)
            return Decision(kind="reflex", action=fallback)
        try:
            action = parse_json_action(body["completion"])
        except ParseError as exc:
            log.warning("LLM action parse failed (%s) — emitting parse_failure", exc)
            return Decision(
                kind="reflex", action=fallback,
                debug={"parse_error": exc.reason, "raw_output": exc.raw_output},
            )
        log.info("LLM picked: %s", action)
        return Decision(kind="llm", action=action, gateway_token=body["gateway_token"])

    async def llm_tool_action(
        self,
        *,
        perception: Perception,
        model: str,
        tools: list[Any] | None = None,
        bio: str = "",
        goal: str = "",
        system_summary: str = "",
        fallback: dict[str, Any] | None = None,
        toolset: Any = None,
    ) -> Decision:
        """Native tool-calling path. Each callable in `tools` becomes a model
        tool via `build_tool_specs()`. The model picks ONE tool, the SDK
        dispatches it locally to produce the action dict, then submits.

        `toolset` is an optional `arena_bot.tool_dispatch.HeroToolset` —
        when present, docstring overrides are applied to the spec list and
        composite tools are appended. If the LLM picks a composite, the
        dispatcher expands its steps; the first action is returned, the rest
        ride along on `Decision.composite_queue_tail` for the runtime to
        queue.
        """
        from arena_bot.actions import DEFAULT_TOOLS
        from arena_bot.tools import build_tool_index, build_tool_specs, build_tool_specs_for_hero

        fallback = fallback or {"do": "wait"}
        tool_fns = list(tools) if tools else list(DEFAULT_TOOLS)
        if toolset is not None:
            manifest_tools = list(toolset.composites.values()) + list(toolset.overrides.values())
            specs = build_tool_specs_for_hero(tool_fns, manifest_tools)
        else:
            specs = build_tool_specs(tool_fns)
        index = build_tool_index(tool_fns)

        system, user = build_tool_action_prompt(
            name=self.name, bio=bio, goal=goal, perception=perception,
            system_summary=system_summary,
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

        try:
            body = await self.think(
                messages=messages,
                model=model,
                tools=specs,
                tool_choice="auto",
                tick_id=perception.tick_id,
                permission_token=perception.gateway_permission_token,
            )
        except httpx.HTTPError as exc:
            log.warning("LLM tool action HTTP failed (%s) — falling back", exc)
            return Decision(kind="reflex", action=fallback)

        tool_calls = body.get("tool_calls") or []
        if not tool_calls:
            log.info("LLM returned no tool_calls; trying free-text fallback")
            try:
                action = parse_json_action(body.get("completion", ""))
                return Decision(kind="llm", action=action, gateway_token=body["gateway_token"])
            except ParseError as exc:
                log.warning("no tool_calls and free-text unparseable (%s)", exc)
                return Decision(
                    kind="reflex", action=fallback,
                    debug={"parse_error": exc.reason, "raw_output": exc.raw_output},
                )

        first = tool_calls[0]
        chosen_name = first.get("name", "")
        chosen_args = first.get("arguments") or {}

        # Composite or override tool — expand via the dispatcher. First
        # primitive is this tick's action; the rest land in
        # composite_queue_tail.
        if toolset is not None and (
            toolset.is_composite(chosen_name) or toolset.is_override(chosen_name)
        ):
            from arena_bot.reflexes import build_context
            from arena_bot.tool_dispatch import expand_tool_call

            namespace = build_context(perception)
            result = expand_tool_call(
                chosen_name, chosen_args, toolset=toolset, namespace=namespace,
            )
            if not result.actions:
                log.warning("tool '%s' expanded to nothing — falling back", chosen_name)
                return Decision(kind="reflex", action=fallback)
            head, *tail = result.actions
            log.info("LLM picked %s: %s(%s) → %d actions",
                     "composite" if toolset.is_composite(chosen_name) else "override",
                     chosen_name, chosen_args, len(result.actions))
            return Decision(
                kind="llm", action=head,
                gateway_token=body["gateway_token"],
                composite_queue_tail=tail or None,
                debug={"tool": chosen_name, "expanded": len(result.actions)},
            )

        fn = index.get(chosen_name)
        if fn is None:
            log.warning("LLM picked unknown tool %r — falling back", chosen_name)
            return Decision(
                kind="reflex", action=fallback,
                debug={"parse_error": "unknown_tool",
                       "raw_output": str(chosen_name)[:500]},
            )

        try:
            action = fn(**chosen_args)
        except TypeError as exc:
            log.warning("tool '%s' rejected args %s (%s) — falling back",
                        chosen_name, chosen_args, exc)
            return Decision(
                kind="reflex", action=fallback,
                debug={"parse_error": "bad_tool_args",
                       "raw_output": json.dumps({"name": chosen_name,
                                                 "arguments": chosen_args})[:500]},
            )

        log.info("LLM picked tool: %s(%s) → %s", chosen_name, chosen_args, action)
        return Decision(kind="llm", action=action, gateway_token=body["gateway_token"])

    # ----------------------------------------------------------------- internal
    def _ws_url(self) -> str:
        return self.world_url.replace("http", "ws", 1) + f"/heroes/ws?token={self.auth_token}"

    async def _handle_perception(self, ws: Any, p: Perception) -> None:
        decision = await self.decide(p)
        outbound: dict[str, Any] = {
            "type": "action",
            "tick_id": p.tick_id,
            "kind": decision.kind,
            "action": decision.action,
        }
        if decision.debug is not None:
            outbound["debug"] = decision.debug

        if decision.kind == "llm":
            if decision.gateway_token:
                outbound["gateway_token"] = decision.gateway_token
            elif decision.messages and decision.model:
                _, token = await self.think(
                    messages=decision.messages, model=decision.model, tick_id=p.tick_id
                )
                outbound["gateway_token"] = token
            else:
                log.warning("llm decision missing token + messages — falling back to reflex")
                outbound["kind"] = "reflex"

        await ws.send(json.dumps(outbound))
