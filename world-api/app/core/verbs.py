"""Canonical action-verb registry.

The world's resolver in `app.core.actions` is authoritative — drift between
this set and what the resolver actually handles means a stale validator,
not a runtime bug. Keeping this list in `core/` so both server-side
validation (`manifest_validate`) and SDK-side schema checks can share it
without crossing a domain boundary.
"""

from __future__ import annotations

VALID_VERBS: set[str] = {
    "wait", "look", "move", "say", "examine", "pickup", "drop", "give",
    "travel", "equip", "unequip", "gather", "fish", "craft",
    "buy", "sell", "cast", "learn", "steal", "tame",
    "accept_quest", "claim_reward", "journal_write", "recall",
    "store", "withdraw", "buy_house",
    "offer", "accept_offer", "reject_offer",
    "register_tournament", "post_bounty",
    "post_contract", "claim_contract", "cancel_contract",
    "attack", "attack_hero", "defend", "flee", "leave_sandbox",
}
