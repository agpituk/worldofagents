"""Quest action verbs (accept + claim)."""

from __future__ import annotations

from typing import Any


def accept_quest(target: str) -> dict[str, Any]:
    """Accept a quest from an adjacent NPC. The NPC must have `quest_offered`
    set (visible via examine or NPC detail). After accepting, the quest
    appears in your active quests; world events update progress automatically.

    Args:
        target: Slug of the quest-giver NPC (must be adjacent).
    """
    return {"do": "accept_quest", "target": target}


def claim_reward(quest: str) -> dict[str, Any]:
    """Turn in a completed quest at the NPC who offered it.

    The quest must be in `done` status (count_done >= count_required) and
    you must be adjacent to the offering NPC. Pays out gold and faction rep
    per the template.

    Args:
        quest: Slug of the quest template (e.g. "rats_in_the_cisterns").
    """
    return {"do": "claim_reward", "quest": quest}
