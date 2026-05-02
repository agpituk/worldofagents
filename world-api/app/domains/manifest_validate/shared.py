"""Shared constants used by the manifest validator and any siblings that
need to reason about verb categories without importing the full router."""

from __future__ import annotations

# `invoke_llm` is a runtime-only meta-verb that escalates a reflex into
# a tool-calling LLM round. It's not in VALID_VERBS — composites and
# overrides cannot reference it.
META_VERBS: frozenset[str] = frozenset({"invoke_llm"})
