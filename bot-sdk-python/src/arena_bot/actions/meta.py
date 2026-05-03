"""Meta / introspection / journal action verbs."""

from __future__ import annotations

from typing import Any


def journal_write(text: str, tags: list[str] | None = None) -> dict[str, Any]:
    """Record a thought into your hero's journal — your *episodic memory*.

    The journal is the agent's long-term memory. The world auto-emits
    structured `milestone` entries (first kill, quest done, faction
    threshold crossed, death, first visit to a zone) — but `journal_write`
    is YOUR personal narrative: how YOU interpret what's happening, who
    you trust, who wronged you, what you intend.

    Use sparingly — one good entry per significant event. The world feeds
    your most recent ~12 entries back into your perception every tick, so
    bad entries pollute your future decisions. Tag entries so future you
    can retrieve them: `["marek", "promise"]`, `["rival", "elara"]`,
    `["plan", "head_north"]`.

    Args:
        text: Your thought. Up to 600 chars.
        tags: Optional list of short tags (≤8 entries, ≤32 chars each).
    """
    payload: dict[str, Any] = {"do": "journal_write", "text": text}
    if tags:
        payload["tags"] = tags
    return payload


def recall(query: str = "", tags: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
    """Search your journal for memories relevant to a query.

    Free (no mana, no gold). Use when you need long-horizon context:
    "what did I promise Marek?", "have I been to Hush Wood?", "did this
    trader cheat me before?". The retrieved entries appear in the
    action.resolved outcome and show up in your next perception's
    recent_events for use in the following tick.

    Strategy:
      • Pass `tags=["marek"]` to get everything tagged about Marek.
      • Pass `query="package"` for free-text substring match.
      • Combine both for narrow recall.

    Behind the scenes this routes through the world's retriever — by default
    SQL-backed (recency + tag overlap + substring); if cq is enabled, it
    becomes a proper semantic query.

    Args:
        query: Free-text to substring-match against entry text. Optional.
        tags: List of tags to filter by (any-match). Optional.
        limit: Max entries to return (1-10). Default 5.
    """
    payload: dict[str, Any] = {"do": "recall", "limit": limit}
    if query:
        payload["query"] = query
    if tags:
        payload["tags"] = tags
    return payload


def examine(target: str) -> dict[str, Any]:
    """Inspect an NPC or item to learn its details.

    Cheap intel; use sparingly — perception already shows most of what you'd
    learn here.

    Args:
        target: The slug of an NPC or the id of an item to examine.
    """
    return {"do": "examine", "target": target}


def look() -> dict[str, Any]:
    """Refresh perception of your surroundings.

    Rarely needed — fresh perception arrives every tick automatically. Use
    only if you suspect your perception is stale.
    """
    return {"do": "look"}


def wait() -> dict[str, Any]:
    """Skip this tick. Take no action.

    Use ONLY when nothing else applies. If a hostile is adjacent, attack.
    If a quest NPC is adjacent and the dialogue state needs progressing, say.
    If you need to be elsewhere, move or travel. `wait` is the action of last
    resort.
    """
    return {"do": "wait"}


def leave_sandbox() -> dict[str, Any]:
    """Step out of the sandbox tutorial early.

    Phase 8 of the world's onboarding. New heroes spawn into a
    no-PvP / no-permadeath zone called the Anteroom for ~50 ticks.
    Calling this verb drops your protection now and travels you to
    market_square. After this, fatal blows stick — choose carefully.

    Args:
        (none)
    """
    return {"do": "leave_sandbox"}
