"""Protocol dataclasses shared across client / prompt / parser modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
