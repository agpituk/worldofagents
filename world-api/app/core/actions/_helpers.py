"""Cross-category helper utilities for the actions package.

These are the small bits of logic that more than one resolver category
needs: skill XP math, the per-hero skill cap lookup, move speed, the
per-verb action-shape validator, the stack-aware inventory helpers,
gold accounting, journal milestones, reputation grants, and the
shared per-tick `defending_this_tick` set. They have no logic of their
own beyond what already lived inside the legacy actions module —
keeping them here lets every category import from a single low-level
module instead of cross-importing each other.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actions._result import ResolutionResult  # noqa: F401 (kept for type stability)
from app.core.memory import update_memory
from app.core.models import Hero, Item, JournalEntry, Quest, QuestTemplate


# Per-tick transient state for `defend` — heroes who declared defend get +5 AC for
# the rest of the tick. The set is keyed by hero_id (str). Cleared each tick
# externally by the tick engine.
defending_this_tick: set[str] = set()


# ---------------------------------------------------------------------------
# Skills + equipment helpers
# ---------------------------------------------------------------------------


def _skill_level(hero: Hero, skill: str) -> int:
    """0..100. Level = min(100, xp // 10). XP is stored in hero.skills[skill]."""
    skills = hero.skills if isinstance(hero.skills, dict) else {}
    xp = int(skills.get(skill, 0) or 0)
    return min(100, xp // 10)


def _hero_skill_cap(hero: Hero) -> int:
    """Resolved skill cap for a hero. Order:
      1. `manifest.build.skill_cap` (per-hero opt-in).
      2. `manifest.extras.build.skill_cap` (where most authors put build).
      3. `settings.skill_cap_total_default` (world-wide default; 0 = uncapped).
    Returns 0 to mean uncapped — that's the behaviour callers expect.
    """
    manifest = hero.manifest if isinstance(hero.manifest, dict) else {}
    for path in ((manifest.get("build") or {}), (manifest.get("extras") or {}).get("build") or {}):
        if isinstance(path, dict) and "skill_cap" in path:
            try:
                v = int(path["skill_cap"])
                if v > 0:
                    return v
            except (TypeError, ValueError):
                continue
    from app.core.config import settings as _settings
    return int(getattr(_settings, "skill_cap_total_default", 0) or 0)


def _hero_skill_total(hero: Hero) -> int:
    """Sum of all XP across all skills. Used for the cap check."""
    skills = hero.skills if isinstance(hero.skills, dict) else {}
    total = 0
    for v in skills.values():
        try:
            total += int(v or 0)
        except (TypeError, ValueError):
            continue
    return total


def _grant_xp(hero: Hero, skill: str, amount: int) -> None:
    """Grant `amount` XP into `skill`. If the hero has opted into a skill
    cap (`manifest.build.skill_cap`) and is at or over that cap, the
    grant is silently dropped — the verb still resolves, just no XP. We
    keep this in the helper rather than per-call sites so every grant
    path (gather/craft/cast/melee/stealth/taming) shares one rule."""
    cap = _hero_skill_cap(hero)
    if cap > 0:
        current_total = _hero_skill_total(hero)
        if current_total >= cap:
            return  # at/over cap — drop the grant
        # Trim grant if it would push us over the cap.
        if current_total + amount > cap:
            amount = max(0, cap - current_total)
        if amount <= 0:
            return
    skills = dict(hero.skills) if isinstance(hero.skills, dict) else {}
    skills[skill] = int(skills.get(skill, 0) or 0) + amount
    hero.skills = skills


# ---------------------------------------------------------------------------
# Stat-derived helpers
# ---------------------------------------------------------------------------


def _move_speed(hero: Hero) -> int:
    return max(1, 1 + hero.dex // 8)


# ---------------------------------------------------------------------------
# Reputation + journaling + tick lookups
# ---------------------------------------------------------------------------


def _reputation_for(hero: "Hero") -> dict[str, Any]:
    """Public reputation counters. Sourced from hero.memory (kills,
    pvp_kills) plus derived flags (status). Surfaced to peers via
    visible_heroes and to the LLM via perception, so a hero deciding
    whether to trust a stranger can see "killed 3 heroes" before
    accepting their contract."""
    mem = hero.memory if isinstance(hero.memory, dict) else {}
    return {
        "kills": int(mem.get("kills", 0) or 0),
        "pvp_kills": int(mem.get("pvp_kills", 0) or 0),
        "dead": hero.status == "dead",
    }


def _increment_kills(db: Session, hero: Hero, *, victim_kind: str) -> None:
    """Bump `hero.memory.kills` (always) and `hero.memory.pvp_kills`
    (only when victim was another hero). Goes through `update_memory`
    so the bump emits a memory.mutated event that spectators see."""
    mem = hero.memory if isinstance(hero.memory, dict) else {}
    new_kills = int(mem.get("kills", 0) or 0) + 1
    changes: dict[str, int] = {"kills": new_kills}
    if victim_kind == "hero":
        changes["pvp_kills"] = int(mem.get("pvp_kills", 0) or 0) + 1
    update_memory(db, hero, source=f"kill_{victim_kind}", **changes)


def _current_tick(db: Session) -> int:
    from app.core.models import Tick as _T
    return int(db.scalar(select(_T.id).order_by(_T.id.desc()).limit(1)) or 0)


def _journal_milestone(
    db: Session, hero: Hero, *, text: str, tags: list[str], dedupe: bool = True
) -> JournalEntry | None:
    """Auto-emit a structured journal entry. If `dedupe`, skip if an entry
    with the same tag set already exists for this hero."""
    if dedupe:
        existing = list(
            db.scalars(
                select(JournalEntry).where(
                    JournalEntry.hero_id == hero.id, JournalEntry.kind == "milestone"
                )
            )
        )
        wanted = set(tags)
        for e in existing:
            if wanted.issubset(set(e.tags or [])):
                return None
    entry = JournalEntry(
        hero_id=hero.id, tick_id=_current_tick(db),
        kind="milestone", text=text, tags=list(tags),
    )
    db.add(entry)
    return entry


_REP_THRESHOLDS = (10, 25, 50)


def _grant_rep(hero: Hero, faction: str, amount: int, db: Session | None = None) -> None:
    rep = dict(hero.faction_rep) if isinstance(hero.faction_rep, dict) else {}
    before = int(rep.get(faction, 0) or 0)
    after = before + amount
    rep[faction] = after
    hero.faction_rep = rep
    if db is not None:
        for th in _REP_THRESHOLDS:
            if before < th <= after:
                _journal_milestone(
                    db, hero,
                    text=f"My standing with the {faction.title()} crossed {th}.",
                    tags=["milestone", "faction", faction, f"rep_{th}"],
                )


def _quest_progress(db: Session, hero: Hero, kind: str, target: str, increment: int = 1) -> list[str]:
    """Bump count_done on every active quest of (hind, target) for this hero.
    Returns the list of quest template slugs that just hit completion."""
    completed: list[str] = []
    quests = list(db.scalars(
        select(Quest).where(Quest.hero_id == hero.id, Quest.status == "active")
    ))
    for q in quests:
        tpl = db.get(QuestTemplate, q.template_slug)
        if tpl is None or tpl.kind != kind or tpl.target != target:
            continue
        q.count_done = min(tpl.count_required, q.count_done + increment)
        if q.count_done >= tpl.count_required:
            q.status = "done"
            completed.append(q.template_slug)
    return completed


# ---------------------------------------------------------------------------
# Stack-aware inventory helpers
# ---------------------------------------------------------------------------


def _inventory_total(db: Session, hero: Hero, slug: str) -> int:
    return sum(
        int(it.quantity or 1)
        for it in db.scalars(select(Item).where(Item.owner_hero_id == hero.id, Item.slug == slug))
    )


def _inventory_stack(db: Session, hero: Hero, slug: str) -> Item | None:
    """Return the (first) inventory stack matching slug, or None."""
    return db.scalar(select(Item).where(Item.owner_hero_id == hero.id, Item.slug == slug))


def _add_to_inventory(
    db: Session, hero: Hero, *,
    slug: str, name: str, kind: str, props: dict | None = None, qty: int = 1,
    description: str = "",
    crafted_by_id: uuid.UUID | None = None,
    crafted_by_name: str | None = None,
) -> Item:
    """Add `qty` of `slug` to hero's inventory, stacking onto an existing
    stack of the same slug if present; otherwise create a new row.

    When `crafted_by_id` is set, always creates a fresh row (no stacking)
    so the crafter mark survives — stacking would erase the per-item
    provenance, and a "crafted by" item being absorbed into an unmarked
    stack would silently strip the maker's name."""
    if crafted_by_id is None:
        stack = _inventory_stack(db, hero, slug)
        if stack is not None:
            stack.quantity = int(stack.quantity or 1) + qty
            return stack
    item = Item(
        id=uuid.uuid4(),
        slug=slug, name=name, kind=kind,
        description=description,
        props=dict(props or {}),
        owner_hero_id=hero.id,
        quantity=qty,
        crafted_by=crafted_by_id,
        crafted_by_name=crafted_by_name,
    )
    db.add(item)
    return item


def _consume_from_inventory(db: Session, hero: Hero, slug: str, count: int) -> int:
    """Remove `count` of `slug` from inventory across all matching stacks.
    Returns the number actually consumed (≤ count). If a stack hits 0, deletes it."""
    remaining = count
    for stack in db.scalars(select(Item).where(Item.owner_hero_id == hero.id, Item.slug == slug)):
        if remaining <= 0:
            break
        have = int(stack.quantity or 1)
        take = min(have, remaining)
        stack.quantity = have - take
        remaining -= take
        if stack.quantity <= 0:
            db.delete(stack)
    return count - remaining


def _equipped_weapon(db: Session, hero: Hero):
    """Returns the Item ORM object the hero has equipped in the weapon slot,
    or None if unarmed. The item must still be in the hero's inventory."""
    eq = hero.equipped if isinstance(hero.equipped, dict) else {}
    slug = eq.get("weapon")
    if not slug:
        return None
    return next(
        (i for i in db.scalars(select(Item).where(Item.owner_hero_id == hero.id)) if i.slug == slug),
        None,
    )


def _equipped_armor_bonus(hero: Hero, db: Session) -> int:
    """Computes the AC contribution of the hero's equipped armor.
    Phase 7: an armor's quality multiplier scales `ac_bonus`, and a
    `Reinforced` prefix or `of_warding` suffix piles `ac_bonus_extra`
    on top. Result is clamped to int (we don't want fractional AC)."""
    eq = hero.equipped if isinstance(hero.equipped, dict) else {}
    slug = eq.get("armor")
    if not slug:
        return 0
    armor = next(
        (i for i in db.scalars(select(Item).where(Item.owner_hero_id == hero.id)) if i.slug == slug),
        None,
    )
    if armor is None:
        return 0
    props = armor.props or {}
    base_ac = int(props.get("ac_bonus", 0) or 0)
    mult = float(props.get("ac_multiplier", 1.0) or 1.0)
    extra = int(props.get("ac_bonus_extra", 0) or 0)
    return int(base_ac * mult) + extra


# ---------------------------------------------------------------------------
# Gold accounting
# ---------------------------------------------------------------------------


def _hero_gold(hero: Hero) -> int:
    mem = hero.memory if isinstance(hero.memory, dict) else {}
    return int(mem.get("gold", 0) or 0)


def _set_hero_gold(db: Session, hero: Hero, value: int, *, source: str) -> None:
    """Update hero.memory.gold with audit emission (P3-1).

    `source` should name the verb/event causing the change (e.g.
    'buy_house', 'tournament_prize', 'pvp_loot') so the spectator UI
    can render gold flows attributed to the action that caused them."""
    update_memory(db, hero, source=source, gold=max(0, value))


def _effective_buy_price(entry: dict) -> int:
    """Buy price scales UP as stock dwindles below 5. Floor at base price."""
    base = int(entry.get("buy_price", 0))
    qty = entry.get("qty")
    if qty is None:
        return base  # infinite supply: base price
    deficit = max(0, 5 - int(qty))
    return int(round(base * (1 + deficit * 0.15)))


def _effective_sell_price(entry: dict) -> int:
    """Sell price scales DOWN as merchant's stock grows. Floor at 40%."""
    base = int(entry.get("sell_price", 0))
    qty = entry.get("qty")
    if qty is None:
        return base
    glut_factor = max(0.4, 1 - int(qty) * 0.03)
    return int(round(base * glut_factor))


# ---------------------------------------------------------------------------
# Misc shared utilities
# ---------------------------------------------------------------------------


def _coerce_item_list(raw: Any) -> list[dict[str, Any]]:
    """Normalize a list of {slug, qty} entries from action input."""
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        if not slug:
            continue
        out.append({"slug": str(slug), "qty": max(1, int(entry.get("qty", 1) or 1))})
    return out


# ---------------------------------------------------------------------------
# Action shape validation (P2-5)
# ---------------------------------------------------------------------------

# Per-verb required field types. Suffix "?" = optional. Verbs absent from
# this map (wait, look, defend, flee, gather, journal_write, …) have no
# required fields. Unknown verbs are caught downstream with reason=
# unknown_verb, which is the right place for that mode.
_VERB_SCHEMAS: dict[str, dict[str, type | tuple[type, ...]]] = {
    "attack": {"target": str},
    "attack_hero": {"target": str},
    "move": {"target": (list, tuple)},
    "travel": {"zone": str},
    "say": {"message": str},
    "give": {"target": str, "item": str},
    "examine": {"target": str},
    "pickup": {"slug": str},
    "drop": {"slug": str},
    "equip": {"slug": str},
    "unequip": {"slot": str},
    "craft": {"recipe": str},
    "buy": {"target": str, "item": str, "qty?": int},
    "sell": {"target": str, "item": str, "qty?": int},
    "cast": {"spell": str, "target?": str},
    "tame": {"target": str},
    "accept_quest": {"target": str},
    "store": {"slug": str, "qty?": int},
    "withdraw": {"slug": str, "qty?": int},
    "buy_house": {"slug": str},
    "accept_offer": {"offer_id": str},
    "reject_offer": {"offer_id": str},
    "post_contract": {"kind": str, "reward?": int},
    "claim_contract": {"contract_id": str},
    "cancel_contract": {"contract_id": str},
}


def _validate_action_shape(verb: str, action: dict[str, Any]) -> str | None:
    """Return None if the action's fields match the verb's schema,
    or a human-readable error string. Errors are short and structured
    enough to be useful in the spectator UI."""
    schema = _VERB_SCHEMAS.get(verb)
    if schema is None:
        return None  # unknown or schema-less verb — not our concern here
    for key, expected_type in schema.items():
        optional = key.endswith("?")
        field = key.rstrip("?")
        if field not in action or action[field] is None:
            if not optional:
                return f"missing required field '{field}'"
            continue
        value = action[field]
        if not isinstance(value, expected_type):
            got = type(value).__name__
            want = (
                expected_type.__name__
                if isinstance(expected_type, type)
                else "/".join(t.__name__ for t in expected_type)
            )
            return f"field '{field}' wants {want}, got {got}"
    return None
