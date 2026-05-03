"""The hero's action vocabulary as plain Python functions with rich docstrings.

Each function maps to ONE world primitive. The body returns the action dict
the World API expects; the *docstring* is what the LLM sees as the tool's
description. Rich, opinionated docstrings — with explicit IMPORTANT/usage
rules — are how a small model picks the right verb without a giant prompt.

To register a hero's tools, pass `DEFAULT_TOOLS` (or your own subset) to
`Hero.llm_tool_action()`. The SDK introspects each function's signature and
docstring to produce an OpenAI-format tool spec the model uses via native
tool-calling.

Pattern stolen wholesale from `octonous/backend/app/services/any_tool/`.
"""

from arena_bot.actions.combat import attack, attack_hero, defend, flee
from arena_bot.actions.contracts import (
    accept_offer,
    cancel_contract,
    claim_contract,
    offer,
    post_bounty,
    post_contract,
    register_tournament,
    reject_offer,
)
from arena_bot.actions.economy import buy, buy_house, sell
from arena_bot.actions.inventory import drop, equip, pickup, store, unequip, withdraw
from arena_bot.actions.magic import cast, learn
from arena_bot.actions.meta import (
    examine,
    journal_write,
    leave_sandbox,
    look,
    recall,
    wait,
)
from arena_bot.actions.movement import move, travel
from arena_bot.actions.quests import accept_quest, claim_reward
from arena_bot.actions.skills import craft, fish, gather, steal, tame
from arena_bot.actions.social import give, say


DEFAULT_TOOLS = [
    attack, attack_hero, defend, flee,
    move, travel,
    say,
    give, pickup, drop, equip, unequip,
    gather, fish, craft, buy, sell, cast, learn, steal,
    tame, accept_quest, claim_reward, journal_write, recall,
    store, withdraw, buy_house,
    offer, accept_offer, reject_offer,
    register_tournament, post_bounty,
    post_contract, claim_contract, cancel_contract,
    leave_sandbox,
    examine, look, wait,
]


__all__ = [
    "DEFAULT_TOOLS",
    "accept_offer", "accept_quest", "attack", "attack_hero",
    "buy", "buy_house",
    "cancel_contract", "cast", "claim_contract", "claim_reward", "craft",
    "defend", "drop",
    "equip", "examine",
    "fish", "flee",
    "gather", "give",
    "journal_write",
    "leave_sandbox", "learn", "look",
    "move",
    "offer",
    "pickup", "post_bounty", "post_contract",
    "recall", "register_tournament", "reject_offer",
    "say", "sell", "steal", "store",
    "tame", "travel",
    "unequip",
    "wait", "withdraw",
]
