"""Per-verb clampable-parameter table — the source of truth for which
arguments a `clamp:` expression may target.

Built from the actual signatures in
`bot-sdk-python/src/arena_bot/actions.py:684-697` (i.e. `DEFAULT_TOOLS`),
not from the idealized table in GRAMMAR.md §3.2 — see IMPL_PLAN.md §2.1
for the divergence. The grammar shape is unchanged; only the param
names align with the real verbs.

The table is consumed by:
  • The validator — at deploy time, to reject `clamp.<param>` for
    unknown params.
  • The dispatcher — at runtime, to apply type coercion + post-clamp
    validation against the param's declared semantics.
  • The frontend's verb-spec generator (Phase 4) via
    `GET /admin/verb-catalog`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# Clamp semantics drive how the dispatcher coerces and validates the
# expression's return value:
#   • `numeric` — result coerced to int/float; clipped to server cap.
#   • `string`  — result coerced to str; truncated to length cap.
#   • `slug`    — result must be a string in the legal-set per server
#                 perception (e.g., a known NPC slug at this tile);
#                 invalid → tool.clamp.invalid, fall back to requested.
#   • `tile`    — 2-tuple/list of ints; checked vs zone bounds.
#   • `list`    — list of strings; per-element regex / length applied.
ClampKind = Literal["numeric", "string", "slug", "tile", "list"]


@dataclass(frozen=True)
class ClampSpec:
    kind: ClampKind
    # Optional length cap for string params.
    max_length: int | None = None
    # Optional element regex for list params (e.g. journal tags).
    element_regex: str | None = None


# Build from `DEFAULT_TOOLS` signatures — see IMPL_PLAN.md §2.1.
CLAMP_TABLE: dict[str, dict[str, ClampSpec]] = {
    # Movement
    "move":   {"target": ClampSpec(kind="tile")},
    "travel": {"zone": ClampSpec(kind="slug")},
    # Combat
    "attack":      {"target": ClampSpec(kind="slug")},
    "attack_hero": {"target": ClampSpec(kind="slug")},
    # Social
    "say": {"message": ClampSpec(kind="string", max_length=400)},
    # Items
    "give":    {"target": ClampSpec(kind="slug"), "item": ClampSpec(kind="slug")},
    "pickup":  {"slug": ClampSpec(kind="slug")},
    "drop":    {"slug": ClampSpec(kind="slug")},
    "equip":   {"slug": ClampSpec(kind="slug")},
    "unequip": {"slot": ClampSpec(kind="string", max_length=12)},
    # Resources / crafting
    "craft": {"recipe": ClampSpec(kind="slug")},
    "buy":   {"target": ClampSpec(kind="slug"), "item": ClampSpec(kind="slug"), "qty": ClampSpec(kind="numeric")},
    "sell":  {"target": ClampSpec(kind="slug"), "item": ClampSpec(kind="slug"), "qty": ClampSpec(kind="numeric")},
    # Magic
    "cast": {"spell": ClampSpec(kind="slug"), "target": ClampSpec(kind="slug")},
    # Memory
    "journal_write": {
        "text": ClampSpec(kind="string", max_length=600),
        "tags": ClampSpec(kind="list", element_regex=r"^[a-z0-9_-]{1,32}$"),
    },
    "recall": {
        "query": ClampSpec(kind="string", max_length=200),
        "tags":  ClampSpec(kind="list", element_regex=r"^[a-z0-9_-]{1,32}$"),
        "limit": ClampSpec(kind="numeric"),
    },
    # Storage / banking
    "store":    {"slug": ClampSpec(kind="slug"), "qty": ClampSpec(kind="numeric")},
    "withdraw": {"slug": ClampSpec(kind="slug"), "qty": ClampSpec(kind="numeric")},
    # Quests
    "accept_quest": {"target": ClampSpec(kind="slug")},
    "claim_reward": {"quest": ClampSpec(kind="slug")},
    # Identity
    "examine": {"target": ClampSpec(kind="slug")},
    # Tame / steal / learn
    "tame":  {"target": ClampSpec(kind="slug")},
    "steal": {"target": ClampSpec(kind="slug"), "item": ClampSpec(kind="slug")},
    "learn": {"scroll": ClampSpec(kind="slug")},
    # Real estate
    "buy_house": {"slug": ClampSpec(kind="slug")},
    # Trade offers
    "offer":         {"target": ClampSpec(kind="slug"), "offered_gold": ClampSpec(kind="numeric"), "wanted_gold": ClampSpec(kind="numeric")},
    "accept_offer":  {"offer_id": ClampSpec(kind="string", max_length=64)},
    "reject_offer":  {"offer_id": ClampSpec(kind="string", max_length=64)},
    # Tournaments / bounties / contracts
    "register_tournament": {"slug": ClampSpec(kind="slug")},
    "post_bounty":   {"target": ClampSpec(kind="slug"), "gold": ClampSpec(kind="numeric")},
    "post_contract": {"kind": ClampSpec(kind="string", max_length=24), "reward": ClampSpec(kind="numeric"),
                      "target": ClampSpec(kind="slug"), "zone": ClampSpec(kind="slug"),
                      "ttl": ClampSpec(kind="numeric")},
    "claim_contract":  {"contract_id": ClampSpec(kind="string", max_length=64)},
    "cancel_contract": {"contract_id": ClampSpec(kind="string", max_length=64)},
}


def is_clampable(verb: str, param: str) -> bool:
    return param in CLAMP_TABLE.get(verb, {})


def clamp_spec(verb: str, param: str) -> ClampSpec | None:
    return CLAMP_TABLE.get(verb, {}).get(param)
