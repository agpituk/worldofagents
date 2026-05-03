"""Social interaction action verbs."""

from __future__ import annotations

from typing import Any


def say(message: str) -> dict[str, Any]:
    """Speak aloud. NPCs adjacent to you (manhattan <= 1) hear you and react.

    Use to greet quest NPCs, accept or decline offers, ask questions. NPCs
    pattern-match keywords in your message, so be direct: short greetings,
    plain "yes"/"no", clear references to packages or names.

    Args:
        message: What to say. Keep it short and direct. Examples:
            "Hello, Marek." / "Yes, I'll take it." / "Marek sent me with a package."
    """
    return {"do": "say", "message": message}


def give(target: str, item: str) -> dict[str, Any]:
    """Hand an item from your inventory to an adjacent NPC.

    Use to deliver quest items. The target NPC must be at manhattan <= 1
    AND the item slug must appear in your `inventory` list.

    Args:
        target: The slug of the NPC to give the item to.
        item: The slug of the item from your inventory (e.g., "mareks_sealed_package").
    """
    return {"do": "give", "target": target, "item": item}
