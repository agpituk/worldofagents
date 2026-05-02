"""Shared decision logic for ManagedHeroTask (server-side) and
ManifestHero (SDK-side).

Pre-fix, both runtimes implemented reflex-eval → composite-expansion →
invoke_llm-dispatch independently. They drifted (P2-2 composite
interrupt landed in managed but not SDK), and a fix that touched one
side would silently leave the other broken — which directly
contradicts the design's "fairness on leaderboards" promise (a hero
hosted by world-api should behave identically to one hosted on the
player's laptop).

This module owns the loop. Both wrappers feed in:
  - the parsed manifest pieces (reflex engine, composite map)
  - the current decision state (composite queue, name)
  - a perception
  - an `on_invoke_llm` callable that handles the gateway call
    (the only piece that actually differs between transports)

…and get back a (action, debug) pair. State mutations to the queue/
name are returned via the dataclass for the caller to persist.

The public surface is `decide_one(...)`. Tests pin the contract; both
wrappers are expected to converge on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional


@dataclass
class HeroDecisionState:
    """Mutable per-hero decision state. Both wrappers store an instance
    on their hero/task object and pass it through decide_one()."""

    composite_queue: list[dict[str, Any]] = field(default_factory=list)
    composite_name: Optional[str] = None


def parse_abilities(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Extract the {ability_name: [primitive_step_dicts]} map from a
    manifest. Defensive: drops malformed steps and ignores non-dict
    abilities — manifest authors will catch typos at deploy time
    rather than mid-tick."""
    inner = manifest.get("hero") if isinstance(manifest.get("hero"), dict) else manifest
    abilities = (inner or {}).get("abilities") or {}
    out: dict[str, list[dict[str, Any]]] = {}
    if isinstance(abilities, dict):
        for name, spec in abilities.items():
            if not isinstance(spec, dict):
                continue
            steps = spec.get("steps") or spec.get("decompose") or []
            if isinstance(steps, list):
                out[str(name)] = [
                    s for s in steps if isinstance(s, dict) and s.get("do")
                ]
    return out


def parse_persona(manifest: dict[str, Any]) -> dict[str, str]:
    """Extract bio + goal + model_id + system_summary from a manifest.
    Returned as a flat dict so wrappers can splat into their own slots
    without coupling to a class layout."""
    inner = manifest.get("hero") if isinstance(manifest.get("hero"), dict) else manifest
    inner = inner or {}
    bio = inner.get("bio") or ""
    memory_block = inner.get("memory") or {}
    memory_init = memory_block.get("initial") or {}
    goal = memory_init.get("goal") or "Survive."
    system_summary = (memory_block.get("system_summary") or "").strip()
    models_block = inner.get("models") or {}
    model_alias = inner.get("model") or "cheap"
    spec = models_block.get(model_alias) if isinstance(models_block, dict) else None
    model_id = ((spec or {}).get("model") if isinstance(spec, dict) else None) or "qwen3-4b"
    return {
        "bio": bio, "goal": goal, "system_summary": system_summary, "model_id": model_id,
    }


# Type alias: the wrapper's gateway-call function. Returns the
# already-parsed action dict (the wrapper does its own parsing).
OnInvokeLlm = Callable[[Any], Awaitable[dict[str, Any]]]


async def decide_one(
    *,
    state: HeroDecisionState,
    perception: Any,
    reflex_engine: Any,
    abilities: dict[str, list[dict[str, Any]]],
    on_invoke_llm: OnInvokeLlm,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """One tick of decision-making. Returns (action, debug).

    Order of operations (canonical, both wrappers):

      1. If a composite is in flight, re-evaluate reflexes against the
         fresh perception. If a reflex fires AND its action is not the
         in-flight composite (which would loop), abandon the queue and
         dispatch the interrupt action through the same expansion path
         as a cold-start decision. This is FIX_PLAN P2-2.

      2. Otherwise drain the next primitive step.

      3. If no composite is in flight, evaluate reflexes. If none match,
         emit `wait`. If one matches, expand composites or dispatch
         invoke_llm or pass through the primitive.

    The `on_invoke_llm` callable is the ONLY place the two wrappers
    differ — managed runs it in-process via httpx; SDK runs it through
    the Hero.think() retry chain.
    """

    if state.composite_queue:
        interrupt_action, interrupt_debug = reflex_engine.evaluate_with_debug(perception)
        if interrupt_action is not None and interrupt_action.get("do") not in (
            state.composite_name, None,
        ):
            interrupted_name = state.composite_name
            remaining = len(state.composite_queue)
            state.composite_queue = []
            state.composite_name = None
            interrupt_marker = {
                "via": "composite_interrupted",
                "interrupted_composite": interrupted_name,
                "remaining_was": remaining,
                "by_reflex_index": (interrupt_debug or {}).get("reflex_index"),
                "when": (interrupt_debug or {}).get("when"),
            }
            action, debug = await _post_reflex(
                state=state, perception=perception, action=interrupt_action,
                debug=interrupt_debug, abilities=abilities, on_invoke_llm=on_invoke_llm,
            )
            debug = {**(debug or {}), "interrupt": interrupt_marker}
            return action, debug

        step = state.composite_queue.pop(0)
        debug = {"via": "composite", "composite": state.composite_name,
                 "remaining": len(state.composite_queue)}
        if not state.composite_queue:
            state.composite_name = None
        return dict(step), debug

    action, debug = reflex_engine.evaluate_with_debug(perception)
    if action is None:
        return {"do": "wait"}, {"reflex_index": -1, "note": "no reflex matched"}

    return await _post_reflex(
        state=state, perception=perception, action=action, debug=debug,
        abilities=abilities, on_invoke_llm=on_invoke_llm,
    )


async def _post_reflex(
    *,
    state: HeroDecisionState,
    perception: Any,
    action: dict[str, Any],
    debug: dict[str, Any] | None,
    abilities: dict[str, list[dict[str, Any]]],
    on_invoke_llm: OnInvokeLlm,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Common tail: composite-expand or invoke_llm or pass-through."""
    verb = action.get("do")

    if verb in abilities:
        name = verb
        steps = list(abilities[name])
        if steps:
            state.composite_name = name
            state.composite_queue = steps[1:]
            first = steps[0]
            d_debug = {"via": "composite_start", "composite": name,
                       "remaining": len(state.composite_queue),
                       "reflex_index": (debug or {}).get("reflex_index"),
                       "when": (debug or {}).get("when")}
            return dict(first), d_debug

    if verb == "invoke_llm":
        llm_action = await on_invoke_llm(perception)
        d_debug = {"via": "invoke_llm",
                   "reflex_index": (debug or {}).get("reflex_index"),
                   "when": (debug or {}).get("when")}
        return llm_action, d_debug

    return action, debug
