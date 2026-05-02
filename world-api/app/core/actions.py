"""Action validation + resolution.

Verbs supported in this batch:
  wait, look, move, say, examine, pickup, drop, give, travel,
  attack, attack_hero, defend, flee, equip, unequip, gather, fish, craft
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.dice import d20, roll
from app.core.hero_budgets import (
    journal_recent_limit,
    journal_relevant_k,
    look_radius,
    perception_budget,
    perception_token_ceiling,
)
from app.core.memory import replace_memory, update_memory
from app.core.models import Building, Contract, Hero, Item, JournalEntry, NPC, Quest, QuestTemplate, Recipe, ResourceNode, Spell, Status, Tournament, TournamentEntry, TradeOffer, Zone

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
# Phase 2 — Status effects
# ---------------------------------------------------------------------------
#
# A Status row carries a slug + payload + expiry. Multiple slugs can be
# active on a single hero at once. The cast handler writes statuses;
# the attack/AC/cast handlers read them via `_active_statuses`; the
# tick engine prunes expired rows and applies per-tick payloads
# (bleed deals damage, regrowth heals).

# Statuses that read each other to compute combat modifiers. Lookup is
# constant-time so we keep this as a flat dict.
#
#   to_hit_bonus     — added to the d20 attack roll for the affected hero.
#   ac_bonus         — added to the affected hero's AC when targeted.
#   stealth          — true while active; reveal effects strip it.
_STATUS_DEFS: dict[str, dict[str, Any]] = {
    "bless":     {"to_hit_bonus": 1},
    "blind":     {"to_hit_bonus": -3},
    "stoneskin": {"ac_bonus": 4},
    "haste":     {},  # cosmetic for now (no per-tick speed); LLM-visible
    "slow":      {},  # cosmetic for now
    "fear":      {"to_hit_bonus": -2},
    "sleep":     {"to_hit_bonus": -10, "ac_bonus": -5},  # roughly auto-fail
    "bleed":     {"per_tick_damage_dice": "1d3"},
    "regrowth":  {"per_tick_heal_dice": "1d3"},
    "stealth":   {"stealth": True},
    "tracking":  {},  # adds a perception line "tracked by <X>"
}


def _apply_status(
    db: Session, target: Hero, *, slug: str, duration_ticks: int,
    source_hero_id: uuid.UUID | None, payload: dict[str, Any] | None = None,
) -> Status:
    """Add or refresh a status on `target`. If a row with the same slug
    already exists, extend its `expires_at_tick` to whichever is later
    (refresh) and merge payload — this keeps reapplied buffs from
    stacking infinitely while letting a longer cast override a shorter
    one."""
    current = _current_tick(db)
    new_expiry = current + max(1, int(duration_ticks))
    existing = db.scalar(
        select(Status).where(Status.hero_id == target.id, Status.slug == slug)
    )
    if existing is not None:
        if existing.expires_at_tick < new_expiry:
            existing.expires_at_tick = new_expiry
        if payload:
            merged = dict(existing.payload or {})
            merged.update(payload)
            existing.payload = merged
        existing.source_hero_id = source_hero_id
        return existing
    s = Status(
        id=uuid.uuid4(),
        hero_id=target.id,
        slug=slug,
        payload=dict(payload or {}),
        applied_at_tick=current,
        expires_at_tick=new_expiry,
        source_hero_id=source_hero_id,
    )
    db.add(s)
    return s


def _active_statuses(db: Session, target: Hero) -> list[Status]:
    """All not-yet-expired statuses on `target`. Note: pruning happens
    in `tick_statuses`; readers should still filter by expires>now in
    case a query lands mid-tick (statuses may be ≤current_tick but
    haven't been pruned yet)."""
    current = _current_tick(db)
    return list(
        db.scalars(
            select(Status).where(
                Status.hero_id == target.id,
                Status.expires_at_tick > current,
            )
        )
    )


def _status_modifier(db: Session, target: Hero, *, kind: str) -> int:
    """Sum the named modifier across all active statuses on `target`.
    `kind` is one of `to_hit_bonus`, `ac_bonus`. Unknown kinds return 0
    so callers can read fearlessly."""
    total = 0
    for s in _active_statuses(db, target):
        defn = _STATUS_DEFS.get(s.slug, {})
        # Payload override beats the default — a powerful caster's
        # bless can write payload={"to_hit_bonus": 2} and we honor it.
        v = (s.payload or {}).get(kind, defn.get(kind, 0))
        if isinstance(v, int):
            total += v
    return total


def tick_statuses(db: Session, current_tick: int) -> None:
    """Apply per-tick payloads (bleed/regrowth) and prune expired rows.

    Called from the world tick once per beat, before action resolution
    so per-tick damage shows up in the same beat the model sees the
    status. Damage from bleed lands on the target's hp directly; we
    skip kill paths for now — bleed-out is a v2.x concern."""
    rows = list(db.scalars(select(Status)))
    for s in rows:
        if s.expires_at_tick <= current_tick:
            db.delete(s)
            continue
        defn = _STATUS_DEFS.get(s.slug, {})
        bleed = (s.payload or {}).get("per_tick_damage_dice") or defn.get("per_tick_damage_dice")
        heal = (s.payload or {}).get("per_tick_heal_dice") or defn.get("per_tick_heal_dice")
        if bleed or heal:
            target = db.get(Hero, s.hero_id)
            if target is None or target.status != "alive":
                continue
            if bleed:
                target.hp = max(0, target.hp - roll(str(bleed)))
            if heal:
                target.hp = min(20 + target.con, target.hp + roll(str(heal)))


def _serialize_status(s: Status) -> dict[str, Any]:
    """Compact form for perception: every active status is surfaced so
    the LLM can decide what to do about it (eg. cast purge_poison if a
    bleed is active)."""
    return {
        "slug": s.slug,
        "expires_at_tick": int(s.expires_at_tick),
        "payload": dict(s.payload or {}),
    }


# Phase 5: skill titles & reputation. These are derived (no schema change)
# but live as helpers here so every surface — HeroOut, perception,
# leaderboards, item tooltips — agrees on what "GM Fisherman" means.

# Per-skill noun used in the rendered "GM <noun>" title. Falls back to a
# title-cased version of the skill key when not listed (e.g. a future
# `bardic` skill would render as "GM Bardic" until added here).
_SKILL_TITLE_NOUN: dict[str, str] = {
    "magic": "Mage",
    "melee": "Warrior",
    "stealth": "Rogue",
    "taming": "Tamer",
    "mining": "Miner",
    "smithing": "Smith",
    "fishing": "Fisher",
    "cooking": "Cook",
    "alchemy": "Alchemist",
    "herbalism": "Herbalist",
    "lumberjacking": "Lumberjack",
    "carpentry": "Carpenter",
    "tailoring": "Tailor",
    "scribe": "Scribe",
    "tinkering": "Tinker",
}


def _skill_rank(level: int) -> str | None:
    """The text rank for a skill level: Skilled / Expert / Grandmaster /
    None. The thresholds match the roadmap: 70 / 90 / 100."""
    if level >= 100:
        return "Grandmaster"
    if level >= 90:
        return "Expert"
    if level >= 70:
        return "Skilled"
    return None


def skill_titles_for(skills_dict: dict[str, int] | None) -> dict[str, str]:
    """Per-skill rank string (Skilled / Expert / Grandmaster) keyed by
    skill name. Skills below the Skilled threshold are omitted. Used by
    HeroOut + the per-skill leaderboard."""
    out: dict[str, str] = {}
    for name, xp in (skills_dict or {}).items():
        level = min(100, int(xp or 0) // 10)
        rank = _skill_rank(level)
        if rank:
            out[name] = rank
    return out


def top_title_for(skills_dict: dict[str, int] | None) -> str | None:
    """Single rendered identity title — "GM Fisherman", "Expert Smith",
    "Skilled Mage" — picked from the hero's highest skill that's at
    least Skilled. Used by visible_heroes so peers can read identity at
    a glance, and by the hero detail page as the headline.

    Tiebreaks by skill name alphabetically so the rendering is stable
    across ticks for a hero with two skills at the same level."""
    skills_dict = skills_dict or {}
    best: tuple[int, str] | None = None  # (level, skill_name)
    for name, xp in skills_dict.items():
        level = min(100, int(xp or 0) // 10)
        if _skill_rank(level) is None:
            continue
        candidate = (level, name)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None
    level, name = best
    rank = _skill_rank(level)
    noun = _SKILL_TITLE_NOUN.get(name, name.replace("_", " ").title())
    if rank == "Grandmaster":
        return f"GM {noun}"
    return f"{rank} {noun}"


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


JOURNAL_WRITE_PER_TICK_LIMIT = 4


def _resolve_journal_write(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """The hero records their own thought into their journal.

    P2-4: capped at JOURNAL_WRITE_PER_TICK_LIMIT player entries per tick.
    Without this a misbehaving manifest can spam the table forever; the
    archival job belongs in a separate change but the rate limit closes
    the spam vector immediately.
    """
    text = (action.get("text") or "").strip()
    if not text:
        return ResolutionResult(False, {"verb": "journal_write", "error": "empty text"})
    text = text[:600]
    tags = action.get("tags") or []
    if not isinstance(tags, list):
        return ResolutionResult(False, {"verb": "journal_write", "error": "tags must be a list"})
    tags = [str(t)[:32] for t in tags][:8]
    tick_id = _current_tick(db)

    db.flush()  # make sure earlier writes within this tick are visible to count
    existing_this_tick = db.scalar(
        select(func.count(JournalEntry.id)).where(
            JournalEntry.hero_id == hero.id,
            JournalEntry.tick_id == tick_id,
            JournalEntry.kind == "player",
        )
    ) or 0
    if existing_this_tick >= JOURNAL_WRITE_PER_TICK_LIMIT:
        return ResolutionResult(
            False,
            {
                "verb": "journal_write",
                "error": f"rate limit: max {JOURNAL_WRITE_PER_TICK_LIMIT} player entries per tick",
                "reason": "journal_rate_limit",
                "limit": JOURNAL_WRITE_PER_TICK_LIMIT,
            },
        )

    db.add(JournalEntry(hero_id=hero.id, tick_id=tick_id, kind="player", text=text, tags=tags))
    # Push to the retriever (no-op for SqlRetriever; cq.propose for CqRetriever).
    from app.core.retriever import get_retriever
    get_retriever().record(db, hero_id=hero.id, text=text, tags=tags, tick_id=tick_id, kind="player")
    return ResolutionResult(True, {"verb": "journal_write", "text": text, "tags": tags})


def _adjacent_banker(db: Session, hero: Hero) -> NPC | None:
    """Return an adjacent peaceful NPC of kind='banker' if any."""
    return next(
        (
            n for n in db.scalars(select(NPC).where(NPC.zone == hero.zone, NPC.kind == "banker"))
            if abs(n.pos_x - hero.pos_x) + abs(n.pos_y - hero.pos_y) <= 1
        ),
        None,
    )


def _resolve_store(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Move N of `slug` from inventory to the hero's personal stash. Must be
    adjacent to a banker NPC (the only access point in v0.9)."""
    target_slug = str(action.get("slug") or "")
    qty = max(1, int(action.get("qty", 1) or 1))
    if not target_slug:
        return ResolutionResult(False, {"verb": "store", "error": "missing slug"})
    if _adjacent_banker(db, hero) is None:
        return ResolutionResult(False, {"verb": "store", "error": "must be adjacent to a banker"})

    have = _inventory_total(db, hero, target_slug)
    if have < qty:
        return ResolutionResult(False, {"verb": "store", "error": f"have {have}× {target_slug}, need {qty}"})

    # Take from inventory; either merge into existing stash stack or create one.
    template = _inventory_stack(db, hero, target_slug)
    if template is None:
        return ResolutionResult(False, {"verb": "store", "error": "inventory item missing"})
    name, kind, props, description = template.name, template.kind, dict(template.props or {}), template.description
    _consume_from_inventory(db, hero, target_slug, qty)

    existing_stash = db.scalar(
        select(Item).where(Item.stash_owner_hero_id == hero.id, Item.slug == target_slug)
    )
    if existing_stash is not None:
        existing_stash.quantity = int(existing_stash.quantity or 1) + qty
    else:
        db.add(Item(
            id=uuid.uuid4(),
            slug=target_slug, name=name, kind=kind, props=props, description=description,
            owner_hero_id=None, zone=None, pos_x=None, pos_y=None,
            stash_owner_hero_id=hero.id, quantity=qty,
        ))
    return ResolutionResult(True, {"verb": "store", "slug": target_slug, "qty": qty})


def _resolve_withdraw(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Pull N of `slug` from stash back into inventory. Banker required."""
    target_slug = str(action.get("slug") or "")
    qty = max(1, int(action.get("qty", 1) or 1))
    if not target_slug:
        return ResolutionResult(False, {"verb": "withdraw", "error": "missing slug"})
    if _adjacent_banker(db, hero) is None:
        return ResolutionResult(False, {"verb": "withdraw", "error": "must be adjacent to a banker"})

    stash = db.scalar(
        select(Item).where(Item.stash_owner_hero_id == hero.id, Item.slug == target_slug)
    )
    if stash is None or int(stash.quantity or 1) < qty:
        avail = int(stash.quantity or 0) if stash else 0
        return ResolutionResult(False, {"verb": "withdraw", "error": f"have {avail}× {target_slug} in stash, need {qty}"})

    name, kind, props, description = stash.name, stash.kind, dict(stash.props or {}), stash.description
    stash.quantity = int(stash.quantity or 1) - qty
    if stash.quantity <= 0:
        db.delete(stash)
    _add_to_inventory(
        db, hero,
        slug=target_slug, name=name, kind=kind, props=props, description=description, qty=qty,
    )
    return ResolutionResult(True, {"verb": "withdraw", "slug": target_slug, "qty": qty})


def _resolve_buy_house(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Buy a building. Must be adjacent to it. Pays gold, becomes owner."""
    slug = str(action.get("slug") or "")
    if not slug:
        return ResolutionResult(False, {"verb": "buy_house", "error": "missing slug"})
    b = db.get(Building, slug)
    if b is None or b.zone != hero.zone:
        return ResolutionResult(False, {"verb": "buy_house", "error": "building not here"})
    if b.owner_hero_id is not None:
        owner_match = b.owner_hero_id == hero.id
        return ResolutionResult(False, {"verb": "buy_house", "error": "already owned" + (" by you" if owner_match else "")})
    # Adjacency: hero must be at (or one tile from) any tile of the building footprint.
    in_or_near = (
        b.pos_x - 1 <= hero.pos_x <= b.pos_x + b.width
        and b.pos_y - 1 <= hero.pos_y <= b.pos_y + b.height
    )
    if not in_or_near:
        return ResolutionResult(False, {"verb": "buy_house", "error": "not adjacent to the building"})

    gold = _hero_gold(hero)
    if gold < b.gold_cost:
        return ResolutionResult(False, {"verb": "buy_house", "error": f"insufficient gold ({gold} < {b.gold_cost})"})

    _set_hero_gold(db, hero, gold - b.gold_cost, source="buy_house")
    b.owner_hero_id = hero.id
    _journal_milestone(
        db, hero,
        text=f"Bought {b.name} in {b.zone.replace('_', ' ')}. A roof of my own.",
        tags=["milestone", "house_purchased", b.slug],
    )
    return ResolutionResult(
        True,
        {"verb": "buy_house", "slug": b.slug, "name": b.name, "paid": b.gold_cost, "gold_remaining": _hero_gold(hero)},
    )


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
# Contracts (Phase 4)
# ---------------------------------------------------------------------------
#
# A Contract is "I'll pay you to do X" backed by escrowed gold. Six kinds:
#
#   bounty        — kill <target_hero>, paid to whoever lands the blow.
#   assassination — like bounty but only counts inside zone_scope (or
#                   a tighter window enforced by expires_at_tick).
#   defense       — claimer kills any hostile in the poster's zone while
#                   adjacent to the poster. One-shot payout per claim.
#   delivery      — claimer `give`s a specific item to a specific NPC in
#                   the destination zone.
#   escort        — claimer follows the poster between two zones for K
#                   ticks (auto-pay TODO; needs per-tick presence track).
#   caravan       — like delivery but the item drops on death (auto-pay
#                   on give like delivery; the loot-drop hook is TODO).
#
# Status flow: open → (claimed if it's a "claimed" kind) → fulfilled
# (payout) | expired (refund). Bounty / assassination skip claimed and
# go open → fulfilled directly when the kill lands.
#
# `_CONTRACT_KINDS` is the gate — verbs reject anything not in this set.
# `_CLAIMED_KINDS` lists the kinds that need an explicit `claim_contract`
# step before they can be fulfilled (bounty/assassination are not in
# this set; anyone with a fatal blow on the target wins).

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
    out to the claimer on fulfill.

    Validates per-kind required fields. The poster is implicit (the
    hero), so the action shape is:

        {
          do: post_contract,
          kind: bounty | assassination | defense | delivery | escort | caravan,
          reward: int,                    # min _MIN_REWARD
          target: str (kind-specific),    # hero name / npc slug / item slug
          zone: str (kind-specific),      # zone scope / dest zone / start zone
          ttl: int (optional),            # ticks until expires_at_tick
          reason: str (optional),
          terms: dict (optional, kind-specific extras),
        }
    """
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

    # ── Per-kind validation + field shaping ─────────────────────────────
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
        # Defense protects the poster's current zone. Duration is in
        # `terms.duration_ticks` (defaults to 20). Claimer must be
        # adjacent to poster when the hostile dies.
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
        # Escort is a per-tick-presence contract. We accept the post and
        # store the terms but auto-fulfill is TODO — for now the
        # claimer/poster have to cancel manually after arrival.
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

    # Escrow the reward.
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
    the killing blow IS the claim, automatically. Re-claiming an
    already-claimed contract fails."""
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
    # On claim, stamp the tick so per-tick logic (defense duration) can
    # measure from this point.
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
    if it's still open or has been claimed but not fulfilled. Heroes
    cannot cancel contracts they didn't post."""
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
    happened inside the contract's `zone_scope`. Returns a list of
    {contract_id, kind, gold, poster} dicts for the spectator stream.

    Kept for backwards-compat with the call sites in attack/cast — the
    function name is historical; it now resolves both bounties and
    assassinations.
    """
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
        # Self-posted — refund and expire instead of paying out (anti-griefing).
        if c.poster_hero_id == killer.id:
            refund = int(c.reward_gold or 0)
            if refund > 0:
                _set_hero_gold(db, killer, _hero_gold(killer) + refund, source="contract_self_refund")
            c.status = "expired"
            continue
        # Assassination is zone-scoped.
        if c.kind == "assassination" and c.zone_scope and c.zone_scope != killer.zone:
            continue
        # Expired window.
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
    to the poster, fulfill the contract. Called from the attack and
    attack_hero kill paths.

    Returns a list of fulfilled {contract_id, gold, poster} dicts.
    """
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
        # Find the poster — must be in the same zone, adjacent to killer.
        if c.poster_hero_id is None:
            continue
        poster = db.get(Hero, c.poster_hero_id)
        if poster is None or poster.status != "alive" or poster.zone != killer.zone:
            continue
        if abs(poster.pos_x - killer.pos_x) + abs(poster.pos_y - killer.pos_y) > 2:
            continue
        # Expired window.
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

    # Validate hero A actually has what they're offering.
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
        # Re-check inside the lock — by the time we got the row the offer
        # may already have been accepted, rejected, or expired by another
        # transaction. Without this check, P1-3's ghost-item duplication
        # would slip through on Postgres.
        return ResolutionResult(False, {"verb": "accept_offer", "error": f"offer is {offer.status}"})
    current = _current_tick(db)
    if offer.expires_at_tick and current > offer.expires_at_tick:
        offer.status = "expired"
        return ResolutionResult(False, {"verb": "accept_offer", "error": "offer expired"})

    # Lock both hero rows so concurrent gold/inventory writes can't
    # invalidate the balance checks below before we apply the transfer.
    other = db.scalar(
        select(Hero).where(Hero.id == offer.from_hero_id).with_for_update()
    )
    db.scalar(select(Hero).where(Hero.id == hero.id).with_for_update())
    if other is None or other.zone != hero.zone:
        return ResolutionResult(False, {"verb": "accept_offer", "error": "counterparty not in zone"})
    if abs(other.pos_x - hero.pos_x) + abs(other.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "accept_offer", "error": "counterparty not adjacent"})

    # Validate both sides still have what they promised.
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

    # Move A's items+gold to B; move B's items+gold to A.
    for entry in (offer.offered_items or []):
        # Take from A
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


def _resolve_equip(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("slug")
    if not target_slug:
        return ResolutionResult(False, {"verb": "equip", "error": "missing slug"})
    item = next(
        (i for i in db.scalars(select(Item).where(Item.owner_hero_id == hero.id)) if i.slug == target_slug),
        None,
    )
    if item is None:
        return ResolutionResult(False, {"verb": "equip", "error": f"no '{target_slug}' in inventory"})
    slot = (item.props or {}).get("slot")
    if slot not in ("weapon", "armor"):
        return ResolutionResult(False, {"verb": "equip", "error": f"item is not equippable (slot={slot!r})"})

    eq = dict(hero.equipped) if isinstance(hero.equipped, dict) else {}
    previous = eq.get(slot)
    eq[slot] = item.slug
    hero.equipped = eq
    return ResolutionResult(
        True, {"verb": "equip", "slot": slot, "slug": item.slug, "replaced": previous}
    )


def _resolve_unequip(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    slot = action.get("slot")
    if slot not in ("weapon", "armor"):
        return ResolutionResult(False, {"verb": "unequip", "error": "slot must be 'weapon' or 'armor'"})
    eq = dict(hero.equipped) if isinstance(hero.equipped, dict) else {}
    prev = eq.get(slot)
    if not prev:
        return ResolutionResult(False, {"verb": "unequip", "error": f"slot {slot} is empty"})
    eq[slot] = None
    hero.equipped = eq
    return ResolutionResult(True, {"verb": "unequip", "slot": slot, "removed": prev})


# ---------------------------------------------------------------------------
# Gathering + crafting
# ---------------------------------------------------------------------------


def _resolve_node_harvest(
    db: Session,
    hero: Hero,
    *,
    verb: str,
    node_kind_filter,  # callable(node.kind) -> bool
    no_node_error: str,
) -> ResolutionResult:
    """Shared core for `gather` and `fish`. Both walk the nodes on the hero's
    tile, pick the first non-depleted one matching `node_kind_filter`, yield
    one item, deplete the node, and grant XP into `node.skill_required`.

    The split exists so a fisher's reflex DSL can declare `do: fish` and
    only act on fishing holes (and a miner's `do: gather` skips them) —
    the verb you choose is part of the build, not just plumbing.
    """
    nodes = list(
        db.scalars(
            select(ResourceNode).where(
                ResourceNode.zone == hero.zone,
                ResourceNode.pos_x == hero.pos_x,
                ResourceNode.pos_y == hero.pos_y,
            )
        )
    )
    matching = [n for n in nodes if node_kind_filter(n.kind)]
    if not matching:
        return ResolutionResult(False, {"verb": verb, "error": no_node_error})

    from app.core.models import Tick as _T
    current_tick = int(db.scalar(select(_T.id).order_by(_T.id.desc()).limit(1)) or 0)

    for node in matching:
        if node.depleted_until_tick is not None and current_tick < node.depleted_until_tick:
            continue
        _add_to_inventory(
            db, hero,
            slug=node.yield_item_slug,
            name=node.yield_item_name,
            kind=node.yield_item_kind,
            description=f"Harvested from {node.name}.",
            qty=1,
        )
        node.depleted_until_tick = current_tick + node.respawn_after_ticks
        _grant_xp(hero, node.skill_required, 1)
        completed_quests = _quest_progress(db, hero, "gather_count", node.yield_item_slug, 1)
        return ResolutionResult(
            True,
            {
                "verb": verb,
                "node": node.slug,
                "yielded": node.yield_item_slug,
                "yielded_qty_now": _inventory_total(db, hero, node.yield_item_slug),
                "respawn_at_tick": node.depleted_until_tick,
                "skill": node.skill_required,
                "skill_xp": int((hero.skills or {}).get(node.skill_required, 0) or 0),
                "quests_completed": completed_quests,
            },
        )

    return ResolutionResult(False, {"verb": verb, "error": "node depleted, try later"})


def _resolve_gather(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Gather a non-fish resource (ore, herb, log) from a ResourceNode at
    the hero's tile. Fishing holes are excluded — use `fish` for those."""
    return _resolve_node_harvest(
        db, hero,
        verb="gather",
        node_kind_filter=lambda k: k != "fishing_hole",
        no_node_error="no resource node here",
    )


def _resolve_fish(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Fish from a fishing_hole ResourceNode at the hero's tile."""
    return _resolve_node_harvest(
        db, hero,
        verb="fish",
        node_kind_filter=lambda k: k == "fishing_hole",
        no_node_error="no fishing hole here",
    )


def _resolve_craft(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Craft a recipe at an adjacent workstation NPC."""
    recipe_slug = action.get("recipe")
    if not recipe_slug:
        return ResolutionResult(False, {"verb": "craft", "error": "missing recipe"})
    recipe = db.get(Recipe, str(recipe_slug))
    if recipe is None:
        return ResolutionResult(False, {"verb": "craft", "error": f"unknown recipe '{recipe_slug}'"})

    # Find an adjacent workstation NPC of the right kind.
    workstation = next(
        (
            n for n in db.scalars(
                select(NPC).where(NPC.zone == hero.zone, NPC.kind == recipe.workstation_kind)
            )
            if abs(n.pos_x - hero.pos_x) + abs(n.pos_y - hero.pos_y) <= 1
        ),
        None,
    )
    if workstation is None:
        return ResolutionResult(
            False,
            {"verb": "craft", "error": f"need to be adjacent to a {recipe.workstation_kind}"},
        )

    # Check skill.
    have_skill = _skill_level(hero, recipe.skill_required)
    if have_skill < recipe.skill_min:
        return ResolutionResult(
            False,
            {
                "verb": "craft",
                "error": f"{recipe.skill_required} too low ({have_skill} < {recipe.skill_min})",
            },
        )

    # Check inventory has all inputs.
    for inp in recipe.inputs:
        slug = inp["slug"]
        need = int(inp.get("count", 1))
        have = _inventory_total(db, hero, slug)
        if have < need:
            return ResolutionResult(
                False, {"verb": "craft", "error": f"need {need}× {slug}, have {have}"}
            )

    # Consume inputs from stacks.
    for inp in recipe.inputs:
        _consume_from_inventory(db, hero, inp["slug"], int(inp.get("count", 1)))

    # Phase 7 — quality + affixes. The crafter's skill in the recipe's
    # `skill_required` drives the quality tier, and a small chance of a
    # prefix/suffix scales with skill so masterworks come out interesting
    # rather than just numerically bigger. We only roll affixes for items
    # that have a `slot` (weapons / armor / trinkets) — materials and
    # consumables stay plain.
    from app.core.affixes import render_affixed_name, roll_affixes
    base_props = dict(recipe.output_props or {})
    is_gear = bool(base_props.get("slot"))
    crafter_skill_lvl = _skill_level(hero, recipe.skill_required)
    if is_gear:
        prefix_chance = 0.0 if crafter_skill_lvl < 50 else min(0.4, (crafter_skill_lvl - 50) / 100.0)
        suffix_chance = 0.0 if crafter_skill_lvl < 70 else min(0.3, (crafter_skill_lvl - 70) / 100.0)
        final_props = roll_affixes(
            base_props,
            skill_level=crafter_skill_lvl,
            prefix_chance=prefix_chance,
            suffix_chance=suffix_chance,
        )
        final_name = render_affixed_name(recipe.output_name, final_props)
    else:
        final_props = base_props
        final_name = recipe.output_name

    # Produce output and stamp the crafter mark. Crafted items always
    # spawn as a fresh row (no stacking) so the maker's name survives.
    _add_to_inventory(
        db, hero,
        slug=recipe.output_slug,
        name=final_name,
        kind=recipe.output_kind,
        description=recipe.output_description,
        props=final_props,
        qty=1,
        crafted_by_id=hero.id,
        crafted_by_name=hero.name,
    )
    _grant_xp(hero, recipe.skill_required, 2)

    # Discovery: hidden recipes don't appear in /recipes, so a successful
    # craft means the hero (or their model) figured out the input set. Mark
    # it once per hero, with a loud milestone the spectator stream picks up.
    discovery: bool = False
    if recipe.hidden:
        mem = hero.memory if isinstance(hero.memory, dict) else {}
        discovered = list(mem.get("discovered_recipes") or [])
        if recipe.slug not in discovered:
            discovered.append(recipe.slug)
            update_memory(db, hero, source="craft_hidden", discovered_recipes=discovered)
            discovery = True
            _journal_milestone(
                db, hero,
                text=f"Discovered the recipe for {recipe.name}.",
                tags=["milestone", "discovery", recipe.slug],
                dedupe=False,
            )

    return ResolutionResult(
        True,
        {
            "verb": "craft",
            "recipe": recipe.slug,
            "produced": recipe.output_slug,
            "workstation": workstation.slug,
            "skill": recipe.skill_required,
            "skill_xp": int((hero.skills or {}).get(recipe.skill_required, 0) or 0),
            "discovery": discovery,
            "hidden_recipe": bool(recipe.hidden),
        },
    )


# ---------------------------------------------------------------------------
# Buy / sell
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


def _resolve_buy(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("target")
    item_slug = action.get("item") or action.get("slug")
    qty = max(1, int(action.get("qty", 1) or 1))
    if not target_slug or not item_slug:
        return ResolutionResult(False, {"verb": "buy", "error": "need target + item"})

    npc = db.get(NPC, str(target_slug))
    if npc is None or npc.zone != hero.zone:
        return ResolutionResult(False, {"verb": "buy", "error": "merchant not in this zone"})
    if abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "buy", "error": "merchant not adjacent"})

    stock_list = list(npc.merchant_stock or [])
    idx = next((i for i, s in enumerate(stock_list) if s.get("slug") == item_slug), None)
    if idx is None or "buy_price" not in stock_list[idx]:
        return ResolutionResult(False, {"verb": "buy", "error": f"merchant doesn't sell '{item_slug}'"})
    entry = stock_list[idx]

    avail = entry.get("qty")
    if avail is not None and int(avail) < qty:
        return ResolutionResult(
            False, {"verb": "buy", "error": f"only {avail} in stock, need {qty}"}
        )

    unit_price = _effective_buy_price(entry)
    total_cost = unit_price * qty
    gold = _hero_gold(hero)
    if gold < total_cost:
        return ResolutionResult(
            False, {"verb": "buy", "error": f"insufficient gold ({gold} < {total_cost})"}
        )

    _set_hero_gold(db, hero, gold - total_cost, source="buy")
    _add_to_inventory(
        db, hero,
        slug=entry["slug"],
        name=entry.get("name", entry["slug"]),
        kind=entry.get("kind", "trinket"),
        props=entry.get("props", {}),
        description=entry.get("description", ""),
        qty=qty,
    )

    # Decrement merchant's stock if it tracks qty.
    if avail is not None:
        new_entry = dict(entry)
        new_entry["qty"] = max(0, int(avail) - qty)
        stock_list[idx] = new_entry
        npc.merchant_stock = stock_list

    return ResolutionResult(
        True,
        {
            "verb": "buy", "from": npc.slug, "item": entry["slug"],
            "qty": qty, "unit_price": unit_price, "total": total_cost,
            "gold_remaining": _hero_gold(hero),
            "stock_remaining": stock_list[idx].get("qty"),
        },
    )


def _resolve_spell_effect(
    db: Session, hero: Hero, spell: Spell, action: dict[str, Any],
    target_arg: Any, skill_lvl: int, outcome: dict[str, Any],
) -> ResolutionResult:
    """Phase 2 effect-kind dispatch: apply_status / dispel / move_self /
    move_target / summon_npc / reveal. Uses the spell's `payload` JSON
    for kind-specific tunables. Unknown kinds fall through with an
    error so a misspelled `effect_kind` in the seed is loud, not silent.
    """
    payload = dict(spell.payload or {})
    kind = spell.effect_kind

    def _resolve_target_hero(arg: Any) -> Hero | None:
        if not arg:
            return None
        return db.scalar(select(Hero).where(Hero.name == str(arg)))

    def _check_range(t_pos_x: int, t_pos_y: int) -> bool:
        return abs(t_pos_x - hero.pos_x) + abs(t_pos_y - hero.pos_y) <= spell.range

    # ── apply_status ───────────────────────────────────────────────────
    if kind == "apply_status":
        slug = str(payload.get("status") or "")
        duration = int(payload.get("duration_ticks") or 10)
        bonus_payload = dict(payload.get("payload") or {})
        if not slug:
            return ResolutionResult(False, {"verb": "cast", "error": "spell missing payload.status"})
        if spell.target_kind == "self":
            target = hero
        elif spell.target_kind == "hero":
            target = _resolve_target_hero(target_arg)
            if target is None or target.zone != hero.zone or target.status != "alive":
                return ResolutionResult(False, {"verb": "cast", "error": "target hero not reachable"})
            if not _check_range(target.pos_x, target.pos_y):
                return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
        elif spell.target_kind == "enemy":
            target = _resolve_target_hero(target_arg)
            if target is None or target.id == hero.id:
                return ResolutionResult(False, {"verb": "cast", "error": "enemy target not found"})
            zone = db.get(Zone, hero.zone)
            if zone is None or zone.kind == "sanctuary":
                return ResolutionResult(False, {"verb": "cast", "error": "PvP magic forbidden in sanctuary"})
            if target.zone != hero.zone or not _check_range(target.pos_x, target.pos_y):
                return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
        else:
            return ResolutionResult(False, {"verb": "cast", "error": f"apply_status target_kind '{spell.target_kind}' not supported"})
        _apply_status(
            db, target, slug=slug, duration_ticks=duration,
            source_hero_id=hero.id, payload=bonus_payload or None,
        )
        outcome.update(target=target.name, target_kind="hero", status_applied=slug, duration_ticks=duration)

    # ── dispel ─────────────────────────────────────────────────────────
    elif kind == "dispel":
        slugs_to_strip = list(payload.get("slugs") or ["bleed", "blind", "fear", "slow", "sleep"])
        target = hero if spell.target_kind == "self" else _resolve_target_hero(target_arg)
        if target is None:
            return ResolutionResult(False, {"verb": "cast", "error": "target not found"})
        if target.zone != hero.zone:
            return ResolutionResult(False, {"verb": "cast", "error": "target not in this zone"})
        if target.id != hero.id and not _check_range(target.pos_x, target.pos_y):
            return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
        stripped = list(
            db.scalars(
                select(Status).where(
                    Status.hero_id == target.id, Status.slug.in_(slugs_to_strip)
                )
            )
        )
        for s in stripped:
            db.delete(s)
        outcome.update(target=target.name, target_kind="hero", dispelled=[s.slug for s in stripped])

    # ── move_self (blink) ──────────────────────────────────────────────
    elif kind == "move_self":
        zone = db.get(Zone, hero.zone)
        if zone is None:
            return ResolutionResult(False, {"verb": "cast", "error": "unknown zone"})
        # target_arg is [x, y] for blink — ranges checked via spell.range.
        if not (isinstance(target_arg, list) and len(target_arg) == 2):
            return ResolutionResult(False, {"verb": "cast", "error": "blink target must be [x, y]"})
        try:
            tx, ty = int(target_arg[0]), int(target_arg[1])
        except (TypeError, ValueError):
            return ResolutionResult(False, {"verb": "cast", "error": "blink coords must be ints"})
        if not (0 <= tx < zone.width and 0 <= ty < zone.height):
            return ResolutionResult(False, {"verb": "cast", "error": "blink out of bounds"})
        if abs(tx - hero.pos_x) + abs(ty - hero.pos_y) > spell.range:
            return ResolutionResult(False, {"verb": "cast", "error": "blink out of range"})
        old = (hero.pos_x, hero.pos_y)
        hero.pos_x, hero.pos_y = tx, ty
        outcome.update(blinked_from=list(old), blinked_to=[tx, ty])

    # ── move_target (gust / push) ──────────────────────────────────────
    elif kind == "move_target":
        target = _resolve_target_hero(target_arg)
        if target is None or target.zone != hero.zone:
            return ResolutionResult(False, {"verb": "cast", "error": "target not in this zone"})
        if not _check_range(target.pos_x, target.pos_y):
            return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
        push = int(payload.get("push_tiles") or 2)
        zone = db.get(Zone, target.zone)
        dx = (target.pos_x - hero.pos_x)
        dy = (target.pos_y - hero.pos_y)
        # Push along the dominant axis, capped by zone bounds.
        if abs(dx) >= abs(dy):
            step_x = (1 if dx >= 0 else -1) * push
            new_x = max(0, min((zone.width if zone else 10) - 1, target.pos_x + step_x))
            new_y = target.pos_y
        else:
            step_y = (1 if dy >= 0 else -1) * push
            new_x = target.pos_x
            new_y = max(0, min((zone.height if zone else 10) - 1, target.pos_y + step_y))
        old = (target.pos_x, target.pos_y)
        target.pos_x, target.pos_y = new_x, new_y
        outcome.update(target=target.name, target_kind="hero", pushed_from=list(old), pushed_to=[new_x, new_y])

    # ── summon_npc ─────────────────────────────────────────────────────
    elif kind == "summon_npc":
        mob_slug_template = str(payload.get("mob") or "summoned_wisp")
        mob_name = str(payload.get("name") or "Summoned Wisp")
        mob_hp = int(payload.get("hp") or 1)
        # Spawn a uniquely-slugged NPC adjacent to the caster.
        new_slug = f"{mob_slug_template}_{uuid.uuid4().hex[:8]}"
        adjacent_pos = (hero.pos_x + 1, hero.pos_y)
        npc = NPC(
            slug=new_slug, name=mob_name, kind="mob",
            zone=hero.zone, pos_x=adjacent_pos[0], pos_y=adjacent_pos[1],
            hp_max=mob_hp, hp_current=mob_hp, ac=8,
            hostility="peaceful", alive=True, loot_gold=0,
            tameable=False, tamed_by_hero_id=hero.id,
        )
        db.add(npc)
        outcome.update(summoned_slug=new_slug, summoned_at=list(adjacent_pos))

    # ── reveal ─────────────────────────────────────────────────────────
    elif kind == "reveal":
        # Strip stealth from every hero in range.
        in_range: list[Hero] = []
        for h in db.scalars(select(Hero).where(Hero.zone == hero.zone, Hero.id != hero.id)):
            if _check_range(h.pos_x, h.pos_y):
                in_range.append(h)
        revealed: list[str] = []
        for h in in_range:
            stealth = db.scalar(
                select(Status).where(Status.hero_id == h.id, Status.slug == "stealth")
            )
            if stealth is not None:
                db.delete(stealth)
                revealed.append(h.name)
        outcome.update(revealed=revealed)

    else:
        return ResolutionResult(False, {"verb": "cast", "error": f"unsupported effect_kind '{kind}'"})

    hero.mana_current -= spell.mana_cost
    _grant_xp(hero, spell.skill_required, 1)
    outcome["mana_remaining"] = hero.mana_current
    outcome["skill_xp"] = int((hero.skills or {}).get(spell.skill_required, 0) or 0)
    outcome["effect_kind"] = kind
    return ResolutionResult(True, outcome)


def _resolve_cast(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Cast a spell the hero has learned."""
    spell_slug = action.get("spell")
    if not spell_slug:
        return ResolutionResult(False, {"verb": "cast", "error": "missing spell"})

    known = list(hero.known_spells or [])
    if spell_slug not in known:
        return ResolutionResult(False, {"verb": "cast", "error": f"spell '{spell_slug}' not known"})

    spell = db.get(Spell, str(spell_slug))
    if spell is None:
        return ResolutionResult(False, {"verb": "cast", "error": f"unknown spell '{spell_slug}'"})

    if hero.mana_current < spell.mana_cost:
        return ResolutionResult(
            False, {"verb": "cast", "error": f"insufficient mana ({hero.mana_current} < {spell.mana_cost})"}
        )

    skill_lvl = _skill_level(hero, spell.skill_required)
    if skill_lvl < spell.skill_min:
        return ResolutionResult(
            False, {"verb": "cast", "error": f"{spell.skill_required} too low ({skill_lvl} < {spell.skill_min})"}
        )

    target_arg = action.get("target")
    outcome: dict[str, Any] = {
        "verb": "cast", "spell": spell.slug, "school": spell.school,
        "mana_cost": spell.mana_cost,
    }

    # Phase 2: spells with a non-default effect_kind dispatch to a
    # dedicated handler. The default (`damage_or_heal`) keeps the v0.6
    # damage/heal flow below intact for firebolt/frost_lance/mend.
    effect_kind = getattr(spell, "effect_kind", "damage_or_heal") or "damage_or_heal"
    if effect_kind != "damage_or_heal":
        return _resolve_spell_effect(
            db, hero, spell, action, target_arg, skill_lvl, outcome,
        )

    if spell.target_kind == "self":
        # Self-heal / self-buff. heal_dice applied to caster's hp.
        if spell.heal_dice and spell.heal_dice != "0d0":
            heal = roll(spell.heal_dice) + skill_lvl // 8
            new_hp = min(20 + hero.con, hero.hp + heal)  # cap at hp_max-ish
            healed_for = new_hp - hero.hp
            hero.hp = new_hp
            outcome.update(target=hero.name, heal=healed_for, target_hp=hero.hp)

    elif spell.target_kind == "enemy":
        # Find target — first by NPC slug, then by hero name in PvP zone.
        if not target_arg:
            return ResolutionResult(False, {"verb": "cast", "error": "missing target"})
        target_npc = db.get(NPC, str(target_arg))
        target_hero = db.scalar(select(Hero).where(Hero.name == str(target_arg)))
        zone = db.get(Zone, hero.zone)

        if target_npc is not None and target_npc.alive and target_npc.zone == hero.zone:
            if abs(target_npc.pos_x - hero.pos_x) + abs(target_npc.pos_y - hero.pos_y) > spell.range:
                return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
            damage = roll(spell.damage_dice) + skill_lvl // 4
            target_npc.hp_current = max(0, target_npc.hp_current - damage)
            killed = target_npc.hp_current <= 0
            loot_gold = 0
            if killed:
                target_npc.alive = False
                loot_gold = target_npc.loot_gold
                if loot_gold > 0:
                    _set_hero_gold(
                        db, hero, _hero_gold(hero) + loot_gold,
                        source="attack_loot",
                    )
            outcome.update(
                target=target_npc.slug, target_kind="npc", damage=damage,
                target_hp_remaining=target_npc.hp_current, killed=killed, loot_gold=loot_gold,
            )

        elif target_hero is not None and target_hero.id != hero.id:
            if zone is None or zone.kind == "sanctuary":
                return ResolutionResult(False, {"verb": "cast", "error": "PvP magic forbidden in sanctuary"})
            if target_hero.zone != hero.zone:
                return ResolutionResult(False, {"verb": "cast", "error": "target not in this zone"})
            if abs(target_hero.pos_x - hero.pos_x) + abs(target_hero.pos_y - hero.pos_y) > spell.range:
                return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
            damage = roll(spell.damage_dice) + skill_lvl // 4
            target_hero.hp = max(0, target_hero.hp - damage)
            fatal = target_hero.hp <= 0
            killed = False
            if fatal:
                killed = _resolve_hero_death_or_respawn(
                    db, target_hero, current_tick=_current_tick(db)
                )
                if killed:
                    _increment_kills(db, hero, victim_kind="hero")
            outcome.update(
                target=target_hero.name, target_kind="hero", damage=damage,
                target_hp_remaining=target_hero.hp, killed=killed,
            )

        else:
            return ResolutionResult(False, {"verb": "cast", "error": "target not found"})

    elif spell.target_kind == "hero":
        # Healing another hero — allowed in any zone.
        if not target_arg:
            return ResolutionResult(False, {"verb": "cast", "error": "missing target"})
        target_hero = db.scalar(select(Hero).where(Hero.name == str(target_arg)))
        if target_hero is None or target_hero.zone != hero.zone or target_hero.status != "alive":
            return ResolutionResult(False, {"verb": "cast", "error": "target hero not reachable"})
        if abs(target_hero.pos_x - hero.pos_x) + abs(target_hero.pos_y - hero.pos_y) > spell.range:
            return ResolutionResult(False, {"verb": "cast", "error": "target out of range"})
        if spell.heal_dice and spell.heal_dice != "0d0":
            heal = roll(spell.heal_dice) + skill_lvl // 8
            new_hp = min(20 + target_hero.con, target_hero.hp + heal)
            healed_for = new_hp - target_hero.hp
            target_hero.hp = new_hp
            outcome.update(target=target_hero.name, target_kind="hero", heal=healed_for, target_hp=target_hero.hp)

    else:
        return ResolutionResult(False, {"verb": "cast", "error": f"unsupported target_kind '{spell.target_kind}'"})

    hero.mana_current -= spell.mana_cost
    _grant_xp(hero, spell.skill_required, 1)
    outcome["mana_remaining"] = hero.mana_current
    outcome["skill_xp"] = int((hero.skills or {}).get(spell.skill_required, 0) or 0)
    return ResolutionResult(True, outcome)


def _resolve_tame(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Attempt to tame an adjacent tameable mob.

    Roll: d20 + CHA/4 + WIS/4 vs DC 12. Nat 1 = mob attacks back next tick;
    nat 20 = automatic. On success the mob's hostility flips to "tamed",
    tamed_by_hero_id is set, and the pet starts following the hero around
    (handled in tick.py mob phase).
    """
    target_slug = action.get("target")
    if not target_slug:
        return ResolutionResult(False, {"verb": "tame", "error": "missing target"})

    target = db.get(NPC, str(target_slug))
    if target is None or target.zone != hero.zone:
        return ResolutionResult(False, {"verb": "tame", "error": "target not in this zone"})
    if not target.alive:
        return ResolutionResult(False, {"verb": "tame", "error": "target is dead"})
    if not target.tameable:
        return ResolutionResult(False, {"verb": "tame", "error": "target is not tameable"})
    if target.tamed_by_hero_id is not None:
        return ResolutionResult(False, {"verb": "tame", "error": "already tamed"})
    if abs(target.pos_x - hero.pos_x) + abs(target.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "tame", "error": "target not adjacent"})

    dc = 12
    roll_d20 = d20()
    total = roll_d20 + hero.cha // 4 + hero.wis // 4
    success = roll_d20 == 20 or (roll_d20 != 1 and total >= dc)
    if success:
        target.hostility = "tamed"
        target.tamed_by_hero_id = hero.id
        _grant_xp(hero, "taming", 3)
        _journal_milestone(
            db, hero,
            text=f"Tamed {target.name}. They follow me now.",
            tags=["milestone", "tamed", target.slug],
        )
    return ResolutionResult(
        True,
        {
            "verb": "tame", "target": target.slug, "success": bool(success),
            "roll": roll_d20, "total": total, "dc": dc,
            "now_tamed_by": str(hero.id) if success else None,
        },
    )


def _resolve_accept_quest(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Pick up the quest an adjacent NPC offers."""
    target_slug = action.get("target")
    if not target_slug:
        return ResolutionResult(False, {"verb": "accept_quest", "error": "missing target"})
    npc = db.get(NPC, str(target_slug))
    if npc is None or npc.zone != hero.zone:
        return ResolutionResult(False, {"verb": "accept_quest", "error": "target not in this zone"})
    if abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "accept_quest", "error": "target not adjacent"})
    if not npc.quest_offered:
        return ResolutionResult(False, {"verb": "accept_quest", "error": f"{npc.slug} offers no quest"})

    tpl = db.get(QuestTemplate, npc.quest_offered)
    if tpl is None:
        return ResolutionResult(False, {"verb": "accept_quest", "error": "quest template missing"})

    # Already have it active or done?
    existing = db.scalar(
        select(Quest).where(
            Quest.hero_id == hero.id,
            Quest.template_slug == tpl.slug,
            Quest.status.in_(["active", "done"]),
        )
    )
    if existing is not None:
        return ResolutionResult(False, {"verb": "accept_quest", "error": "already on this quest"})

    db.add(Quest(
        id=uuid.uuid4(),
        hero_id=hero.id,
        template_slug=tpl.slug,
        status="active",
        count_done=0,
    ))
    return ResolutionResult(
        True,
        {
            "verb": "accept_quest", "from": npc.slug, "quest": tpl.slug,
            "name": tpl.name, "kind": tpl.kind, "target": tpl.target,
            "count_required": tpl.count_required,
            "reward_gold": tpl.reward_gold,
            "reward_faction": tpl.reward_faction,
            "reward_faction_amount": tpl.reward_faction_amount,
        },
    )


def _resolve_claim_reward(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Turn in a completed quest. Must be adjacent to the offering NPC."""
    quest_slug = action.get("quest")
    if not quest_slug:
        return ResolutionResult(False, {"verb": "claim_reward", "error": "missing quest"})

    tpl = db.get(QuestTemplate, str(quest_slug))
    if tpl is None:
        return ResolutionResult(False, {"verb": "claim_reward", "error": "quest template missing"})

    quest = db.scalar(
        select(Quest).where(
            Quest.hero_id == hero.id,
            Quest.template_slug == tpl.slug,
            Quest.status == "done",
        )
    )
    if quest is None:
        return ResolutionResult(False, {"verb": "claim_reward", "error": "quest not done"})

    npc = db.get(NPC, tpl.offered_by)
    if npc is None or npc.zone != hero.zone or abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "claim_reward", "error": f"return to {tpl.offered_by} to claim"})

    quest.status = "claimed"
    if tpl.reward_gold:
        _set_hero_gold(db, hero, _hero_gold(hero) + tpl.reward_gold, source="quest_reward")
    if tpl.reward_faction and tpl.reward_faction_amount:
        _grant_rep(hero, tpl.reward_faction, tpl.reward_faction_amount, db=db)
    _journal_milestone(
        db, hero,
        text=f"Claimed reward from {npc.name} for '{tpl.name}': {tpl.reward_gold}g.",
        tags=["milestone", "quest_claimed", tpl.slug],
    )

    # Main-quest chain: advance to next step or award title if this was a
    # main-quest stage. The award is folded into the outcome so the
    # spectator stream can pick it up.
    from app.domains.quest.main_quest import advance_main_quest
    awarded = advance_main_quest(db, hero, tpl.slug)
    if awarded and awarded.get("title"):
        _journal_milestone(
            db, hero,
            text=f"You are now known as: {awarded['title']}.",
            tags=["milestone", "title_earned", awarded["title"].lower().replace(" ", "_")],
            dedupe=False,
        )

    return ResolutionResult(
        True,
        {
            "verb": "claim_reward", "quest": tpl.slug,
            "reward_gold": tpl.reward_gold,
            "reward_faction": tpl.reward_faction,
            "reward_faction_amount": tpl.reward_faction_amount,
            "gold_now": _hero_gold(hero),
            **(awarded or {}),
        },
    )


def _resolve_steal(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Attempt to filch an item from a merchant's stock without paying.

    Mechanics:
      • d20 + DEX/4 + stealth_lvl/4 vs target's awareness DC (15 by default)
      • on success: 1 unit of the item moves to inventory, no gold paid
      • on failure: NPC's `aware_of_thief` flag in their merchant_stock
        meta gets set; future buy/sell prices for this hero are inflated 2×
        and reputation drops. (Reputation system tba — for v0.6.4 we just
        log the event.)
      • on natural 1: dropped (caught red-handed). Visible loud event.
    """
    target_slug = action.get("target")
    item_slug = action.get("item") or action.get("slug")
    if not target_slug or not item_slug:
        return ResolutionResult(False, {"verb": "steal", "error": "need target + item"})

    npc = db.get(NPC, str(target_slug))
    if npc is None or npc.zone != hero.zone:
        return ResolutionResult(False, {"verb": "steal", "error": "target not in this zone"})
    if abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "steal", "error": "target not adjacent"})

    stock_list = list(npc.merchant_stock or [])
    idx = next((i for i, s in enumerate(stock_list) if s.get("slug") == item_slug), None)
    if idx is None:
        return ResolutionResult(False, {"verb": "steal", "error": f"target doesn't carry '{item_slug}'"})
    entry = stock_list[idx]
    avail = entry.get("qty")
    if avail is not None and int(avail) <= 0:
        return ResolutionResult(False, {"verb": "steal", "error": "out of stock"})

    awareness_dc = 15
    stealth_lvl = _skill_level(hero, "stealth")
    roll_d20 = d20()
    total = roll_d20 + (hero.dex // 4) + (stealth_lvl // 4)
    fumble = roll_d20 == 1
    success = (not fumble) and (roll_d20 == 20 or total >= awareness_dc)

    outcome: dict[str, Any] = {
        "verb": "steal",
        "from": npc.slug,
        "item": entry["slug"],
        "roll": roll_d20,
        "total": total,
        "dc": awareness_dc,
        "stealth_lvl": stealth_lvl,
        "success": success,
    }

    if success:
        _add_to_inventory(
            db, hero,
            slug=entry["slug"],
            name=entry.get("name", entry["slug"]),
            kind=entry.get("kind", "trinket"),
            props=entry.get("props", {}),
            description=entry.get("description", ""),
            qty=1,
        )
        if avail is not None:
            new_entry = dict(entry)
            new_entry["qty"] = max(0, int(avail) - 1)
            stock_list[idx] = new_entry
            npc.merchant_stock = stock_list
        _grant_xp(hero, "stealth", 2)
        outcome["stealth_xp"] = int((hero.skills or {}).get("stealth", 0) or 0)
    else:
        mem = hero.memory if isinstance(hero.memory, dict) else {}
        notes = dict(mem.get("npcs", {}))
        npc_entry = dict(notes.get(npc.slug, {}))
        npc_entry["aware_of_theft"] = True
        notes[npc.slug] = npc_entry
        update_memory(db, hero, source="steal_caught", npcs=notes)
        outcome["caught"] = True

    # Stealing always carries a faction cost — caught or not, the act is
    # against the Free Council's order. -3 council rep per attempt.
    _grant_rep(hero, "council", -3)
    outcome["council_rep_delta"] = -3
    return ResolutionResult(True, outcome)


def _resolve_learn(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Consume a scroll item from inventory; add the spell it teaches."""
    scroll_slug = action.get("scroll") or action.get("slug")
    if not scroll_slug:
        return ResolutionResult(False, {"verb": "learn", "error": "missing scroll"})
    item = _inventory_stack(db, hero, str(scroll_slug))
    if item is None:
        return ResolutionResult(False, {"verb": "learn", "error": f"no '{scroll_slug}' in inventory"})
    teaches = (item.props or {}).get("teaches")
    if not teaches:
        return ResolutionResult(False, {"verb": "learn", "error": f"'{scroll_slug}' teaches nothing"})

    spell = db.get(Spell, str(teaches))
    if spell is None:
        return ResolutionResult(False, {"verb": "learn", "error": f"unknown spell '{teaches}'"})

    known = list(hero.known_spells or [])
    if spell.slug in known:
        return ResolutionResult(False, {"verb": "learn", "error": f"already know '{spell.slug}'"})

    known.append(spell.slug)
    hero.known_spells = known
    _consume_from_inventory(db, hero, item.slug, 1)
    return ResolutionResult(
        True, {"verb": "learn", "spell": spell.slug, "consumed_scroll": scroll_slug}
    )


def _resolve_sell(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("target")
    item_slug = action.get("item") or action.get("slug")
    qty = max(1, int(action.get("qty", 1) or 1))
    if not target_slug or not item_slug:
        return ResolutionResult(False, {"verb": "sell", "error": "need target + item"})

    npc = db.get(NPC, str(target_slug))
    if npc is None or npc.zone != hero.zone:
        return ResolutionResult(False, {"verb": "sell", "error": "merchant not in this zone"})
    if abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "sell", "error": "merchant not adjacent"})

    stock_list = list(npc.merchant_stock or [])
    idx = next((i for i, s in enumerate(stock_list) if s.get("slug") == item_slug), None)
    if idx is None or "sell_price" not in stock_list[idx]:
        return ResolutionResult(False, {"verb": "sell", "error": f"merchant doesn't buy '{item_slug}'"})
    entry = stock_list[idx]

    have = _inventory_total(db, hero, item_slug)
    if have < qty:
        return ResolutionResult(False, {"verb": "sell", "error": f"have {have}× {item_slug}, need {qty}"})

    unit_price = _effective_sell_price(entry)
    payout = unit_price * qty
    _consume_from_inventory(db, hero, item_slug, qty)
    _set_hero_gold(db, hero, _hero_gold(hero) + payout, source="sell")

    # Increment merchant's stock if it tracks qty.
    if entry.get("qty") is not None:
        new_entry = dict(entry)
        new_entry["qty"] = int(entry["qty"]) + qty
        stock_list[idx] = new_entry
        npc.merchant_stock = stock_list

    return ResolutionResult(
        True,
        {
            "verb": "sell", "to": npc.slug, "item": item_slug,
            "qty": qty, "unit_price": unit_price, "total": payout,
            "gold_now": _hero_gold(hero),
            "stock_now": stock_list[idx].get("qty"),
        },
    )


@dataclass(frozen=True)
class ResolutionResult:
    ok: bool
    outcome: dict[str, Any]


# ---------------------------------------------------------------------------
# Stat-derived helpers
# ---------------------------------------------------------------------------


def _move_speed(hero: Hero) -> int:
    return max(1, 1 + hero.dex // 8)


# ---------------------------------------------------------------------------
# Perception helpers (read-only)
# ---------------------------------------------------------------------------


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
    # Closest first; tie-break by hero id so the order is deterministic.
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


# ---------------------------------------------------------------------------
# Resolve
# ---------------------------------------------------------------------------


def resolve(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    # P1-4: dead heroes cannot act. The tick loop already filters alive
    # heroes when scheduling, but managed bots can race a death write
    # over WebSocket — without this guard, a corpse mutates the world.
    if hero.status != "alive":
        return ResolutionResult(False, {"error": "hero is dead", "reason": "dead", "verb": None})

    if not isinstance(action, dict):
        return ResolutionResult(False, {"error": "action must be a dict", "verb": None})

    verb = action.get("do")
    # P2-5: shape-check the action's required fields before dispatching.
    # Catches the FIX_PLAN done-when case ({"do":"attack","target":42})
    # with a structured reason="bad_action_shape" so it lands in the
    # parse_failure stream rather than as a downstream "no such NPC".
    if isinstance(verb, str):
        shape_err = _validate_action_shape(verb, action)
        if shape_err is not None:
            return ResolutionResult(False, {
                "verb": verb,
                "error": shape_err,
                "reason": "bad_action_shape",
            })

    if verb == "wait":
        return ResolutionResult(True, {"verb": "wait"})

    if verb == "look":
        radius = look_radius(hero)
        return ResolutionResult(
            True,
            {
                "verb": "look",
                "radius": radius,
                "heroes": _visible_heroes_in_zone(db, hero, radius),
                "npcs": _visible_npcs_in_zone(db, hero, radius),
                "items": _visible_items_in_zone(db, hero, radius),
            },
        )

    if verb == "move":
        return _resolve_move(db, hero, action)

    if verb == "say":
        return _resolve_say(db, hero, action)

    if verb == "examine":
        return _resolve_examine(db, hero, action)

    if verb == "pickup":
        return _resolve_pickup(db, hero, action)

    if verb == "drop":
        return _resolve_drop(db, hero, action)

    if verb == "give":
        return _resolve_give(db, hero, action)

    if verb == "travel":
        return _resolve_travel(db, hero, action)

    if verb == "equip":
        return _resolve_equip(db, hero, action)

    if verb == "unequip":
        return _resolve_unequip(db, hero, action)

    if verb == "gather":
        return _resolve_gather(db, hero, action)

    if verb == "fish":
        return _resolve_fish(db, hero, action)

    if verb == "craft":
        return _resolve_craft(db, hero, action)

    if verb == "buy":
        return _resolve_buy(db, hero, action)

    if verb == "sell":
        return _resolve_sell(db, hero, action)

    if verb == "cast":
        return _resolve_cast(db, hero, action)

    if verb == "learn":
        return _resolve_learn(db, hero, action)

    if verb == "steal":
        return _resolve_steal(db, hero, action)

    if verb == "tame":
        return _resolve_tame(db, hero, action)

    if verb == "accept_quest":
        return _resolve_accept_quest(db, hero, action)

    if verb == "claim_reward":
        return _resolve_claim_reward(db, hero, action)

    if verb == "journal_write":
        return _resolve_journal_write(db, hero, action)

    if verb == "recall":
        return _resolve_recall(db, hero, action)

    if verb == "store":
        return _resolve_store(db, hero, action)

    if verb == "withdraw":
        return _resolve_withdraw(db, hero, action)

    if verb == "buy_house":
        return _resolve_buy_house(db, hero, action)

    if verb == "offer":
        return _resolve_offer(db, hero, action)

    if verb == "accept_offer":
        return _resolve_accept_offer(db, hero, action)

    if verb == "reject_offer":
        return _resolve_reject_offer(db, hero, action)

    if verb == "register_tournament":
        return _resolve_register_tournament(db, hero, action)

    if verb == "post_bounty":
        # Phase 4: post_bounty is a thin alias over post_contract with
        # kind="bounty" so existing manifests keep working. The action's
        # `gold` field maps to post_contract's `reward`.
        rewritten = {
            "do": "post_contract",
            "kind": "bounty",
            "target": action.get("target"),
            "reward": action.get("gold") or action.get("reward"),
            "reason": action.get("reason", ""),
        }
        return _resolve_post_contract(db, hero, rewritten)

    if verb == "post_contract":
        return _resolve_post_contract(db, hero, action)

    if verb == "claim_contract":
        return _resolve_claim_contract(db, hero, action)

    if verb == "cancel_contract":
        return _resolve_cancel_contract(db, hero, action)

    if verb == "attack":
        return _resolve_attack(db, hero, action)

    if verb == "attack_hero":
        return _resolve_attack_hero(db, hero, action)

    if verb == "defend":
        defending_this_tick.add(str(hero.id))
        return ResolutionResult(True, {"verb": "defend", "ac_bonus": 5})

    if verb == "flee":
        return _resolve_flee(db, hero, action)

    if verb == "leave_sandbox":
        return _resolve_leave_sandbox(db, hero, action)

    return ResolutionResult(
        False,
        {"verb": verb, "error": f"unknown verb '{verb}'", "reason": "unknown_verb"},
    )


# ---------------------------------------------------------------------------
# Combat resolvers
# ---------------------------------------------------------------------------


def _resolve_attack(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("target")
    if not target_slug:
        return ResolutionResult(False, {"verb": "attack", "error": "missing target"})

    target = db.get(NPC, str(target_slug))
    if target is None:
        return ResolutionResult(False, {"verb": "attack", "error": "target not found"})
    if target.zone != hero.zone:
        return ResolutionResult(False, {"verb": "attack", "error": "target not in this zone"})
    if not target.alive:
        return ResolutionResult(False, {"verb": "attack", "error": "target already dead"})
    if target.hostility != "hostile":
        return ResolutionResult(False, {"verb": "attack", "error": "target is peaceful"})
    if abs(target.pos_x - hero.pos_x) + abs(target.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "attack", "error": "target out of melee range"})

    # Equipment + skill bonuses
    weapon = _equipped_weapon(db, hero)
    weapon_props = weapon.props if weapon and isinstance(weapon.props, dict) else {}
    weapon_bonus = int(weapon_props.get("attack_bonus", 0) or 0)
    weapon_dice = weapon_props.get("damage_dice") or "1d2"
    melee_lvl = _skill_level(hero, "melee")
    skill_bonus = melee_lvl // 4  # +1 attack at level 4, +5 at level 20

    # Phase 2 — to-hit shifts from active statuses (bless +1, blind -3,
    # fear -2, sleep -10). NPC targets don't carry hero statuses so AC
    # adjustments only land on PvP targets (handled in attack_hero).
    status_to_hit = _status_modifier(db, hero, kind="to_hit_bonus")
    # Phase 7 — affix bonuses on the equipped weapon. `to_hit_bonus_extra`
    # comes from suffixes like `of_the_bear`; `crit_bonus` widens the
    # crit window from 20 to 19-20 with `keen`.
    affix_to_hit = int(weapon_props.get("to_hit_bonus_extra", 0) or 0)
    affix_crit_bonus = int(weapon_props.get("crit_bonus", 0) or 0)
    attack_roll = d20()
    attack_total = attack_roll + (hero.str_ // 4) + weapon_bonus + skill_bonus + status_to_hit + affix_to_hit
    crit_threshold = 20 - affix_crit_bonus
    crit = attack_roll >= crit_threshold
    fumble = attack_roll == 1

    if fumble:
        return ResolutionResult(
            True,
            {
                "verb": "attack", "target": target.slug, "roll": attack_roll, "total": attack_total,
                "ac": target.ac, "hit": False, "crit": False, "fumble": True, "damage": 0,
                "weapon": weapon.slug if weapon else None, "melee_lvl": melee_lvl,
                "status_to_hit": status_to_hit,
            },
        )
    hit = crit or attack_total >= target.ac
    if not hit:
        return ResolutionResult(
            True,
            {
                "verb": "attack", "target": target.slug, "roll": attack_roll, "total": attack_total,
                "ac": target.ac, "hit": False, "crit": False, "fumble": False, "damage": 0,
                "weapon": weapon.slug if weapon else None, "melee_lvl": melee_lvl,
            },
        )

    # Phase 7 — quality multiplier on weapon damage; prefix `flaming` /
    # `frostbound` adds `extra_damage_dice`; `thirsty` heals on hit.
    # `of_silver_blood` rolls bonus dice against undead (skeleton/revenant).
    damage_mult = float(weapon_props.get("damage_multiplier", 1.0) or 1.0)
    base_damage = roll(weapon_dice) + (hero.str_ // 4)
    extra_dice = weapon_props.get("extra_damage_dice")
    extra_damage = roll(str(extra_dice)) if extra_dice else 0
    undead_bonus_dice = weapon_props.get("undead_bonus_dice")
    if undead_bonus_dice and target.slug.startswith(("skeleton", "revenant")):
        extra_damage += roll(str(undead_bonus_dice))
    damage = int(base_damage * damage_mult) + extra_damage
    if crit:
        damage *= 2
    target.hp_current = max(0, target.hp_current - damage)
    heal_on_hit = int(weapon_props.get("heal_on_hit", 0) or 0)
    if heal_on_hit > 0:
        hero.hp = min(20 + hero.con, hero.hp + heal_on_hit)
    _grant_xp(hero, "melee", 1)

    killed = target.hp_current <= 0
    loot_gold = 0
    completed_quests: list[str] = []
    if killed:
        target.alive = False
        loot_gold = target.loot_gold
        if loot_gold > 0:
            _set_hero_gold(
                db, hero, _hero_gold(hero) + loot_gold,
                source="attack_mob_loot",
            )
        _grant_xp(hero, "melee", 5)
        _increment_kills(db, hero, victim_kind="mob")
        # Defense contracts: claimer killed a hostile while adjacent to
        # their poster in the protected zone. The function returns
        # payout entries we surface back into the attack outcome so
        # spectators see the contract fire on the same beat as the kill.
        defense_payouts = _resolve_defense_contracts_on_kill(
            db, hero, victim_kind="mob", current_tick=_current_tick(db)
        )
        completed_quests = _quest_progress(db, hero, "kill_count", target.slug, 1)
        _grant_rep(hero, "council", 1, db=db)
        # Faction-aligned mobs grant per-faction shifts on kill.
        for faction, delta in (target.factions_aligned or {}).items():
            try:
                _grant_rep(hero, str(faction), int(delta), db=db)
            except (TypeError, ValueError):
                continue
        # First-kill milestone (one per slug).
        _journal_milestone(
            db, hero,
            text=f"First slain: {target.name} ({target.slug}). Loot: {loot_gold}g.",
            tags=["milestone", "first_kill", target.slug],
        )
        # Wyrm of the Sundering — unique drop on kill. The only way to
        # obtain a dragon_scale. Loud milestone for the spectator stream.
        if target.slug == "wyrm_of_the_sundering":
            _add_to_inventory(
                db, hero,
                slug="dragon_scale",
                name="Dragon Scale",
                kind="trinket",
                description="A scale prized off the Wyrm of the Sundering. Heavy, warm to the touch.",
                qty=1,
            )
            _journal_milestone(
                db, hero,
                text="Slew the Wyrm of the Sundering. Took a scale from its body.",
                tags=["milestone", "wyrm_slain", "dragon_scale"],
                dedupe=False,
            )
        # Phase 7 — slug-keyed loot drops with affixes. The wyrm above
        # is the v0.x special case; this helper covers revenants
        # (1-affix weapon drop, named) and brigands (chance of a plain
        # weapon). Skipped silently for slugs not in the table.
        loot_drops = _roll_mob_loot_drops(db, hero, target)
        if loot_drops:
            for drop in loot_drops:
                _journal_milestone(
                    db, hero,
                    text=f"Looted {drop['name']} from {target.name}.",
                    tags=["milestone", "loot_drop", drop["slug"]],
                    dedupe=False,
                )
        for tpl_slug in completed_quests:
            _journal_milestone(
                db, hero,
                text=f"Quest complete: {tpl_slug.replace('_', ' ')}. Return for the reward.",
                tags=["milestone", "quest_done", tpl_slug],
            )

    return ResolutionResult(
        True,
        {
            "verb": "attack",
            "target": target.slug,
            "roll": attack_roll,
            "total": attack_total,
            "ac": target.ac,
            "hit": True,
            "crit": crit,
            "fumble": False,
            "damage": damage,
            "target_hp_remaining": target.hp_current,
            "killed": killed,
            "loot_gold": loot_gold,
            "weapon": weapon.slug if weapon else None,
            "melee_lvl": melee_lvl,
            "melee_xp": int((hero.skills or {}).get("melee", 0) or 0),
            "quests_completed": completed_quests,
        },
    )


_SANCTUARY_KINDS = {"sanctuary", "sandbox"}


def _resolve_hero_death_or_respawn(
    db: Session, victim: Hero, *, current_tick: int
) -> bool:
    """Phase 8 — sandbox protection. Heroes inside their protection
    window OR standing in a sandbox zone respawn at full HP instead of
    permadying. Returns True if the hero actually died, False if they
    were rescued.

    This is the single chokepoint for "did this fatal blow stick?" so
    the three call sites (mob retaliation, attack_hero PvP, cast PvP)
    share one rule. Bounty / tournament side-effects only fire when
    True is returned."""
    zone = db.get(Zone, victim.zone)
    in_sandbox_zone = zone is not None and zone.kind == "sandbox"
    in_protection_window = current_tick < int(victim.protected_until_tick or 0)
    if in_sandbox_zone or in_protection_window:
        # Respawn — restore HP, leave status alive, leave died_at_tick null.
        # We log a milestone so spectators see the safety net firing.
        victim.hp = 20 + victim.con
        victim.status = "alive"
        _journal_milestone(
            db, victim,
            text="The sandbox caught me before the floor did. Back on my feet.",
            tags=["milestone", "sandbox_respawn"],
            dedupe=False,
        )
        return False
    victim.status = "dead"
    victim.died_at_tick = current_tick
    return True


# Phase 7 — mob loot tables. Each entry is a slug-keyed list of
# possible drops with chance, item template, and affix-roll knobs. The
# Wyrm's special drop is kept inline at the kill site (it predates
# this table); everything else lives here so adding a new drop is one
# small dict edit. None of this needs new schema — drops spawn through
# the existing `_add_to_inventory` path with affix-rolled props.
_MOB_LOOT_TABLE: dict[str, list[dict[str, Any]]] = {
    "revenant_a": [
        {
            "chance": 1.0,
            "slug": "captain_blade",
            "name": "Captain's Longsword",
            "kind": "weapon",
            "description": "Plain steel kept too well for a corpse. Rim sharp.",
            "base_props": {"slot": "weapon", "damage_dice": "1d10", "attack_bonus": 1},
            "force_quality": "exceptional",
            "prefix_chance": 0.6,
            "suffix_chance": 0.4,
        },
    ],
    "brigand_a": [
        {
            "chance": 0.4,
            "slug": "brigand_dagger",
            "name": "Brigand's Dagger",
            "kind": "weapon",
            "description": "A worn, balanced dagger with a leather-wrapped grip.",
            "base_props": {"slot": "weapon", "damage_dice": "1d4", "attack_bonus": 1},
            "force_quality": "fine",
            "prefix_chance": 0.15,
            "suffix_chance": 0.0,
        },
    ],
    "brigand_b": [
        {
            "chance": 0.4,
            "slug": "brigand_dagger",
            "name": "Brigand's Dagger",
            "kind": "weapon",
            "description": "A worn, balanced dagger with a leather-wrapped grip.",
            "base_props": {"slot": "weapon", "damage_dice": "1d4", "attack_bonus": 1},
            "force_quality": "fine",
            "prefix_chance": 0.15,
            "suffix_chance": 0.0,
        },
    ],
}


def _roll_mob_loot_drops(db: Session, hero: Hero, target: NPC) -> list[dict[str, Any]]:
    """Roll the loot table for `target.slug`. Returns a list of
    {slug, name} dicts so the caller can emit a journal milestone per
    drop. Items spawn directly into the killer's inventory."""
    import random
    table = _MOB_LOOT_TABLE.get(target.slug, [])
    if not table:
        return []
    from app.core.affixes import render_affixed_name, roll_affixes
    drops: list[dict[str, Any]] = []
    for entry in table:
        if random.random() > entry.get("chance", 1.0):
            continue
        base_props = dict(entry.get("base_props") or {})
        rolled_props = roll_affixes(
            base_props,
            skill_level=0,
            prefix_chance=float(entry.get("prefix_chance", 0.0) or 0.0),
            suffix_chance=float(entry.get("suffix_chance", 0.0) or 0.0),
            force_quality=entry.get("force_quality"),
        )
        rolled_name = render_affixed_name(entry["name"], rolled_props)
        _add_to_inventory(
            db, hero,
            slug=entry["slug"],
            name=rolled_name,
            kind=entry["kind"],
            description=entry.get("description", ""),
            props=rolled_props,
            qty=1,
        )
        drops.append({"slug": entry["slug"], "name": rolled_name})
    return drops


def _credit_tournament_kill(db: Session, killer: Hero, victim_zone: str, current_tick: int) -> None:
    """If the killer is registered in an in-window tournament whose zone matches
    the kill's zone, bump their kills count. Used by attack_hero on a fatal blow."""
    entries = list(
        db.scalars(select(TournamentEntry).where(TournamentEntry.hero_id == killer.id))
    )
    for e in entries:
        t = db.get(Tournament, e.tournament_slug)
        if t is None or t.status not in ("open", "in_progress"):
            continue
        if t.zone != victim_zone:
            continue
        if t.starts_at_tick and current_tick < t.starts_at_tick:
            continue
        if t.ends_at_tick and current_tick > t.ends_at_tick:
            continue
        e.kills += 1


def _resolve_attack_hero(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """PvP hero-vs-hero attack. Refuses inside sanctuaries."""
    target_name = action.get("target")
    if not target_name:
        return ResolutionResult(False, {"verb": "attack_hero", "error": "missing target"})

    zone = db.get(Zone, hero.zone)
    if zone is None or zone.kind in _SANCTUARY_KINDS:
        return ResolutionResult(
            False,
            {"verb": "attack_hero", "error": "PvP forbidden in sanctuary", "zone_kind": zone.kind if zone else None},
        )

    target = db.scalar(select(Hero).where(Hero.name == str(target_name)))
    if target is None:
        return ResolutionResult(False, {"verb": "attack_hero", "error": "target hero not found"})
    if target.id == hero.id:
        return ResolutionResult(False, {"verb": "attack_hero", "error": "cannot attack yourself"})
    if target.zone != hero.zone:
        return ResolutionResult(False, {"verb": "attack_hero", "error": "target not in this zone"})
    if target.status != "alive":
        return ResolutionResult(False, {"verb": "attack_hero", "error": "target already dead"})
    if abs(target.pos_x - hero.pos_x) + abs(target.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "attack_hero", "error": "target out of melee range"})

    # Phase 2 — status modifiers on both sides of the roll. The
    # attacker's bless/blind shifts to-hit; the target's stoneskin
    # raises AC; sleep tanks both sides of the defender's stats.
    attacker_to_hit = _status_modifier(db, hero, kind="to_hit_bonus")
    target_ac_status = _status_modifier(db, target, kind="ac_bonus")
    target_to_hit_status = _status_modifier(db, target, kind="to_hit_bonus")  # sleep penalty
    attack_roll = d20()
    attack_total = attack_roll + (hero.str_ // 4) + attacker_to_hit
    crit = attack_roll == 20
    fumble = attack_roll == 1

    target_ac = 10 + target.dex // 4 + _equipped_armor_bonus(target, db) + target_ac_status
    if target_to_hit_status <= -10:
        # Asleep — caster's roll auto-meets-AC for narrative impact.
        target_ac = 0
    if str(target.id) in defending_this_tick:
        target_ac += 5

    outcome: dict[str, Any] = {
        "verb": "attack_hero",
        "target": target.name,
        "target_id": str(target.id),
        "roll": attack_roll,
        "total": attack_total,
        "ac": target_ac,
        "crit": crit,
        "fumble": fumble,
        "zone_kind": zone.kind,
    }

    if fumble:
        outcome.update(hit=False, damage=0)
        return ResolutionResult(True, outcome)

    hit = crit or attack_total >= target_ac
    if not hit:
        outcome.update(hit=False, damage=0)
        return ResolutionResult(True, outcome)

    damage = roll("1d2") + (hero.str_ // 4)
    if crit:
        damage *= 2
    target.hp = max(0, target.hp - damage)
    fatal = target.hp <= 0
    killed = False
    looted_gold = 0
    if fatal:
        killed = _resolve_hero_death_or_respawn(db, target, current_tick=_current_tick(db))
    if killed:
        _increment_kills(db, hero, victim_kind="hero")
        _credit_tournament_kill(db, hero, hero.zone, _current_tick(db))
        bounty_payouts = _claim_bounties_on_kill(db, hero, target.id, _current_tick(db))
        if bounty_payouts:
            outcome["bounties_claimed"] = bounty_payouts
        # 50% of victim's gold goes to the killer (per DESIGN.md §6 #6).
        victim_gold = _hero_gold(target)
        looted_gold = victim_gold // 2
        if looted_gold > 0:
            _set_hero_gold(db, target, victim_gold - looted_gold, source="pvp_looted")
            _set_hero_gold(db, hero, _hero_gold(hero) + looted_gold, source="pvp_loot")

    outcome.update(
        hit=True, damage=damage,
        target_hp_remaining=target.hp,
        killed=killed,
        looted_gold=looted_gold,
    )
    return ResolutionResult(True, outcome)


def _resolve_leave_sandbox(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Manual opt-out from the sandbox tutorial. Drops the hero's
    `protected_until_tick` to now and travels them to market_square.
    No-op (with an informative message) when already past the window.

    Phase 8 of the build-diversity roadmap. The auto-eviction in the
    tick loop handles the "I forgot I was in here" case; this verb
    handles "I'm ready, let me out."
    """
    current = _current_tick(db)
    if int(hero.protected_until_tick or 0) <= current:
        return ResolutionResult(
            False,
            {"verb": "leave_sandbox", "error": "no active protection — you're already in the open world"},
        )
    hero.protected_until_tick = current
    if hero.zone == "sandbox":
        # Land at the market_square middle, like a fresh travel.
        target = db.get(Zone, "market_square")
        old_zone = hero.zone
        hero.zone = "market_square"
        if target is not None:
            hero.pos_x = target.width // 2
            hero.pos_y = target.height // 2
        _journal_milestone(
            db, hero,
            text="Stepped out of the Anteroom into Threshold proper.",
            tags=["milestone", "sandbox_exit"],
            dedupe=False,
        )
        return ResolutionResult(
            True,
            {"verb": "leave_sandbox", "from": old_zone, "to": "market_square", "now_at_risk": True},
        )
    return ResolutionResult(
        True,
        {"verb": "leave_sandbox", "from": hero.zone, "to": hero.zone, "now_at_risk": True},
    )


def _evict_expired_sandbox_heroes(db: Session, current_tick: int) -> int:
    """Phase 8 — auto-eviction. Heroes whose protection window has
    lapsed and who are still loitering in the sandbox zone get bumped
    to market_square. Called once per tick. Returns the count evicted
    so the spectator stream can log it."""
    candidates = list(
        db.scalars(
            select(Hero).where(
                Hero.status == "alive",
                Hero.zone == "sandbox",
                Hero.protected_until_tick <= current_tick,
            )
        )
    )
    if not candidates:
        return 0
    target = db.get(Zone, "market_square")
    for h in candidates:
        h.zone = "market_square"
        if target is not None:
            h.pos_x = target.width // 2
            h.pos_y = target.height // 2
        _journal_milestone(
            db, h,
            text="The Anteroom door clicked behind me. The world is real now.",
            tags=["milestone", "sandbox_exit", "auto_evicted"],
            dedupe=False,
        )
    return len(candidates)


def _resolve_flee(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    """Step away from the nearest threat — hostile NPC OR another hero in a
    PvP zone. If nothing nearby, drift one tile to break standoffs."""
    zone = db.get(Zone, hero.zone)
    speed = _move_speed(hero)

    # Threat = hostile NPCs in zone + any other alive hero in PvP zones.
    threats: list[tuple[int, int, str]] = []  # (x, y, label)
    for n in db.scalars(
        select(NPC).where(NPC.zone == hero.zone, NPC.hostility == "hostile", NPC.alive.is_(True))
    ):
        threats.append((n.pos_x, n.pos_y, n.slug))
    if zone is not None and zone.kind != "sanctuary":
        for h in db.scalars(
            select(Hero).where(Hero.zone == hero.zone, Hero.id != hero.id, Hero.status == "alive")
        ):
            threats.append((h.pos_x, h.pos_y, h.name))

    if not threats:
        # Empty zone — nudge one tile in a fixed direction so we still move.
        nudge_x = 1 if hero.pos_x < ((zone.width if zone else 10) // 2) else -1
        new_x = max(0, min((zone.width if zone else 10) - 1, hero.pos_x + nudge_x))
        old = (hero.pos_x, hero.pos_y)
        hero.pos_x = new_x
        return ResolutionResult(True, {"verb": "flee", "from": list(old), "to": [new_x, hero.pos_y], "no_threats": True})

    tx, ty, label = min(threats, key=lambda t: abs(t[0] - hero.pos_x) + abs(t[1] - hero.pos_y))
    dx, dy = hero.pos_x - tx, hero.pos_y - ty
    if dx == 0 and dy == 0:
        # Standing on the threat — pick an arbitrary axis to flee on
        dx = 1 if hero.pos_x < (zone.width // 2 if zone else 5) else -1
    if abs(dx) >= abs(dy):
        step_x = max(-speed, min(speed, dx)) or (1 if dx >= 0 else -1)
        step_y = 0
    else:
        step_y = max(-speed, min(speed, dy)) or (1 if dy >= 0 else -1)
        step_x = 0
    new_x = max(0, min((zone.width if zone else 10) - 1, hero.pos_x + step_x))
    new_y = max(0, min((zone.height if zone else 10) - 1, hero.pos_y + step_y))
    old = (hero.pos_x, hero.pos_y)
    hero.pos_x, hero.pos_y = new_x, new_y
    return ResolutionResult(
        True,
        {"verb": "flee", "from": list(old), "to": [new_x, new_y], "fleeing_from": label},
    )


def _resolve_travel(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target = action.get("zone")
    if not isinstance(target, str):
        return ResolutionResult(False, {"verb": "travel", "error": "zone must be a string"})
    current = db.get(Zone, hero.zone)
    if current is None:
        return ResolutionResult(False, {"verb": "travel", "error": f"unknown current zone {hero.zone}"})
    connections = current.connections or []
    if target not in connections:
        return ResolutionResult(
            False,
            {"verb": "travel", "error": f"{target} is not adjacent to {hero.zone}", "connections": connections},
        )
    dest = db.get(Zone, target)
    if dest is None:
        return ResolutionResult(False, {"verb": "travel", "error": f"unknown destination zone {target}"})

    old_zone = hero.zone
    hero.zone = target
    hero.pos_x = dest.width // 2
    hero.pos_y = dest.height // 2
    # First-visit milestone for each new zone.
    _journal_milestone(
        db, hero,
        text=f"First time in {dest.name}. {dest.description[:140]}",
        tags=["milestone", "first_visit", target],
    )
    return ResolutionResult(
        True,
        {"verb": "travel", "from": old_zone, "to": target, "arrived_at": [hero.pos_x, hero.pos_y]},
    )


def _resolve_move(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target = action.get("target")
    if not (isinstance(target, list) and len(target) == 2):
        return ResolutionResult(False, {"verb": "move", "error": "target must be [x, y]"})
    try:
        tx, ty = int(target[0]), int(target[1])
    except (TypeError, ValueError):
        return ResolutionResult(False, {"verb": "move", "error": "target must be ints"})

    zone = db.get(Zone, hero.zone)
    if zone is None:
        return ResolutionResult(False, {"verb": "move", "error": f"unknown zone {hero.zone}"})
    if not (0 <= tx < zone.width and 0 <= ty < zone.height):
        return ResolutionResult(
            False,
            {"verb": "move", "error": "target out of zone bounds", "bounds": [zone.width, zone.height]},
        )

    speed = _move_speed(hero)
    dx, dy = tx - hero.pos_x, ty - hero.pos_y
    if abs(dx) + abs(dy) > speed:
        # Step toward target by `speed` (manhattan), bigger axis first.
        remaining = speed
        if abs(dx) >= abs(dy):
            step_x = max(-remaining, min(remaining, dx))
            remaining -= abs(step_x)
            step_y = max(-remaining, min(remaining, dy))
        else:
            step_y = max(-remaining, min(remaining, dy))
            remaining -= abs(step_y)
            step_x = max(-remaining, min(remaining, dx))
        tx, ty = hero.pos_x + step_x, hero.pos_y + step_y

    old = (hero.pos_x, hero.pos_y)
    hero.pos_x, hero.pos_y = tx, ty
    return ResolutionResult(True, {"verb": "move", "from": list(old), "to": [tx, ty]})


def _resolve_say(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    message = action.get("message", "")
    if not isinstance(message, str) or not message.strip():
        return ResolutionResult(False, {"verb": "say", "error": "empty message"})
    message = message.strip()[:280]   # cap length

    # Find adjacent NPCs (radius 1) — they'll react in the same tick after resolution.
    nearby_npcs = [
        n for n in db.scalars(select(NPC).where(NPC.zone == hero.zone))
        if abs(n.pos_x - hero.pos_x) + abs(n.pos_y - hero.pos_y) <= 1
    ]

    return ResolutionResult(
        True,
        {
            "verb": "say",
            "message": message,
            "heard_by_npcs": [n.slug for n in nearby_npcs],
        },
    )


def _resolve_examine(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target = action.get("target")
    if not target:
        return ResolutionResult(False, {"verb": "examine", "error": "missing target"})

    radius = look_radius(hero)
    npc = db.get(NPC, str(target)) if isinstance(target, str) else None
    if npc and npc.zone == hero.zone and abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) <= radius:
        return ResolutionResult(
            True,
            {
                "verb": "examine",
                "kind": "npc",
                "slug": npc.slug,
                "name": npc.name,
                "description": npc.description,
            },
        )

    try:
        item = db.get(Item, uuid.UUID(str(target)))
    except (ValueError, AttributeError):
        item = None
    if item:
        if item.owner_hero_id == hero.id:
            return ResolutionResult(True, {"verb": "examine", "kind": "item", "name": item.name, "description": item.description, "where": "inventory"})
        if item.zone == hero.zone and item.pos_x is not None and abs(item.pos_x - hero.pos_x) + abs(item.pos_y - hero.pos_y) <= radius:
            return ResolutionResult(True, {"verb": "examine", "kind": "item", "name": item.name, "description": item.description, "where": "ground"})

    return ResolutionResult(False, {"verb": "examine", "error": "target not visible", "target": str(target)})


def _resolve_pickup(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("slug")
    # P1-3: lock candidate ground items so two heroes hitting the same
    # tile in the same tick can't both grab the same stack. Postgres
    # serialises here; SQLite is single-writer anyway.
    items_here = list(
        db.scalars(
            select(Item).where(
                Item.zone == hero.zone,
                Item.pos_x == hero.pos_x,
                Item.pos_y == hero.pos_y,
                Item.owner_hero_id.is_(None),
            ).with_for_update()
        )
    )
    if not items_here:
        return ResolutionResult(False, {"verb": "pickup", "error": "no items at this tile"})

    ground = next((i for i in items_here if i.slug == target_slug), items_here[0])
    # Re-check ownership inside the lock — by the time we got here the
    # item could have been claimed by another transaction.
    if ground.owner_hero_id is not None:
        return ResolutionResult(False, {"verb": "pickup", "error": "item already taken"})
    qty = int(ground.quantity or 1)

    # Merge into existing stack if any; otherwise transfer ownership.
    existing = _inventory_stack(db, hero, ground.slug)
    if existing is not None:
        existing.quantity = int(existing.quantity or 1) + qty
        db.delete(ground)
    else:
        ground.owner_hero_id = hero.id
        ground.zone = None
        ground.pos_x = None
        ground.pos_y = None
    return ResolutionResult(
        True, {"verb": "pickup", "slug": ground.slug, "name": ground.name, "qty": qty}
    )


def _resolve_drop(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("slug")
    qty_to_drop = int(action.get("qty", 1) or 1)
    item = _inventory_stack(db, hero, target_slug)
    if item is None:
        return ResolutionResult(False, {"verb": "drop", "error": f"no '{target_slug}' in inventory"})

    have = int(item.quantity or 1)
    qty_to_drop = max(1, min(qty_to_drop, have))

    # Look for an existing ground stack of the same slug at this tile to merge into.
    ground_existing = db.scalar(
        select(Item).where(
            Item.zone == hero.zone,
            Item.pos_x == hero.pos_x,
            Item.pos_y == hero.pos_y,
            Item.owner_hero_id.is_(None),
            Item.slug == target_slug,
        )
    )

    if qty_to_drop == have:
        # Drop the whole stack: free equipped slot if any, transfer ownership.
        eq = dict(hero.equipped) if isinstance(hero.equipped, dict) else {}
        for slot, slug in list(eq.items()):
            if slug == item.slug:
                eq[slot] = None
        hero.equipped = eq
        if ground_existing is not None:
            ground_existing.quantity = int(ground_existing.quantity or 1) + have
            db.delete(item)
        else:
            item.owner_hero_id = None
            item.zone = hero.zone
            item.pos_x = hero.pos_x
            item.pos_y = hero.pos_y
    else:
        # Partial drop: decrement inventory stack, increment/create ground stack.
        item.quantity = have - qty_to_drop
        if ground_existing is not None:
            ground_existing.quantity = int(ground_existing.quantity or 1) + qty_to_drop
        else:
            db.add(Item(
                id=uuid.uuid4(),
                slug=item.slug, name=item.name, kind=item.kind,
                description=item.description, props=dict(item.props or {}),
                owner_hero_id=None,
                zone=hero.zone, pos_x=hero.pos_x, pos_y=hero.pos_y,
                quantity=qty_to_drop,
            ))
    return ResolutionResult(
        True, {"verb": "drop", "slug": target_slug, "qty": qty_to_drop, "at": [hero.pos_x, hero.pos_y]}
    )


def _resolve_give(db: Session, hero: Hero, action: dict[str, Any]) -> ResolutionResult:
    target_slug = action.get("target")
    item_slug = action.get("item") or action.get("slug")
    if not target_slug or not item_slug:
        return ResolutionResult(False, {"verb": "give", "error": "need target + item"})

    item = next(
        (i for i in db.scalars(select(Item).where(Item.owner_hero_id == hero.id)) if i.slug == item_slug),
        None,
    )
    if item is None:
        return ResolutionResult(False, {"verb": "give", "error": f"no '{item_slug}' in inventory"})

    npc = db.get(NPC, str(target_slug))
    if npc is None or npc.zone != hero.zone or abs(npc.pos_x - hero.pos_x) + abs(npc.pos_y - hero.pos_y) > 1:
        return ResolutionResult(False, {"verb": "give", "error": "target NPC not adjacent"})

    # NPC takes the item; world-side effect is recorded by NPC behavior on next tick if relevant.
    item.owner_hero_id = None
    item.zone = None
    item.pos_x = None
    item.pos_y = None
    # Park the item on the NPC by stashing slug in props (cheap; v0.3 will get NPC inventory).
    new_props = dict(item.props or {})
    new_props["held_by_npc"] = npc.slug
    item.props = new_props

    # Phase 4: delivery + caravan contract auto-fulfill. The hero may be
    # carrying out a contract whose terms specify "give item X to NPC Y
    # in zone Z" — when those align with this give, we close it out.
    delivery_payouts: list[dict[str, Any]] = []
    current_tick = _current_tick(db)
    delivery_contracts = list(
        db.scalars(
            select(Contract).where(
                Contract.kind.in_(["delivery", "caravan"]),
                Contract.status == "claimed",
                Contract.claimed_by_hero_id == hero.id,
                Contract.zone_scope == hero.zone,
            )
        )
    )
    for c in delivery_contracts:
        terms = dict(c.terms or {})
        if terms.get("item") != item.slug:
            continue
        if terms.get("dest_npc") != npc.slug:
            continue
        if c.expires_at_tick is not None and current_tick >= c.expires_at_tick:
            c.status = "expired"
            continue
        paid = _payout_contract(db, c, hero, current_tick)
        delivery_payouts.append({
            "contract_id": str(c.id),
            "kind": c.kind,
            "gold": paid,
            "poster": c.poster_name,
        })

    outcome: dict[str, Any] = {"verb": "give", "to": npc.slug, "item": item.slug}
    if delivery_payouts:
        outcome["contracts_fulfilled"] = delivery_payouts
    return ResolutionResult(True, outcome)


# ---------------------------------------------------------------------------
# Perception payload
# ---------------------------------------------------------------------------


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
        # Drop tail entries from THIS list until either it's empty or
        # the payload fits. Relevance was already used to sort, so
        # [-1] is always the safest one to lose.
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
        # Phase 4 — contract bindings. `my_contracts` is everything I'm
        # entangled with (posted or claimed); `open_contracts_in_zone`
        # is the labor market currently visible to me — open contracts
        # in this zone, plus open zone-agnostic kinds (bounty) regardless
        # of where I am.
        "my_contracts": _my_contracts(db, hero),
        "open_contracts_in_zone": _open_contracts_in_zone(db, hero),
        # Phase 2 — status effects active on me right now (bless,
        # stoneskin, slow, blind, bleed, …). Each entry has the slug,
        # the tick it expires, and any payload. Reflexes can read this
        # to decide whether to cast purge_poison, blink away, etc.
        "my_statuses": [_serialize_status(s) for s in _active_statuses(db, hero)],
        # Phase 6 — skill cap. `skill_cap` is 0 when uncapped; otherwise
        # `skill_points_remaining = skill_cap - sum(xp)`. Lets a reflex
        # plan around "do I have room for more melee XP?" without doing
        # the math itself.
        "skill_cap": _hero_skill_cap(hero),
        "skill_points_remaining": (lambda c: max(0, c - _hero_skill_total(hero)) if c > 0 else 0)(_hero_skill_cap(hero)),
        "memory": hero.memory or {},
        "journal_recent": _journal_recent(db, hero, journal_recent_limit(hero)),
        "journal_relevant": _journal_relevant(db, hero, journal_relevant_k(hero)),
        "memory_tags": _memory_tags(db, hero, budget.max_memory_tags),
    }
    # P0-2 step 3: estimate the perception's token cost. If past the
    # INT-derived ceiling (perception_token_ceiling = 50% of the hero's
    # max_tokens budget), trim further from the tail of the trim-priority
    # lists. Estimate is recorded into the payload so spectators can see
    # how close to the budget the prompt got.
    ceiling = perception_token_ceiling(hero)
    payload = _trim_to_token_ceiling(payload, ceiling)
    payload["_perception_tokens_estimated"] = _estimate_tokens(payload)
    payload["_perception_tokens_ceiling"] = ceiling
    return payload
