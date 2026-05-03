"""Perception payload assembly.

Builds the JSON the LLM sees each tick. Layered helpers collect
per-zone visibility (`_visible_*_in_zone`), recall the journal slice,
gather contract bindings, then trim the whole payload to the hero's
INT-derived token ceiling.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.actions._helpers import (
    _hero_skill_cap,
    _hero_skill_total,
    _reputation_for,
)
from app.core.actions.contracts import _serialize_contract_brief
from app.core.actions.statuses import _active_statuses, _serialize_status
from app.core.actions.titles import top_title_for
from app.core.hero_budgets import (
    journal_recent_limit,
    journal_relevant_k,
    look_radius,
    perception_budget,
    perception_token_ceiling,
)
from app.core.models import Contract, Hero, Item, JournalEntry, NPC, ResourceNode, Zone


def _visible_heroes_in_zone(
    db: Session, hero: Hero, radius: int, *, limit: int | None = None
) -> list[dict[str, Any]]:
    others = (
        db.query(Hero)
        .filter(Hero.zone == hero.zone, Hero.id != hero.id, Hero.status == "alive")
        .all()
    )
    nearby = [
        o for o in others
        if abs(o.pos_x - hero.pos_x) + abs(o.pos_y - hero.pos_y) <= radius
    ]
    nearby.sort(key=lambda o: (
        abs(o.pos_x - hero.pos_x) + abs(o.pos_y - hero.pos_y),
        str(o.id),
    ))
    if limit is not None:
        nearby = nearby[:limit]
    return [
        {
            "kind": "hero",
            "id": str(o.id),
            "name": o.name,
            "pos": [o.pos_x, o.pos_y],
            "hp": o.hp,
            "top_title": top_title_for(o.skills),
            "reputation": _reputation_for(o),
        }
        for o in nearby
    ]


# Hostile NPCs sort first so a low-WIS hero in danger still sees the threat
# rather than wasting their visibility budget on the innkeeper.
_HOSTILITY_PRIORITY = {"hostile": 0, "tamed": 1, "peaceful": 2}


def _visible_npcs_in_zone(
    db: Session, hero: Hero, radius: int, *, limit: int | None = None
) -> list[dict[str, Any]]:
    npcs = list(db.scalars(select(NPC).where(NPC.zone == hero.zone, NPC.alive.is_(True))))
    nearby = [
        n for n in npcs
        if abs(n.pos_x - hero.pos_x) + abs(n.pos_y - hero.pos_y) <= radius
    ]
    nearby.sort(key=lambda n: (
        _HOSTILITY_PRIORITY.get(n.hostility, 3),
        abs(n.pos_x - hero.pos_x) + abs(n.pos_y - hero.pos_y),
        n.slug,
    ))
    if limit is not None:
        nearby = nearby[:limit]
    return [
        {
            "kind": "npc",
            "slug": n.slug,
            "name": n.name,
            "pos": [n.pos_x, n.pos_y],
            "hostility": n.hostility,
            "hp": n.hp_current,
            "hp_max": n.hp_max,
        }
        for n in nearby
    ]


def _visible_items_in_zone(db: Session, hero: Hero, radius: int) -> list[dict[str, Any]]:
    items = list(
        db.scalars(
            select(Item).where(Item.zone == hero.zone, Item.owner_hero_id.is_(None))
        )
    )
    out: list[dict[str, Any]] = []
    for i in items:
        if i.pos_x is None or i.pos_y is None:
            continue
        if abs(i.pos_x - hero.pos_x) + abs(i.pos_y - hero.pos_y) <= radius:
            props = i.props or {}
            out.append({
                "id": str(i.id),
                "slug": i.slug,
                "name": i.name,
                "kind": i.kind,
                "slot": props.get("slot"),
                "pos": [i.pos_x, i.pos_y],
            })
    return out


def _visible_resource_nodes(db: Session, hero: Hero, radius: int) -> list[dict[str, Any]]:
    nodes = list(db.scalars(select(ResourceNode).where(ResourceNode.zone == hero.zone)))
    out: list[dict[str, Any]] = []
    for n in nodes:
        if abs(n.pos_x - hero.pos_x) + abs(n.pos_y - hero.pos_y) > radius:
            continue
        out.append({
            "slug": n.slug,
            "name": n.name,
            "kind": n.kind,
            "pos": [n.pos_x, n.pos_y],
            "yield_item_slug": n.yield_item_slug,
            "skill_required": n.skill_required,
            "depleted_until_tick": n.depleted_until_tick,
        })
    return out


def _journal_relevant(db: Session, hero: Hero, n: int) -> list[dict[str, Any]]:
    """Top-K journal entries scored by the active retriever, biased by the
    hero's manifest-declared `recall_tags`. This is the "memories you carry"
    slice — durable across distance and time, not just the last few ticks."""
    mem = hero.memory if isinstance(hero.memory, dict) else {}
    tags = mem.get("recall_tags") or []
    if not isinstance(tags, list) or not tags:
        return []
    from app.core.retriever import get_retriever
    try:
        hits = get_retriever().recall(
            db, hero_id=hero.id, query="", tags=[str(t) for t in tags][:8], limit=n,
        )
    except Exception:
        return []
    out = []
    for h in hits or []:
        out.append({
            "tick_id": h.get("tick_id"),
            "kind": h.get("kind"),
            "text": h.get("text"),
            "tags": list(h.get("tags") or []),
        })
    return out


def _journal_recent(db: Session, hero: Hero, n: int) -> list[dict[str, Any]]:
    """Recency-weighted slice for the LLM context."""
    rows = list(
        db.scalars(
            select(JournalEntry)
            .where(JournalEntry.hero_id == hero.id)
            .order_by(JournalEntry.id.desc())
            .limit(n)
        )
    )
    out = [{"tick_id": r.tick_id, "kind": r.kind, "text": r.text, "tags": list(r.tags or [])} for r in rows]
    out.reverse()
    return out


def _memory_tags(db: Session, hero: Hero, limit: int) -> list[str]:
    """The set of unique tags the hero has earned in their journal — fed to
    the bot's reflex evaluator as `memory_tags` so deterministic rules can
    branch on long-term memory without burning a token. Capped at `limit`,
    biased toward tags from the most recent entries so the working set is
    relevant rather than archaeological."""
    rows = list(
        db.scalars(
            select(JournalEntry.tags)
            .where(JournalEntry.hero_id == hero.id)
            .order_by(JournalEntry.id.desc())
            .limit(500)
        )
    )
    tags: set[str] = set()
    for taglist in rows:
        for t in (taglist or []):
            tags.add(str(t))
            if len(tags) >= limit:
                break
        if len(tags) >= limit:
            break
    return sorted(tags)


def _ranked_inventory(hero: Hero, items: list[Item], limit: int) -> list[Item]:
    """Sort inventory: equipped slots first (so a wizard's wand is never
    truncated off), then most-recently-acquired (id desc as a proxy until
    last_used_tick exists). Truncate at `limit`."""
    equipped_slugs = set((hero.equipped or {}).values()) if isinstance(hero.equipped, dict) else set()
    items_sorted = sorted(
        items,
        key=lambda i: (
            0 if i.slug in equipped_slugs else 1,
            -((i.id.int) if hasattr(i.id, "int") else hash(str(i.id))),
            i.slug,
        ),
    )
    return items_sorted[:limit]


# Trim order when perception still exceeds the token ceiling after
# WIS caps: drop from the lists that hurt comprehension least first.
# Visible NPCs are last because they drive combat decisions — losing
# the hostile mob standing on the hero's tile means losing the tick.
# Inventory drops before NPCs because "what's around me right now"
# matters more than "what I'm carrying" for the next-action choice.
_TRIM_PRIORITY: tuple[str, ...] = (
    "memory_tags",
    "journal_relevant",
    "journal_recent",
    "visible_heroes",
    "inventory",
    "visible_npcs",
)


def _estimate_tokens(payload: dict[str, Any]) -> int:
    """Cheap token estimator: ~4 chars per token. Matches the gateway's
    StubProvider's accounting so on-server estimates stay in the same
    units as gateway-side billing."""
    import json as _json
    return len(_json.dumps(payload, separators=(",", ":"), default=str)) // 4


def _trim_to_token_ceiling(payload: dict[str, Any], ceiling: int) -> dict[str, Any]:
    """Drop tail entries in strict priority order: drain memory_tags
    fully before touching journal_relevant, drain journal_relevant
    fully before journal_recent, and so on. Visible_npcs is last and
    only loses entries when everything cheaper is already empty."""
    if _estimate_tokens(payload) <= ceiling:
        return payload
    for key in _TRIM_PRIORITY:
        value = payload.get(key)
        if not (isinstance(value, list) and value):
            continue
        while payload[key] and _estimate_tokens(payload) > ceiling:
            payload[key] = payload[key][:-1]
        if _estimate_tokens(payload) <= ceiling:
            return payload
    return payload


def _my_contracts(db: Session, hero: Hero) -> list[dict[str, Any]]:
    """Contracts the hero is entangled with: ones they posted, plus
    ones they've claimed. Closed/expired excluded so the binding stays
    actionable. Sorted newest-first."""
    rows = list(
        db.scalars(
            select(Contract).where(
                Contract.status.in_(["open", "claimed"]),
                or_(
                    Contract.poster_hero_id == hero.id,
                    Contract.claimed_by_hero_id == hero.id,
                ),
            ).order_by(Contract.created_at_tick.desc())
        )
    )
    return [_serialize_contract_brief(c) for c in rows]


def _open_contracts_in_zone(db: Session, hero: Hero, *, limit: int = 12) -> list[dict[str, Any]]:
    """The labor market visible to a hero in their current zone. Includes:

      • zone-scoped contracts (defense, assassination, delivery,
        caravan, escort) whose `zone_scope` matches the hero's zone.
      • zone-agnostic contracts (bounty) regardless of position — the
        bounty board is global, not local.

    Excludes contracts the hero posted themselves (they already see
    those in `my_contracts`). Newest first, capped at `limit` for
    perception budget."""
    # Spectator-posted contracts have NULL poster_hero_id; SQL `!= UUID`
    # is false for NULL, so we OR-in the IS NULL branch explicitly to
    # keep those visible to all heroes.
    rows = list(
        db.scalars(
            select(Contract).where(
                Contract.status == "open",
                or_(
                    Contract.poster_hero_id.is_(None),
                    Contract.poster_hero_id != hero.id,
                ),
                or_(
                    Contract.zone_scope == hero.zone,
                    Contract.kind == "bounty",
                ),
            ).order_by(Contract.created_at_tick.desc()).limit(limit)
        )
    )
    return [_serialize_contract_brief(c) for c in rows]


def perception_for(db: Session, hero: Hero) -> dict[str, Any]:
    radius = look_radius(hero)
    budget = perception_budget(hero)
    zone = db.get(Zone, hero.zone)
    inventory_all = list(db.scalars(select(Item).where(Item.owner_hero_id == hero.id)))
    inventory = _ranked_inventory(hero, inventory_all, budget.max_inventory)
    payload = {
        "zone": {
            "slug": hero.zone,
            "name": zone.name if zone else hero.zone,
            "kind": zone.kind if zone else "unknown",
            "size": [zone.width, zone.height] if zone else [10, 10],
            "connections": zone.connections if zone else [],
        },
        "self_pos": [hero.pos_x, hero.pos_y],
        "visible_radius": radius,
        "visible_heroes": _visible_heroes_in_zone(db, hero, radius, limit=budget.max_visible_heroes),
        "visible_npcs": _visible_npcs_in_zone(db, hero, radius, limit=budget.max_visible_npcs),
        "visible_items": _visible_items_in_zone(db, hero, radius),
        "inventory": [
            {
                "id": str(i.id), "slug": i.slug, "name": i.name, "kind": i.kind,
                "qty": int(i.quantity or 1), "props": i.props or {},
            }
            for i in inventory
        ],
        "visible_resources": _visible_resource_nodes(db, hero, radius),
        # Phase 4 — contract bindings.
        "my_contracts": _my_contracts(db, hero),
        "open_contracts_in_zone": _open_contracts_in_zone(db, hero),
        # Phase 2 — status effects active on me right now.
        "my_statuses": [_serialize_status(s) for s in _active_statuses(db, hero)],
        # Phase 6 — skill cap.
        "skill_cap": _hero_skill_cap(hero),
        "skill_points_remaining": (lambda c: max(0, c - _hero_skill_total(hero)) if c > 0 else 0)(_hero_skill_cap(hero)),
        "memory": hero.memory or {},
        "journal_recent": _journal_recent(db, hero, journal_recent_limit(hero)),
        "journal_relevant": _journal_relevant(db, hero, journal_relevant_k(hero)),
        "memory_tags": _memory_tags(db, hero, budget.max_memory_tags),
    }
    # P0-2 step 3: estimate the perception's token cost. If past the
    # INT-derived ceiling, trim further from the tail of the trim-priority
    # lists. Estimate is recorded into the payload so spectators can see
    # how close to the budget the prompt got.
    ceiling = perception_token_ceiling(hero)
    payload = _trim_to_token_ceiling(payload, ceiling)
    payload["_perception_tokens_estimated"] = _estimate_tokens(payload)
    payload["_perception_tokens_ceiling"] = ceiling
    return payload
