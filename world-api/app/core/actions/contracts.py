"""Contract / tournament / trade-offer / recall action verbs.

Phase 4 of the world's economy layer. A Contract is "I'll pay you to do
X" backed by escrowed gold. Six kinds:

  bounty        — kill <target_hero>, paid to whoever lands the blow.
  assassination — like bounty but only counts inside zone_scope (or
                  a tighter window enforced by expires_at_tick).
  defense       — claimer kills any hostile in the poster's zone while
                  adjacent to the poster. One-shot payout per claim.
  delivery      — claimer `give`s a specific item to a specific NPC in
                  the destination zone.
  escort        — claimer follows the poster between two zones for K
                  ticks (auto-pay TODO; needs per-tick presence track).
  caravan       — like delivery but the item drops on death (auto-pay
                  on give like delivery; the loot-drop hook is TODO).

Status flow: open → (claimed if it's a "claimed" kind) → fulfilled
(payout) | expired (refund). Bounty / assassination skip claimed and
go open → fulfilled directly when the kill lands.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.actions._helpers import (
    _add_to_inventory,
    _coerce_item_list,
    _consume_from_inventory,
    _current_tick,
    _hero_gold,
    _inventory_stack,
    _inventory_total,
    _journal_milestone,
    _set_hero_gold,
)
from app.core.actions._result import ResolutionResult
from app.core.models import Contract, Hero, Tournament, TournamentEntry, TradeOffer


_CONTRACT_KINDS = {
    "bounty", "assassination", "defense", "delivery", "escort", "caravan",
}
_CLAIMED_KINDS = {"defense", "delivery", "escort", "caravan"}
_MIN_REWARD = 10


def _serialize_contract_brief(c: Contract) -> dict[str, Any]:
    """Compact dict for perception payloads + reflex bindings. Heavy
    fields (poster_hero_id raw, internal timestamps) are kept off the
    wire. Used by `my_contracts` and `open_contracts_in_zone`."""
    return {
        "id": str(c.id),
        "kind": c.kind,
        "poster": c.poster_name,
        "target_ref": c.target_ref,
        "reward_gold": int(c.reward_gold or 0),
        "status": c.status,
        "zone_scope": c.zone_scope,
        "reason": c.reason,
        "terms": dict(c.terms or {}),
        "created_at_tick": int(c.created_at_tick or 0),
        "expires_at_tick": c.expires_at_tick,
        "claimed_by": str(c.claimed_by_hero_id) if c.claimed_by_hero_id else None,
    }


def _resolve_post_contract(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Post a new contract. The reward gold is escrowed up front — pulled
    from the poster's wallet on success, refunded on cancel/expire, paid
    out to the claimer on fulfill."""
    kind = str(action.get("kind") or "").strip().lower()
    if kind not in _CONTRACT_KINDS:
        return ResolutionResult(
            False,
            {"verb": "post_contract", "error": f"unknown kind '{kind}'", "valid_kinds": sorted(_CONTRACT_KINDS)},
        )
    reward = int(action.get("reward") or action.get("gold") or 0)
    if reward < _MIN_REWARD:
        return ResolutionResult(
            False, {"verb": "post_contract", "error": f"minimum reward is {_MIN_REWARD}g"}
        )
    if _hero_gold(hero) < reward:
        return ResolutionResult(
            False,
            {"verb": "post_contract", "error": f"insufficient gold ({_hero_gold(hero)} < {reward})"},
        )

    target_arg = (action.get("target") or "").strip() if isinstance(action.get("target"), str) else None
    zone_arg = action.get("zone")
    if isinstance(zone_arg, str):
        zone_arg = zone_arg.strip() or None
    else:
        zone_arg = None
    ttl = action.get("ttl")
    expires_at_tick: int | None = None
    if isinstance(ttl, int) and ttl > 0:
        expires_at_tick = _current_tick(db) + ttl
    reason = str(action.get("reason") or "")[:280]
    extra_terms = action.get("terms") if isinstance(action.get("terms"), dict) else {}

    target_hero_id: uuid.UUID | None = None
    target_ref: str | None = None
    zone_scope: str | None = None
    terms: dict[str, Any] = dict(extra_terms or {})

    if kind in ("bounty", "assassination"):
        if not target_arg:
            return ResolutionResult(False, {"verb": "post_contract", "error": "missing target hero"})
        target_hero = db.scalar(select(Hero).where(Hero.name == target_arg))
        if target_hero is None:
            return ResolutionResult(False, {"verb": "post_contract", "error": "target hero not found"})
        if target_hero.id == hero.id:
            return ResolutionResult(
                False, {"verb": "post_contract", "error": "cannot post a contract on yourself"}
            )
        if target_hero.status != "alive":
            return ResolutionResult(False, {"verb": "post_contract", "error": "target is already dead"})
        target_hero_id = target_hero.id
        target_ref = target_hero.name
        if kind == "assassination":
            if not zone_arg:
                return ResolutionResult(
                    False, {"verb": "post_contract", "error": "assassination requires zone"}
                )
            zone_scope = zone_arg

    elif kind == "defense":
        zone_scope = zone_arg or hero.zone
        terms.setdefault("duration_ticks", 20)
        terms.setdefault("posted_in_zone", hero.zone)

    elif kind == "delivery" or kind == "caravan":
        item_slug = str(terms.get("item") or terms.get("item_slug") or target_arg or "")
        dest_zone = str(terms.get("dest_zone") or zone_arg or "")
        dest_npc = str(terms.get("dest_npc") or "")
        if not item_slug:
            return ResolutionResult(False, {"verb": "post_contract", "error": f"{kind} requires terms.item"})
        if not dest_zone:
            return ResolutionResult(
                False, {"verb": "post_contract", "error": f"{kind} requires terms.dest_zone"}
            )
        if not dest_npc:
            return ResolutionResult(
                False, {"verb": "post_contract", "error": f"{kind} requires terms.dest_npc"}
            )
        terms["item"] = item_slug
        terms["dest_zone"] = dest_zone
        terms["dest_npc"] = dest_npc
        terms.setdefault("qty", 1)
        if kind == "caravan":
            terms.setdefault("heavy", True)
            terms.setdefault("drop_on_death", True)
        target_ref = item_slug
        zone_scope = dest_zone

    elif kind == "escort":
        from_zone = str(terms.get("from_zone") or hero.zone)
        to_zone = str(terms.get("to_zone") or zone_arg or "")
        if not to_zone:
            return ResolutionResult(
                False, {"verb": "post_contract", "error": "escort requires terms.to_zone"}
            )
        terms["from_zone"] = from_zone
        terms["to_zone"] = to_zone
        terms.setdefault("follow_radius", 3)
        terms.setdefault("duration_ticks", 30)
        zone_scope = to_zone

    _set_hero_gold(db, hero, _hero_gold(hero) - reward, source=f"post_contract_{kind}")

    contract = Contract(
        id=uuid.uuid4(),
        kind=kind,
        poster_hero_id=hero.id,
        poster_name=hero.name,
        target_hero_id=target_hero_id,
        target_ref=target_ref,
        reward_gold=reward,
        status="open",
        zone_scope=zone_scope,
        reason=reason,
        terms=terms,
        created_at_tick=_current_tick(db),
        expires_at_tick=expires_at_tick,
    )
    db.add(contract)

    journal_text = f"Posted a {reward}g {kind} contract"
    if target_ref:
        journal_text += f" — target: {target_ref}"
    if zone_scope:
        journal_text += f" in {zone_scope.replace('_', ' ')}"
    journal_text += "."
    _journal_milestone(
        db, hero,
        text=journal_text,
        tags=["milestone", "contract_posted", kind],
        dedupe=False,
    )

    return ResolutionResult(
        True,
        {
            "verb": "post_contract",
            "contract_id": str(contract.id),
            "kind": kind,
            "target_ref": target_ref,
            "zone_scope": zone_scope,
            "reward_gold": reward,
            "expires_at_tick": expires_at_tick,
            "poster_gold_remaining": _hero_gold(hero),
        },
    )


def _resolve_claim_contract(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Take a contract that needs an explicit claimer (defense / delivery
    / escort / caravan). Bounty and assassination cannot be claimed —
    the killing blow IS the claim, automatically."""
    cid_str = str(action.get("contract_id") or "")
    try:
        cid = uuid.UUID(cid_str)
    except (TypeError, ValueError):
        return ResolutionResult(
            False, {"verb": "claim_contract", "error": "missing or malformed contract_id"}
        )
    c = db.get(Contract, cid)
    if c is None:
        return ResolutionResult(False, {"verb": "claim_contract", "error": "contract not found"})
    if c.kind not in _CLAIMED_KINDS:
        return ResolutionResult(
            False,
            {
                "verb": "claim_contract",
                "error": f"{c.kind} contracts cannot be claimed — they auto-resolve on the qualifying event",
            },
        )
    if c.status != "open":
        return ResolutionResult(
            False, {"verb": "claim_contract", "error": f"contract is {c.status}, not open"}
        )
    if c.poster_hero_id == hero.id:
        return ResolutionResult(
            False, {"verb": "claim_contract", "error": "cannot claim your own contract"}
        )
    current = _current_tick(db)
    if c.expires_at_tick is not None and current >= c.expires_at_tick:
        return ResolutionResult(
            False, {"verb": "claim_contract", "error": "contract has expired"}
        )

    c.status = "claimed"
    c.claimed_by_hero_id = hero.id
    c.claimed_at_tick = current
    if c.kind == "defense":
        terms = dict(c.terms or {})
        terms["claimed_at_tick"] = current
        c.terms = terms

    _journal_milestone(
        db, hero,
        text=f"Claimed a {c.kind} contract from {c.poster_name} ({c.reward_gold}g).",
        tags=["milestone", "contract_claimed", c.kind, str(c.id)],
        dedupe=False,
    )
    return ResolutionResult(
        True,
        {
            "verb": "claim_contract",
            "contract_id": str(c.id),
            "kind": c.kind,
            "reward_gold": int(c.reward_gold or 0),
        },
    )


def _resolve_cancel_contract(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Cancel a contract you posted. Refunds the escrowed reward to you
    if it's still open or has been claimed but not fulfilled."""
    cid_str = str(action.get("contract_id") or "")
    try:
        cid = uuid.UUID(cid_str)
    except (TypeError, ValueError):
        return ResolutionResult(
            False, {"verb": "cancel_contract", "error": "missing or malformed contract_id"}
        )
    c = db.get(Contract, cid)
    if c is None:
        return ResolutionResult(False, {"verb": "cancel_contract", "error": "contract not found"})
    if c.poster_hero_id != hero.id:
        return ResolutionResult(
            False, {"verb": "cancel_contract", "error": "you didn't post this contract"}
        )
    if c.status not in ("open", "claimed"):
        return ResolutionResult(
            False, {"verb": "cancel_contract", "error": f"contract is {c.status}, cannot cancel"}
        )

    refund = int(c.reward_gold or 0)
    _set_hero_gold(db, hero, _hero_gold(hero) + refund, source="cancel_contract")
    c.status = "expired"
    return ResolutionResult(
        True,
        {
            "verb": "cancel_contract",
            "contract_id": str(c.id),
            "kind": c.kind,
            "refunded_gold": refund,
        },
    )


def _payout_contract(
    db: Session, c: Contract, claimer: Hero, current_tick: int, *, journal: bool = True
) -> int:
    """Mark `c` fulfilled and pay the reward to `claimer`. Idempotent
    against a re-entry — checks status before paying. Returns the
    amount paid (0 if no-op)."""
    if c.status == "fulfilled":
        return 0
    reward = int(c.reward_gold or 0)
    c.status = "fulfilled"
    c.fulfilled_at_tick = current_tick
    if c.claimed_by_hero_id is None:
        c.claimed_by_hero_id = claimer.id
        c.claimed_at_tick = current_tick
    if reward > 0:
        _set_hero_gold(db, claimer, _hero_gold(claimer) + reward, source=f"contract_{c.kind}_payout")
    if journal and reward > 0:
        target_label = c.target_ref or c.zone_scope or c.kind
        _journal_milestone(
            db, claimer,
            text=f"Fulfilled {c.kind} contract on {target_label} ({reward}g).",
            tags=["milestone", "contract_fulfilled", c.kind, str(c.id)],
            dedupe=False,
        )
    return reward


def _claim_bounties_on_kill(
    db: Session, killer: Hero, victim_id: uuid.UUID, current_tick: int
) -> list[dict[str, Any]]:
    """Pay out every open bounty + qualifying assassination contract on
    `victim_id` to `killer`. Killer cannot collect their own posts —
    those are refunded instead. Assassinations only pay if the kill
    happened inside the contract's `zone_scope`."""
    open_contracts = list(
        db.scalars(
            select(Contract).where(
                Contract.target_hero_id == victim_id,
                Contract.status == "open",
                Contract.kind.in_(["bounty", "assassination"]),
            )
        )
    )
    payouts: list[dict[str, Any]] = []
    for c in open_contracts:
        if c.poster_hero_id == killer.id:
            refund = int(c.reward_gold or 0)
            if refund > 0:
                _set_hero_gold(db, killer, _hero_gold(killer) + refund, source="contract_self_refund")
            c.status = "expired"
            continue
        if c.kind == "assassination" and c.zone_scope and c.zone_scope != killer.zone:
            continue
        if c.expires_at_tick is not None and current_tick >= c.expires_at_tick:
            c.status = "expired"
            continue
        paid = _payout_contract(db, c, killer, current_tick, journal=False)
        payouts.append({
            "contract_id": str(c.id),
            "kind": c.kind,
            "gold": paid,
            "poster": c.poster_name,
        })
    if payouts:
        total = sum(p["gold"] for p in payouts)
        _journal_milestone(
            db, killer,
            text=f"Claimed {total}g across {len(payouts)} contract(s) on {open_contracts[0].target_ref}.",
            tags=["milestone", "contract_fulfilled", str(victim_id)],
            dedupe=False,
        )
    return payouts


def _resolve_defense_contracts_on_kill(
    db: Session, killer: Hero, *, victim_kind: str, current_tick: int
) -> list[dict[str, Any]]:
    """When `killer` lands a fatal blow on a hostile (mob or hero) in a
    zone where they hold an active defense contract AND they're adjacent
    to the poster, fulfill the contract."""
    contracts = list(
        db.scalars(
            select(Contract).where(
                Contract.kind == "defense",
                Contract.status == "claimed",
                Contract.claimed_by_hero_id == killer.id,
                Contract.zone_scope == killer.zone,
            )
        )
    )
    if not contracts:
        return []
    payouts: list[dict[str, Any]] = []
    for c in contracts:
        if c.poster_hero_id is None:
            continue
        poster = db.get(Hero, c.poster_hero_id)
        if poster is None or poster.status != "alive" or poster.zone != killer.zone:
            continue
        if abs(poster.pos_x - killer.pos_x) + abs(poster.pos_y - killer.pos_y) > 2:
            continue
        if c.expires_at_tick is not None and current_tick >= c.expires_at_tick:
            c.status = "expired"
            refund = int(c.reward_gold or 0)
            if refund > 0:
                _set_hero_gold(db, poster, _hero_gold(poster) + refund, source="contract_defense_expired")
            continue
        paid = _payout_contract(db, c, killer, current_tick)
        payouts.append({
            "contract_id": str(c.id),
            "kind": "defense",
            "gold": paid,
            "poster": c.poster_name,
        })
    return payouts


def _resolve_register_tournament(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Register the hero into a tournament. Division must match (featherweight
    can only enter featherweight tournaments, etc.). The hero must be in the
    tournament's zone at registration time."""
    slug = str(action.get("slug") or "")
    if not slug:
        return ResolutionResult(False, {"verb": "register_tournament", "error": "missing slug"})
    t = db.get(Tournament, slug)
    if t is None:
        return ResolutionResult(False, {"verb": "register_tournament", "error": "tournament not found"})
    if t.status not in ("open", "in_progress"):
        return ResolutionResult(False, {"verb": "register_tournament", "error": f"registration closed (status={t.status})"})
    if hero.division != t.division:
        return ResolutionResult(
            False,
            {"verb": "register_tournament", "error": f"division mismatch ({hero.division} vs {t.division})"},
        )
    if hero.zone != t.zone:
        return ResolutionResult(False, {"verb": "register_tournament", "error": f"register inside the arena ({t.zone})"})
    existing = db.scalar(
        select(TournamentEntry).where(
            TournamentEntry.tournament_slug == slug, TournamentEntry.hero_id == hero.id
        )
    )
    if existing is not None:
        return ResolutionResult(False, {"verb": "register_tournament", "error": "already registered"})
    count = db.scalar(
        select(func.count(TournamentEntry.id)).where(TournamentEntry.tournament_slug == slug)
    ) or 0
    if int(count) >= t.max_entries:
        return ResolutionResult(False, {"verb": "register_tournament", "error": "tournament full"})

    entry = TournamentEntry(
        id=uuid.uuid4(),
        tournament_slug=slug, hero_id=hero.id,
        kills=0, status="registered", registered_at_tick=_current_tick(db),
    )
    db.add(entry)
    _journal_milestone(
        db, hero,
        text=f"Registered for {t.name}. Brackets close at tick {t.ends_at_tick}.",
        tags=["milestone", "tournament_registered", slug],
    )
    return ResolutionResult(
        True,
        {
            "verb": "register_tournament", "tournament": slug,
            "name": t.name, "division": t.division,
            "ends_at_tick": t.ends_at_tick,
            "prize_gold": t.prize_gold,
        },
    )


def _resolve_offer(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Hero A offers items+gold to hero B in exchange for items+gold.
    The offer sits in the trade_offers table until B accepts/rejects.
    Both heroes must be adjacent (manhattan ≤ 1) at the time of offering."""
    target_name = str(action.get("target") or "")
    if not target_name:
        return ResolutionResult(False, {"verb": "offer", "error": "missing target"})
    target = db.scalar(select(Hero).where(Hero.name == target_name))
    if target is None or target.id == hero.id or target.zone != hero.zone:
        return ResolutionResult(False, {"verb": "offer", "error": "target not in this zone"})
    if abs(target.pos_x - hero.pos_x) + abs(target.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "offer", "error": "target not adjacent"})

    offered_items = _coerce_item_list(action.get("offered_items"))
    wanted_items = _coerce_item_list(action.get("wanted_items"))
    offered_gold = max(0, int(action.get("offered_gold", 0) or 0))
    wanted_gold = max(0, int(action.get("wanted_gold", 0) or 0))

    if not offered_items and offered_gold == 0 and not wanted_items and wanted_gold == 0:
        return ResolutionResult(False, {"verb": "offer", "error": "empty trade"})

    for entry in offered_items:
        have = _inventory_total(db, hero, entry["slug"])
        if have < entry["qty"]:
            return ResolutionResult(False, {"verb": "offer", "error": f"have {have}× {entry['slug']}, need {entry['qty']}"})
    if _hero_gold(hero) < offered_gold:
        return ResolutionResult(False, {"verb": "offer", "error": f"insufficient gold ({_hero_gold(hero)} < {offered_gold})"})

    expires = _current_tick(db) + 30  # ~3 minutes at 6s/tick
    offer = TradeOffer(
        id=uuid.uuid4(),
        from_hero_id=hero.id, to_hero_id=target.id,
        offered_items=offered_items, offered_gold=offered_gold,
        wanted_items=wanted_items, wanted_gold=wanted_gold,
        status="pending", expires_at_tick=expires,
    )
    db.add(offer)
    return ResolutionResult(True, {
        "verb": "offer", "offer_id": str(offer.id), "to": target.name,
        "offered_items": offered_items, "offered_gold": offered_gold,
        "wanted_items": wanted_items, "wanted_gold": wanted_gold,
        "expires_at_tick": expires,
    })


def _resolve_accept_offer(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Accept a pending offer addressed to this hero. Adjacency required at
    accept time too. Resolves instantly: both sides exchange items + gold.

    P1-3: lock the offer row + both hero rows for the duration of the
    handler. On Postgres this serialises concurrent accepts of the same
    offer; on SQLite it's a no-op (writes already serialise) but the
    re-check after the lock guards against logic-level TOCTOU regardless.
    """
    offer_id = action.get("offer_id")
    if not offer_id:
        return ResolutionResult(False, {"verb": "accept_offer", "error": "missing offer_id"})
    try:
        offer_uuid = uuid.UUID(str(offer_id))
    except ValueError:
        return ResolutionResult(False, {"verb": "accept_offer", "error": "bad offer_id"})

    offer = db.scalar(
        select(TradeOffer).where(TradeOffer.id == offer_uuid).with_for_update()
    )
    if offer is None:
        return ResolutionResult(False, {"verb": "accept_offer", "error": "offer not found"})
    if offer.to_hero_id != hero.id:
        return ResolutionResult(False, {"verb": "accept_offer", "error": "not the addressee"})
    if offer.status != "pending":
        return ResolutionResult(False, {"verb": "accept_offer", "error": f"offer is {offer.status}"})
    current = _current_tick(db)
    if offer.expires_at_tick and current > offer.expires_at_tick:
        offer.status = "expired"
        return ResolutionResult(False, {"verb": "accept_offer", "error": "offer expired"})

    other = db.scalar(
        select(Hero).where(Hero.id == offer.from_hero_id).with_for_update()
    )
    db.scalar(select(Hero).where(Hero.id == hero.id).with_for_update())
    if other is None or other.zone != hero.zone:
        return ResolutionResult(False, {"verb": "accept_offer", "error": "counterparty not in zone"})
    if abs(other.pos_x - hero.pos_x) + abs(other.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "accept_offer", "error": "counterparty not adjacent"})

    for entry in (offer.offered_items or []):
        if _inventory_total(db, other, entry["slug"]) < entry["qty"]:
            return ResolutionResult(False, {"verb": "accept_offer", "error": f"counterparty short on {entry['slug']}"})
    if _hero_gold(other) < (offer.offered_gold or 0):
        return ResolutionResult(False, {"verb": "accept_offer", "error": "counterparty short on gold"})
    for entry in (offer.wanted_items or []):
        if _inventory_total(db, hero, entry["slug"]) < entry["qty"]:
            return ResolutionResult(False, {"verb": "accept_offer", "error": f"you are short on {entry['slug']}"})
    if _hero_gold(hero) < (offer.wanted_gold or 0):
        return ResolutionResult(False, {"verb": "accept_offer", "error": "you are short on gold"})

    for entry in (offer.offered_items or []):
        stack = _inventory_stack(db, other, entry["slug"])
        if stack is None:
            return ResolutionResult(False, {"verb": "accept_offer", "error": "internal: stack vanished"})
        name, kind, props, desc = stack.name, stack.kind, dict(stack.props or {}), stack.description
        _consume_from_inventory(db, other, entry["slug"], entry["qty"])
        _add_to_inventory(db, hero, slug=entry["slug"], name=name, kind=kind, props=props, description=desc, qty=entry["qty"])
    if offer.offered_gold:
        _set_hero_gold(db, other, _hero_gold(other) - offer.offered_gold, source="trade_accept")
        _set_hero_gold(db, hero, _hero_gold(hero) + offer.offered_gold, source="trade_accept")

    for entry in (offer.wanted_items or []):
        stack = _inventory_stack(db, hero, entry["slug"])
        if stack is None:
            return ResolutionResult(False, {"verb": "accept_offer", "error": "internal: stack vanished"})
        name, kind, props, desc = stack.name, stack.kind, dict(stack.props or {}), stack.description
        _consume_from_inventory(db, hero, entry["slug"], entry["qty"])
        _add_to_inventory(db, other, slug=entry["slug"], name=name, kind=kind, props=props, description=desc, qty=entry["qty"])
    if offer.wanted_gold:
        _set_hero_gold(db, hero, _hero_gold(hero) - offer.wanted_gold, source="trade_accept")
        _set_hero_gold(db, other, _hero_gold(other) + offer.wanted_gold, source="trade_accept")

    offer.status = "accepted"
    return ResolutionResult(True, {
        "verb": "accept_offer", "offer_id": str(offer.id),
        "from": other.name, "to": hero.name,
        "exchanged_items_to_you": offer.offered_items,
        "exchanged_gold_to_you": offer.offered_gold,
        "given_items_to_them": offer.wanted_items,
        "given_gold_to_them": offer.wanted_gold,
    })


def _resolve_reject_offer(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    offer_id = action.get("offer_id")
    if not offer_id:
        return ResolutionResult(False, {"verb": "reject_offer", "error": "missing offer_id"})
    try:
        offer = db.get(TradeOffer, uuid.UUID(str(offer_id)))
    except ValueError:
        return ResolutionResult(False, {"verb": "reject_offer", "error": "bad offer_id"})
    if offer is None or offer.to_hero_id != hero.id:
        return ResolutionResult(False, {"verb": "reject_offer", "error": "not your offer"})
    if offer.status != "pending":
        return ResolutionResult(False, {"verb": "reject_offer", "error": f"offer is {offer.status}"})
    offer.status = "rejected"
    return ResolutionResult(True, {"verb": "reject_offer", "offer_id": str(offer.id)})


def _resolve_recall(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """The hero asks the retriever for relevant memories. Free (no mana cost,
    no token spend on the world side); the retrieved memories appear in the
    action.resolved outcome and surface in the next tick's recent_events."""
    from app.core.retriever import get_retriever
    query = str(action.get("query") or "")
    tags_arg = action.get("tags") or []
    if not isinstance(tags_arg, list):
        tags_arg = []
    limit = max(1, min(10, int(action.get("limit", 5) or 5)))
    hits = get_retriever().recall(
        db, hero_id=hero.id, query=query, tags=[str(t) for t in tags_arg], limit=limit
    )
    return ResolutionResult(
        True,
        {
            "verb": "recall",
            "query": query,
            "tags": list(tags_arg),
            "hits": hits,
            "count": len(hits),
        },
    )
