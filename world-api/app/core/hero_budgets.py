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
