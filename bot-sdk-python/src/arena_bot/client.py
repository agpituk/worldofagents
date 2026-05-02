"""Hero client.

Two-layer decision API:
  • Low-level: override `decide(perception)` to return a Decision (reflex or llm).
  • Helpers: `think()` calls the gateway and returns (completion, token).
            `llm_action()` builds a standard prompt from perception, calls the
            gateway, parses JSON action, returns a Decision(kind="llm").

For dev iteration, use `Hero.connect()` instead of `register()`. It caches
credentials in `<manifest_dir>/.arena-cache/<slug>.json` and resumes across
runs and DB wipes.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import websockets
import yaml

log = logging.getLogger("arena_bot")


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "hero"


async def _hero_exists(world_url: str, hero_id: str) -> bool:
    try:
        async with httpx.AsyncClient(base_url=world_url.rstrip("/"), timeout=5.0) as client:
            r = await client.get(f"/heroes/{hero_id}")
            return r.status_code == 200
    except httpx.HTTPError:
        return False


@dataclass
class Perception:
    tick_id: int
    your_state: dict[str, Any]
    perception: dict[str, Any]
    deadline_ms: int
    # World-api-signed cap on max_tokens for any /think call this tick.
    # The SDK forwards it to the gateway, which enforces.
    gateway_permission_token: str | None = None


@dataclass
class Decision:
    """What the hero submits this tick.

    - kind="reflex": deterministic action; no gateway token.
    - kind="llm":    LLM-driven; `gateway_token` must be set OR (`model`+`messages`)
                     left for the SDK to fill in via a fallback gateway call.
    - debug:         optional metadata (e.g. which reflex fired) — surfaced
                     server-side and rendered in the spectator UI.
    """

    kind: str
    action: dict[str, Any]
    gateway_token: str | None = None
    messages: list[dict[str, str]] | None = None
    model: str | None = None
    debug: dict[str, Any] | None = None
    # Phase 2 — when the LLM picks a composite tool, the dispatcher expands
    # its steps into a list of primitive actions. The first one is `action`;
    # the rest land here for the runtime to push into the composite queue
    # (one primitive per tick). None means "single primitive tool call".
    composite_queue_tail: list[dict[str, Any]] | None = None


# ---------------------------------------------------------------------------
# JSON action parser (tolerant of code fences; structured failure reporting)
# ---------------------------------------------------------------------------

_OBJECT_RE = re.compile(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", re.DOTALL)

# Failure-mode taxonomy. Stable strings — they end up in events that the
# spectator UI will eventually render, and players will read them looking
# for "why is my hero waiting?". Don't reword these casually.
PARSE_REASON_EMPTY = "empty"
PARSE_REASON_NO_JSON = "no_json_found"
PARSE_REASON_INVALID_JSON = "invalid_json"
PARSE_REASON_NOT_OBJECT = "not_an_object"
PARSE_REASON_MISSING_DO = "missing_do"
PARSE_REASON_MULTIPLE_OBJECTS = "multiple_objects"


class ParseError(ValueError):
    """A structured LLM-output parse failure.

    Subclasses ValueError so existing `except ValueError` blocks still
    catch it, but carries the failure reason and a truncated raw output
    so callers can build a ParseFailure event the spectator can read.
    """

    def __init__(self, reason: str, *, raw_output: str = "", message: str | None = None) -> None:
        self.reason = reason
        self.raw_output = (raw_output or "")[:500]
        super().__init__(message or f"{reason}: {self.raw_output[:120]!r}")


def parse_json_action(text: str) -> dict[str, Any]:
    """Parse the LLM's completion into an action dict, raising ParseError
    with a stable `reason` so the world can record what went wrong rather
    than silently waiting."""
    raw = text or ""
    if not raw or not raw.strip():
        raise ParseError(PARSE_REASON_EMPTY, raw_output=raw)
    text = raw.strip()
    # Strip a leading/trailing code fence if present.
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try a whole-string parse first — the strict path. If the model
    # behaved, this is where the parse succeeds.
    obj: Any
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to first-object regex extraction; flag if there are
        # multiple top-level JSON objects so a second-action smuggle is
        # legible rather than silent.
        matches = _OBJECT_RE.findall(text)
        if not matches:
            raise ParseError(PARSE_REASON_NO_JSON, raw_output=raw) from None
        if len(matches) > 1:
            raise ParseError(
                PARSE_REASON_MULTIPLE_OBJECTS, raw_output=raw,
                message=f"{len(matches)} JSON objects in output; refusing to guess",
            ) from None
        try:
            obj = json.loads(matches[0])
        except json.JSONDecodeError as exc:
            raise ParseError(PARSE_REASON_INVALID_JSON, raw_output=raw) from exc

    if not isinstance(obj, dict):
        raise ParseError(
            PARSE_REASON_NOT_OBJECT, raw_output=raw,
            message=f"expected object, got {type(obj).__name__}",
        )
    if "do" not in obj:
        raise ParseError(
            PARSE_REASON_MISSING_DO, raw_output=raw,
            message=f"missing 'do' field in {obj!r}",
        )
    return obj


# ---------------------------------------------------------------------------
# Action-prompt builder
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------


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
        manifest_bytes = Path(manifest_path).read_bytes()
        async with httpx.AsyncClient(base_url=world_url.rstrip("/"), timeout=15.0) as client:
            files = {"manifest": (Path(manifest_path).name, manifest_bytes, "application/yaml")}
            r = await client.post("/heroes/register", files=files)
            r.raise_for_status()
            body = r.json()
        log.info("registered hero %s (%s)", body["name"], body["id"])
        return cls(
            hero_id=body["id"],
            name=body["name"],
            auth_token=body["auth_token"],
            world_url=world_url,
            gateway_url=gateway_url,
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
    ) -> "Hero":
        manifest_path = Path(manifest_path)
        manifest = yaml.safe_load(manifest_path.read_bytes())
        inner = manifest["hero"] if "hero" in manifest and "name" not in manifest else manifest
        name = inner["name"]
        slug = _slugify(name)

        cache_root = Path(cache_dir) if cache_dir else manifest_path.parent / ".arena-cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_file = cache_root / f"{slug}.json"

        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text())
                if await _hero_exists(world_url, cached["hero_id"]):
                    log.info("resuming cached hero %s (%s)", cached["name"], cached["hero_id"])
                    return cls(
                        hero_id=cached["hero_id"],
                        name=cached["name"],
                        auth_token=cached["auth_token"],
                        world_url=world_url,
                        gateway_url=gateway_url,
                    )
                log.info("cached hero %s no longer in world — re-registering", name)
            except (KeyError, json.JSONDecodeError) as exc:
                log.warning("cache file unreadable (%s) — re-registering", exc)

        try:
            hero = await cls.register(
                manifest_path=manifest_path, world_url=world_url, gateway_url=gateway_url
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                raise RuntimeError(
                    f"Hero name '{name}' is already registered in the world but no "
                    f"local cache for it exists. Either:\n"
                    f"  • delete the orphan: docker compose exec -T postgres psql "
                    f"-U arena -d arena -c \"DELETE FROM heroes WHERE name='{name}';\"\n"
                    f"  • or wipe the world: docker compose down -v && docker compose up -d\n"
                    f"  • or rename your hero in the manifest"
                ) from exc
            raise
        cache_file.write_text(
            json.dumps(
                {"hero_id": hero.hero_id, "name": hero.name, "auth_token": hero.auth_token},
                indent=2,
            )
        )
        log.info("cached credentials at %s", cache_file)
        return hero

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
            # Some models, given tools, still return free text. Try to parse.
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

        # Composite tool — expand via the dispatcher. First primitive is
        # this tick's action; the rest land in composite_queue_tail.
        # Overrides apply when the LLM picks a primitive (handled below).
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
                log.warning("tool '%s' expanded to nothing — falling back",
                            chosen_name)
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

        log.info("LLM picked tool: %s(%s) → %s",
                 chosen_name, chosen_args, action)
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
                # legacy path: SDK calls the gateway, no completion parsing.
                _, token = await self.think(
                    messages=decision.messages, model=decision.model, tick_id=p.tick_id
                )
                outbound["gateway_token"] = token
            else:
                log.warning("llm decision missing token + messages — falling back to reflex")
                outbound["kind"] = "reflex"

        await ws.send(json.dumps(outbound))
