"""Generic manifest runner. The .py boilerplate that used to live in every
archetype example now lives here, parameterised by the manifest YAML.

A player's contribution is just a YAML file. To run it:

    python -m arena_bot path/to/my_hero.yaml

or, if installed as a script:

    arena path/to/my_hero.yaml

The manifest provides everything: name, build, bio, reflexes, model alias,
and (via memory.initial.goal) the goal text fed to the LLM when reflexes
escalate to `invoke_llm`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

import yaml

from arena_bot.client import Decision, Hero, Perception
from arena_bot.hero_runtime import (
    HeroDecisionState,
    decide_one,
    parse_abilities,
    parse_persona,
)
from arena_bot.reflexes import ReflexEngine
from arena_bot.tool_dispatch import HeroToolset


log = logging.getLogger("arena_bot.runner")


class ManifestHero(Hero):
    """A Hero subclass driven entirely by a YAML manifest. The decide() loop
    walks reflexes; on `invoke_llm` it builds the standard tool-calling prompt
    using the manifest's bio + goal + model alias and fires it through the
    gateway.

    Composites: if the manifest has an `abilities:` block with named multi-
    step plans, a reflex can emit `{do: <ability_name>}` and the runner will
    expand that into a queue of primitive actions, dispatching one per tick
    until the queue empties (then reflexes resume)."""

    def __init__(
        self,
        *args: Any,
        manifest: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        manifest = manifest or {}
        inner = manifest.get("hero") if isinstance(manifest.get("hero"), dict) else manifest
        self._reflexes = ReflexEngine((inner or {}).get("reflexes") or [])

        persona = parse_persona(manifest)
        self._bio = persona["bio"]
        self._goal = persona["goal"] or "Survive. Adventure. Make decisions in character."
        self._system_summary = persona["system_summary"]
        self._model_id = persona["model_id"]

        self._abilities = parse_abilities(manifest)
        self._toolset = HeroToolset.from_manifest(manifest)
        self._state = HeroDecisionState()

    async def decide(self, perception: Perception) -> Decision:
        async def _on_invoke_llm(p: Perception) -> dict[str, Any]:
            d = await self.llm_tool_action(
                perception=p, model=self._model_id, bio=self._bio,
                goal=self._goal, system_summary=self._system_summary,
                fallback={"do": "wait"},
                toolset=self._toolset,
            )
            # If the LLM picked a composite, push its tail into the queue
            # so the runtime drains one primitive per tick. Reuses the same
            # mechanism the reflex-side abilities path uses.
            if d.composite_queue_tail:
                self._state.composite_queue = list(d.composite_queue_tail)
                self._state.composite_name = (d.debug or {}).get("composite")
            return d.action

        action, debug = await decide_one(
            state=self._state, perception=perception,
            reflex_engine=self._reflexes, abilities=self._abilities,
            on_invoke_llm=_on_invoke_llm,
        )
        return Decision(kind="llm" if (debug or {}).get("via") == "invoke_llm" else "reflex",
                        action=action, debug=debug)


async def run(
    manifest_path: str | Path,
    *,
    world_url: str,
    gateway_url: str,
    auth_token: str | None = None,
) -> None:
    manifest_path = Path(manifest_path).expanduser().resolve()
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    manifest = yaml.safe_load(manifest_path.read_bytes())
    if not isinstance(manifest, dict):
        raise ValueError(f"manifest must be a YAML mapping, got {type(manifest).__name__}")

    log.info("loading manifest: %s", manifest_path)
    hero = await ManifestHero.connect(
        manifest_path=manifest_path,
        world_url=world_url,
        gateway_url=gateway_url,
        auth_token=auth_token,
    )
    runner = ManifestHero(
        hero_id=hero.hero_id,
        name=hero.name,
        auth_token=hero.auth_token,
        world_url=hero.world_url,
        gateway_url=hero.gateway_url,
        manifest=manifest,
    )
    await runner.run()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="arena",
        description="Run a hero manifest. Your YAML is your hero — no Python required.",
    )
    parser.add_argument("manifest", help="Path to the hero's YAML manifest")
    parser.add_argument(
        "--world", default="http://localhost:47800",
        help="World API URL (default: http://localhost:47800)",
    )
    parser.add_argument(
        "--gateway", default="http://localhost:47801",
        help="LLM Gateway URL (default: http://localhost:47801)",
    )
    parser.add_argument(
        "--token", default=None,
        help=(
            "Auth token from the /create success page. Use this when "
            "attaching the bot to a hero you registered via the web — "
            "the SDK skips re-registration and writes a local cache "
            "file so future runs don't need the flag."
        ),
    )
    args = parser.parse_args(argv)

    try:
        asyncio.run(run(
            args.manifest,
            world_url=args.world,
            gateway_url=args.gateway,
            auth_token=args.token,
        ))
    except KeyboardInterrupt:
        log.info("stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
