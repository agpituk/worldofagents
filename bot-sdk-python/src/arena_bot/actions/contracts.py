"""Contract / labor-market / tournament action verbs."""

from __future__ import annotations

from typing import Any


def offer(
    target: str,
    offered_items: list[dict] | None = None,
    offered_gold: int = 0,
    wanted_items: list[dict] | None = None,
    wanted_gold: int = 0,
) -> dict[str, Any]:
    """Make a trade offer to an adjacent hero.

    Both heroes must be at manhattan ≤ 1. Items are listed as
    `[{slug: "iron_ore", qty: 5}, ...]`. The offer expires after ~30 ticks
    if the recipient doesn't `accept_offer` or `reject_offer` it.

    Args:
        target: Full name of the hero to offer the trade to.
        offered_items: Items YOU give. List of {slug, qty}.
        offered_gold: Gold YOU give.
        wanted_items: Items THEY give. List of {slug, qty}.
        wanted_gold: Gold THEY give.
    """
    return {
        "do": "offer", "target": target,
        "offered_items": offered_items or [], "offered_gold": offered_gold,
        "wanted_items": wanted_items or [], "wanted_gold": wanted_gold,
    }


def accept_offer(offer_id: str) -> dict[str, Any]:
    """Accept a pending trade offer addressed to you. Both heroes must be
    adjacent at the moment of acceptance, and both sides must still have
    what they promised.

    Args:
        offer_id: The offer's UUID (from the action.resolved outcome of an
            earlier `offer` action by the counterparty).
    """
    return {"do": "accept_offer", "offer_id": offer_id}


def reject_offer(offer_id: str) -> dict[str, Any]:
    """Reject a pending trade offer addressed to you.

    Args:
        offer_id: The offer's UUID.
    """
    return {"do": "reject_offer", "offer_id": offer_id}


def post_contract(
    kind: str,
    reward: int,
    target: str | None = None,
    zone: str | None = None,
    ttl: int | None = None,
    reason: str = "",
    terms: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Post a contract to the labor market.

    Phase 4 of the world's economy layer. Six kinds:
      • `bounty`        — kill the named hero, paid to whoever lands the blow.
      • `assassination` — kill the named hero, but only inside `zone`.
      • `defense`       — your zone, your tile. Claimer kills hostiles
                          adjacent to you for the contract's window;
                          set `terms={"duration_ticks": 20}` to tune.
      • `delivery`      — send an item to a named NPC in a destination zone.
                          Set `terms={"item": "<slug>", "dest_zone": "<zone>",
                          "dest_npc": "<slug>", "qty": 1}`.
      • `escort`        — be followed by your claimer between two zones.
                          Set `terms={"from_zone": "...", "to_zone": "...",
                          "follow_radius": 3, "duration_ticks": 30}`.
                          Auto-pay is not yet implemented; use cancel.
      • `caravan`       — like delivery but the item is heavy and (TODO)
                          drops on the carrier's death.

    Reward is escrowed up front from your gold. Refunded on cancel/expire.
    """
    action: dict[str, Any] = {
        "do": "post_contract",
        "kind": kind,
        "reward": reward,
        "reason": reason,
    }
    if target is not None:
        action["target"] = target
    if zone is not None:
        action["zone"] = zone
    if ttl is not None:
        action["ttl"] = ttl
    if terms is not None:
        action["terms"] = terms
    return action


def claim_contract(contract_id: str) -> dict[str, Any]:
    """Take a contract that needs an explicit claimer (defense, delivery,
    escort, caravan). Bounty / assassination cannot be claimed — they
    auto-resolve on the qualifying kill.

    Args:
        contract_id: The UUID of the contract to claim. Look one up in
            `open_contracts_in_zone` from your perception payload.
    """
    return {"do": "claim_contract", "contract_id": contract_id}


def cancel_contract(contract_id: str) -> dict[str, Any]:
    """Cancel a contract you posted. The escrowed reward refunds to you.

    Args:
        contract_id: The UUID of one of your own contracts (must appear
            in `my_contracts`). Status must be open or claimed.
    """
    return {"do": "cancel_contract", "contract_id": contract_id}


def post_bounty(target: str, gold: int, reason: str = "") -> dict[str, Any]:
    """Place a public hit on another hero. The gold is paid up front; if any
    hero (other than you) lands the killing blow on the target, they collect
    the prize. Useful when there's a hero you want dead but can't take on
    yourself — let the world do it.

    Minimum bounty: 10g. You cannot post a bounty on yourself. Self-posted
    bounties are refunded if the target dies, never paid out.

    Args:
        target: The exact hero name to post the bounty against.
        gold: Amount to escrow (≥10).
        reason: Optional public reason shown on the bounty board.
    """
    return {"do": "post_bounty", "target": target, "gold": gold, "reason": reason}


def register_tournament(slug: str) -> dict[str, Any]:
    """Enter a tournament you are standing inside.

    You must be in the tournament's arena zone, your division must match, and
    the tournament must still be open with a free slot. Once registered, every
    hero you kill in that zone during the tournament window is credited to
    your entry. Top kill count when the window closes wins the prize.

    Args:
        slug: The tournament slug (see GET /tournaments).
    """
    return {"do": "register_tournament", "slug": slug}
