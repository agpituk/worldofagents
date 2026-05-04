"""Shared constants used by the manifest validator and any siblings that
need to reason about verb categories without importing the full router."""

from __future__ import annotations

# `invoke_llm` is a runtime-only meta-verb that escalates a reflex into
# a tool-calling LLM round. It's not in VALID_VERBS — composites and
# overrides cannot reference it.
META_VERBS: frozenset[str] = frozenset({"invoke_llm"})

# Convenience verbs the SDK's `resolve_action()` (arena_bot/reflexes.py)
# expands at runtime to a concrete primitive based on the current
# perception (e.g. `attack_nearest_hostile` → `attack(target=<slug>)`).
# They never reach the dispatcher — so they're not in VALID_VERBS — but
# the validator must accept them in reflex.then.do and composite steps,
# because both the bot-sdk runtime and the world-api managed runner
# resolve them before submitting the action.
SDK_CONVENIENCE_VERBS: frozenset[str] = frozenset({
    "move_to_npc",
    "move_to_nearest_hostile",
    "attack_nearest_hostile",
    "move_to_nearest_hero",
    "attack_nearest_hero",
})
