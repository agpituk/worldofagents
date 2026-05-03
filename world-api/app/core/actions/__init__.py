"""Action resolution package.

Routes a hero's submitted action to the right category-specific handler
and assembles the perception payload the LLM sees each tick. Originally
a single 3,745-line `actions.py`; split into per-category modules so
any one of them stays small enough to read end-to-end.

Module map:
  • _result      — the `ResolutionResult` dataclass every handler returns.
  • _helpers     — skill / xp / inventory / gold / journal helpers shared
                   across categories.
  • titles       — skill rank labels + top_title_for.
  • statuses     — bless / blind / bleed / regrowth tick + apply.
  • inventory    — journal_write, store/withdraw, buy_house.
  • equipment    — equip, unequip.
  • gathering    — gather, fish, craft.
  • trade        — buy, sell.
  • magic        — cast, spell-effect dispatch, tame, learn.
  • quests       — accept_quest, claim_reward, steal.
  • contracts    — post/claim/cancel_contract, defense + bounty payouts,
                   tournaments, trade-offers, recall.
  • combat       — attack, attack_hero, flee, hero death/respawn.
  • movement     — move, travel.
  • social       — say, examine, pickup, drop, give.
  • sandbox      — leave_sandbox, _evict_expired_sandbox_heroes.
  • perception   — visibility helpers + perception_for.
  • dispatcher   — `resolve()` switch.

Public surface (re-exported here so existing
`from app.core.actions import resolve` style imports keep working):
  resolve, perception_for, tick_statuses, defending_this_tick,
  skill_titles_for, top_title_for, JOURNAL_WRITE_PER_TICK_LIMIT,
  ResolutionResult.

A handful of underscore-prefixed names are also re-exported because
external modules import them by name (hero/schemas, hero/router,
tournament/close, npc/behaviors, core/combat, core/tick).
"""

from app.core.actions._helpers import (  # noqa: F401
    _current_tick,
    _grant_rep,
    _grant_xp,
    _hero_gold,
    _hero_skill_cap,
    _hero_skill_total,
    _journal_milestone,
    _reputation_for,
    _set_hero_gold,
    _validate_action_shape,
    defending_this_tick,
)
from app.core.actions._result import ResolutionResult  # noqa: F401
from app.core.actions.combat import (  # noqa: F401
    _resolve_hero_death_or_respawn,
)
from app.core.actions.dispatcher import resolve  # noqa: F401
from app.core.actions.inventory import JOURNAL_WRITE_PER_TICK_LIMIT  # noqa: F401
from app.core.actions.perception import _journal_relevant, perception_for  # noqa: F401
from app.core.actions.sandbox import _evict_expired_sandbox_heroes  # noqa: F401
from app.core.actions.statuses import tick_statuses  # noqa: F401
from app.core.actions.titles import (  # noqa: F401
    _SKILL_TITLE_NOUN,
    _skill_rank,
    skill_titles_for,
    top_title_for,
)


__all__ = [
    "JOURNAL_WRITE_PER_TICK_LIMIT",
    "ResolutionResult",
    "_SKILL_TITLE_NOUN",
    "_current_tick",
    "_evict_expired_sandbox_heroes",
    "_grant_rep",
    "_grant_xp",
    "_hero_gold",
    "_hero_skill_cap",
    "_hero_skill_total",
    "_journal_milestone",
    "_journal_relevant",
    "_reputation_for",
    "_resolve_hero_death_or_respawn",
    "_set_hero_gold",
    "_skill_rank",
    "_validate_action_shape",
    "defending_this_tick",
    "perception_for",
    "resolve",
    "skill_titles_for",
    "tick_statuses",
    "top_title_for",
]
