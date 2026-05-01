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
from arena_bot.reflexes import ReflexEngine


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
        inner = (manifest or {}).get("hero", manifest or {})
        self._reflexes = ReflexEngine(inner.get("reflexes") or [])
        self._bio = inner.get("bio") or ""
        memory_block = inner.get("memory") or {}
        memory_init = memory_block.get("initial") or {}
        self._goal = memory_init.get("goal") or "Survive. Adventure. Make decisions in character."
        # Durable persona context fed into every LLM prompt — the YAML's
        # answer to "what does this hero remember about who they are even
        # when nothing in perception reminds them?"
        self._system_summary = (memory_block.get("system_summary") or "").strip()
        models_block = inner.get("models") or {}
        model_alias = inner.get("model") or "cheap"
        model_spec = models_block.get(model_alias) if isinstance(models_block, dict) else None
        self._model_id = (
            (model_spec or {}).get("model") if isinstance(model_spec, dict) else None
        ) or "qwen3-4b"

        # Composite abilities — name → list[primitive action dicts].
        abilities = inner.get("abilities") or {}
        self._abilities: dict[str, list[dict[str, Any]]] = {}
        if isinstance(abilities, dict):
            for name, spec in abilities.items():
                if not isinstance(spec, dict):
                    continue
                steps = spec.get("steps") or spec.get("decompose") or []
                if isinstance(steps, list):
                    self._abilities[str(name)] = [s for s in steps if isinstance(s, dict) and s.get("do")]
        self._composite_queue: list[dict[str, Any]] = []
        self._composite_name: str | None = None

    async def decide(self, perception: Perception) -> Decision:
        # If a composite is in flight, dispatch the next primitive step.
        if self._composite_queue:
            step = self._composite_queue.pop(0)
            debug = {
                "reflex_index": -1,
                "via": "composite",
                "composite": self._composite_name,
                "remaining": len(self._composite_queue),
            }
            if not self._composite_queue:
                self._composite_name = None
            return Decision(kind="reflex", action=dict(step), debug=debug)

        action, debug = self._reflexes.evaluate_with_debug(perception)
        if action is None:
            return Decision(
                kind="reflex",
                action={"do": "wait"},
                debug={"reflex_index": -1, "note": "no reflex matched"},
            )

        # Composite expansion: if the action's `do` matches a named ability,
        # queue its steps and dispatch the first one this tick.
        if action.get("do") in self._abilities:
            name = action["do"]
            steps = list(self._abilities[name])
            if steps:
                self._composite_name = name
                self._composite_queue = steps[1:]
                first = steps[0]
                d_debug = {
                    "reflex_index": (debug or {}).get("reflex_index"),
                    "when": (debug or {}).get("when"),
                    "via": "composite_start",
                    "composite": name,
                    "remaining": len(self._composite_queue),
                }
                return Decision(kind="reflex", action=dict(first), debug=d_debug)

        if action.get("do") == "invoke_llm":
            d = await self.llm_tool_action(
                perception=perception,
                model=self._model_id,
                bio=self._bio,
                goal=self._goal,
                system_summary=self._system_summary,
                fallback={"do": "wait"},
            )
            d.debug = {
                "reflex_index": (debug or {}).get("reflex_index"),
                "when": (debug or {}).get("when"),
                "via": "invoke_llm",
            }
            return d
        return Decision(kind="reflex", action=action, debug=debug)


async def run(manifest_path: str | Path, *, world_url: str, gateway_url: str) -> None:
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
    args = parser.parse_args(argv)

    try:
        asyncio.run(run(args.manifest, world_url=args.world, gateway_url=args.gateway))
    except KeyboardInterrupt:
        log.info("stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
