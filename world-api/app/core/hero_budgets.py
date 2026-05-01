"""INT- and WIS-derived budgets for a hero's LLM environment.

DESIGN.md §2.3 calls this the "genius mechanic": INT funds the per-tick
thinking budget (tokens + mana regen), WIS funds the size of what the
hero can perceive (journal slices, look radius). Without this module the
stats are decorative — every hero sees the same blob and casts at the
same cadence regardless of their build.

Formulas are calibrated so a default 10/10 hero reproduces the values
that were hard-coded before this module existed: mana regen = 1,
journal_recent = 12, journal_relevant = 5, look_radius = max(2, 2+wis//4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.models import Hero

# Baselines reproduce the pre-budget hard-coded values at stat = 10.
_TOKENS_BASE = 256
_TOKENS_PER_INT = 32           # INT 10 → 576, INT 25 → 1056, INT 5 → 416
_MANA_REGEN_INT_THRESHOLD = 10  # below this regen stays at 1
_MANA_REGEN_PER_INT = 4        # INT 10 → 1, INT 14 → 2, INT 18 → 3, INT 25 → 4
_JOURNAL_RECENT_BASE = 7       # WIS 10 → 12, WIS 5 → 9, WIS 25 → 19
_JOURNAL_RECENT_PER_2WIS = 1
_JOURNAL_RELEVANT_BASE = 3     # WIS 10 → 5, WIS 5 → 4, WIS 25 → 8
_JOURNAL_RELEVANT_PER_5WIS = 1


def max_tokens_per_tick(hero: Hero) -> int:
    return _TOKENS_BASE + hero.int_ * _TOKENS_PER_INT


def mana_regen_per_tick(hero: Hero) -> int:
    extra = max(0, hero.int_ - _MANA_REGEN_INT_THRESHOLD) // _MANA_REGEN_PER_INT
    return 1 + extra


def journal_recent_limit(hero: Hero) -> int:
    return _JOURNAL_RECENT_BASE + hero.wis // 2 * _JOURNAL_RECENT_PER_2WIS


def journal_relevant_k(hero: Hero) -> int:
    return _JOURNAL_RELEVANT_BASE + hero.wis // 5 * _JOURNAL_RELEVANT_PER_5WIS


def look_radius(hero: Hero) -> int:
    return max(2, 2 + hero.wis // 4)


# ---------------------------------------------------------------------------
# Perception budget (P0-2) — caps on what perception_for serialises
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PerceptionBudget:
    """Maximum number of entries from each list type that perception_for
    serialises into the LLM payload. Lists past the cap are sorted by
    relevance and truncated, not random-sampled. WIS scales every cap so
    a sage genuinely sees more than a fool.

    Defaults pick "comfortable" numbers for a 10/10 hero in the smaller
    seeded zones; enough for a busy market but bounded so a worst-case
    zone with 100 NPCs cannot blow up the prompt.
    """

    max_inventory: int
    max_visible_npcs: int
    max_visible_heroes: int
    max_memory_tags: int


# WIS 5 → 10/8/5/32, WIS 10 → 16/12/8/64, WIS 25 → 31/24/17/184.
_INVENTORY_BASE = 6
_INVENTORY_PER_WIS = 1
_NPC_BASE = 4
_NPC_PER_2WIS = 1
_HERO_BASE = 3
_HERO_PER_2WIS = 1
_MEMORY_TAG_BASE = 24
_MEMORY_TAG_PER_WIS = 4


def perception_budget(hero: Hero) -> PerceptionBudget:
    return PerceptionBudget(
        max_inventory=_INVENTORY_BASE + hero.wis * _INVENTORY_PER_WIS,
        max_visible_npcs=_NPC_BASE + hero.wis // 2 * _NPC_PER_2WIS,
        max_visible_heroes=_HERO_BASE + hero.wis // 2 * _HERO_PER_2WIS,
        max_memory_tags=_MEMORY_TAG_BASE + hero.wis * _MEMORY_TAG_PER_WIS,
    )


# Fraction of max_tokens_per_tick the perception payload alone is allowed
# to take. The system + tools prompt eats the rest; if perception alone
# blows past this fraction, trim further before sending to the model.
PERCEPTION_TOKEN_FRACTION = 0.5


def perception_token_ceiling(hero: Hero) -> int:
    """Hard ceiling on the perception payload's estimated token count.
    Used by perception_for to decide whether to trim further past the
    WIS-derived list caps."""
    return max(64, int(max_tokens_per_tick(hero) * PERCEPTION_TOKEN_FRACTION))
