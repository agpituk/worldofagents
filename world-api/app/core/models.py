"""All ORM models registered against the same Base, so alembic --autogenerate sees them."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Zone(Base):
    """One playable zone. Coordinates are zero-based: x ∈ [0, width), y ∈ [0, height)."""

    __tablename__ = "zones"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # sanctuary | frontier | dungeon | arena
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    capacity_soft: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    # Adjacent zone slugs you can travel(...) to from here.
    connections: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class Hero(Base, TimestampMixin):
    """A registered hero. The full manifest is stored as JSON for now;
    once the design stabilises we'll project key fields into typed columns."""

    __tablename__ = "heroes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    author: Mapped[str] = mapped_column(String(120), nullable=False)
    division: Mapped[str] = mapped_column(String(32), nullable=False)
    bio: Mapped[str] = mapped_column(String, nullable=False, default="")

    # Point-buy stats
    str_: Mapped[int] = mapped_column("str", Integer, nullable=False, default=10)
    dex: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    con: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    int_: Mapped[int] = mapped_column("int", Integer, nullable=False, default=10)
    wis: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    cha: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    # Ephemeral runtime state
    hp: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="alive")
    zone: Mapped[str] = mapped_column(String(64), nullable=False, default="market_square")
    pos_x: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    pos_y: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    # Full manifest as supplied (immutable)
    manifest: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Mutable runtime memory — quest state, NPC relationships, accumulated knowledge.
    # Initialized from manifest.memory.initial at registration. All writes
    # should go through app.core.memory.update_memory() / replace_memory()
    # so they emit memory.mutated audit events and are guarded by the
    # schema-version forward-migration table.
    memory: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    memory_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    # Skills: per-skill XP totals. Level = min(100, xp // 10). Examples:
    #   {"melee": 12, "gathering": 4, "crafting": 0}
    skills: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Equipment slots: { "weapon": "<item_slug>" | None, "armor": ... }
    # The actual Item row remains in the hero's inventory (owner_hero_id == hero.id);
    # this dict just records which inventory slug fills each slot.
    equipped: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Magic. mana_max is computed as 5 + INT*2 at registration and stored;
    # mana_current regens 1/tick up to max. known_spells is a list of spell slugs.
    mana_max: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    mana_current: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    known_spells: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Faction reputation. Keys: wardens, council, embered. Values are integers
    # that go up via faction-aligned actions and down via faction-opposed ones.
    # Some content is gated by these (e.g. Embered Shrine training requires
    # embered >= 5). Default empty.
    faction_rep: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Per-hero token used by the bot SDK to authenticate the WebSocket connection.
    # Generated on registration. Distinct from the gateway's signed call-tokens.
    auth_token: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    # Lifespan — the headline metric of the game. born_at_tick is set on
    # register; died_at_tick is stamped the moment status flips to "dead"
    # (PvP kill, mob kill, anything). Permadeath: there is no resurrect verb,
    # so died_at_tick is monotonic. Days alive = (died_at_tick or current
    # tick) - born_at_tick, mapped through ticks-per-day.
    born_at_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    died_at_tick: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Phase 8 — sandbox protection. While `current_tick <
    # protected_until_tick`, the hero is in a tutorial-grade safety net:
    # any fatal blow respawns them at full HP instead of stamping
    # died_at_tick. Default 0 means no protection (the legacy behaviour
    # for every existing hero). New heroes get `born_at_tick + 50`
    # unless their manifest opts out via `extras.skip_sandbox: true`.
    protected_until_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Managed mode: when true, the world-api runs the bot loop on the hero's
    # behalf — reflexes, LLM calls, action submissions all happen server-side.
    # When false (legacy), the player runs the bot loop locally via the SDK.
    # The deploy form defaults this to true so paste-and-go works without
    # any local Python environment.
    managed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class NPC(Base):
    """A non-player character living in a zone. Behavior is scripted by slug."""

    __tablename__ = "npcs"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # innkeeper | guard | trainer | mob | etc.
    zone: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    pos_x: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pos_y: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")

    # Merchant stock. List of stockable items: [{slug, name, kind, props,
    # buy_price, sell_price, qty}]. qty=None = infinite supply.
    merchant_stock: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Tameable mobs become pets when a hero succeeds at a tame check.
    # tamed_by_hero_id points to the owner; hostility flips to "tamed".
    tameable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tamed_by_hero_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # If non-null, this NPC offers this quest slug to heroes who say(...) the
    # right keyword. Quests live in the Quest model, instantiated per-hero.
    quest_offered: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Optional LLM persona — when set, this NPC's `say` reactions go through
    # the gateway with this text as system prompt + the hero's message; the
    # parsed JSON response becomes the effects (speak / set_state / give_item).
    # Leave null to keep keyword-matching scripted dialogue.
    llm_persona: Mapped[str | None] = mapped_column(String, nullable=True)

    # NPC alignment with factions. Killing it shifts hero rep accordingly.
    # E.g. {"embered": -3, "council": +2} on a cultist means killing it
    # costs embered rep and gains council rep. Default empty.
    factions_aligned: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Combat fields. Peaceful NPCs aren't attackable; mobs are.
    hostility: Mapped[str] = mapped_column(String(16), nullable=False, default="peaceful")  # peaceful | hostile | tamed
    alive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    hp_max: Mapped[int] = mapped_column(Integer, nullable=False, default=999)
    hp_current: Mapped[int] = mapped_column(Integer, nullable=False, default=999)
    ac: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    attack_bonus: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    damage_dice: Mapped[str] = mapped_column(String(16), nullable=False, default="0d0")
    loot_gold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ResourceNode(Base):
    """A gatherable resource on a tile. Depletes when used; respawns after N ticks."""

    __tablename__ = "resource_nodes"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # ore_vein | herb_patch | log_pile
    zone: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    pos_x: Mapped[int] = mapped_column(Integer, nullable=False)
    pos_y: Mapped[int] = mapped_column(Integer, nullable=False)
    yield_item_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    yield_item_name: Mapped[str] = mapped_column(String(120), nullable=False)
    yield_item_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="material")
    skill_required: Mapped[str] = mapped_column(String(32), nullable=False, default="gathering")
    respawn_after_ticks: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    depleted_until_tick: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Recipe(Base):
    """A crafting recipe. Inputs are consumed from inventory; output is created."""

    __tablename__ = "recipes"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    output_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    output_name: Mapped[str] = mapped_column(String(120), nullable=False)
    output_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    output_description: Mapped[str] = mapped_column(String, nullable=False, default="")
    output_props: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    inputs: Mapped[list] = mapped_column(JSON, nullable=False)  # [{slug, count}, ...]
    skill_required: Mapped[str] = mapped_column(String(32), nullable=False, default="crafting")
    skill_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    workstation_kind: Mapped[str] = mapped_column(String(32), nullable=False)  # forge | alchemy_table | loom

    # Hidden recipes don't appear in the public /recipes catalogue. Heroes
    # find them by guessing — the model has to try the right input
    # combination at the right workstation. On a successful hidden craft,
    # the world emits a "discovery" milestone and adds the recipe to the
    # hero's `memory.discovered_recipes` set. This is the only "wait you
    # can do that?" surface in the world today; spectators love it.
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Building(Base):
    """A multi-tile structure heroes can buy. v0.10 ships ownership + stash
    access (heroes who own a house gain a personal stash usable at any
    banker NPC). Multi-tile rendering on the frontend comes later; for now
    a building is a (zone, top-left, w, h, owner) record."""

    __tablename__ = "buildings"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    zone: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    pos_x: Mapped[int] = mapped_column(Integer, nullable=False)
    pos_y: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="house")
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    owner_hero_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    gold_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class JournalEntry(Base):
    """The hero's episodic memory. Two sources:

      • `kind="player"`  — the agent wrote it via `journal_write` (their own
        interpretation of an event, free-form text)
      • `kind="milestone"` — the world auto-emitted a structured entry on a
        notable event (first kill of a slug, quest completed, faction rep
        threshold crossed, hero death, first visit to a zone, ...)

    Tags drive cheap retrieval: a slice of the hero's journal can be
    selected by tag intersection (e.g. all entries tagged "marek") and fed
    into the LLM context. Once cq is wired, this table becomes its corpus.
    """

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hero_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    tick_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # player | milestone
    text: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class QuestTemplate(Base):
    """Static catalogue of quests NPCs can offer."""

    __tablename__ = "quest_templates"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # kill_count | gather_count | deliver
    target: Mapped[str] = mapped_column(String(64), nullable=False)  # npc.slug for kill, item.slug for gather
    count_required: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reward_gold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reward_faction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reward_faction_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    offered_by: Mapped[str] = mapped_column(String(64), nullable=False)  # NPC.slug who hands it out


class Quest(Base):
    """An active or completed quest instance for one hero."""

    __tablename__ = "quests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hero_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    template_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active | done | claimed
    count_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Spell(Base):
    """A spell heroes can learn and cast."""

    __tablename__ = "spells"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    school: Mapped[str] = mapped_column(String(32), nullable=False)  # fire | frost | heal | shadow | ...
    target_kind: Mapped[str] = mapped_column(String(32), nullable=False)  # enemy | self | hero | any_target | none
    mana_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    range: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    damage_dice: Mapped[str] = mapped_column(String(16), nullable=False, default="0d0")
    heal_dice: Mapped[str] = mapped_column(String(16), nullable=False, default="0d0")
    skill_required: Mapped[str] = mapped_column(String(32), nullable=False, default="magic")
    skill_min: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Phase 2: effect kind drives which handler runs at cast time. The
    # default `damage_or_heal` keeps the v0.6 spells (firebolt /
    # frost_lance / mend) on their existing path — pick `apply_status`,
    # `dispel`, `move_self`, `move_target`, `summon_npc`, or `reveal` to
    # exercise the new handlers. `payload` is kind-specific JSON
    # (status slug + duration_ticks for apply_status, mob slug for
    # summon_npc, etc.).
    effect_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="damage_or_heal"
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class Status(Base):
    """An active status effect on a hero — the durable side-channel that
    spells use to modify combat without re-targeting on every tick. A
    Bless raises to-hit; a Stoneskin raises AC; a Slow drops action
    priority; a Bleed ticks damage. The world tick decrements
    `expires_at_tick` and removes rows that hit zero.

    `slug` is the effect's identity (e.g. `bless`, `stoneskin`, `slow`,
    `blind`, `bleed`, `regrowth`). `payload` carries kind-specific
    numeric tunables (bonus magnitude, damage dice, source caster id)
    so the same row format covers all status types.

    Multiple stacks of the same slug on the same hero are allowed — the
    apply path can choose to refresh the longest-running one or stack
    them. We keep that policy in the spell handler, not the schema.
    """

    __tablename__ = "statuses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hero_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    applied_at_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at_tick: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_hero_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class Item(Base):
    """An item somewhere in the world. Either held by a hero (owner_hero_id) or
    dropped on the ground in a zone (zone + pos_x + pos_y). Mutually exclusive."""

    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # delivery | weapon | herb | scroll | trinket
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    props: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    owner_hero_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    zone: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    pos_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pos_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Stack count. Equippable items (weapons/armor) are typically qty=1.
    # Materials (iron_ore, oak_log, herbs, gold-ish things) stack arbitrarily.
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # If set, the item lives in this hero's personal stash (bank-style storage)
    # instead of their carried inventory. Mutually exclusive with owner_hero_id
    # (and with zone/pos for ground items).
    stash_owner_hero_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # Crafter marks (Phase 5). Stamped at craft time on the new Item row.
    # `crafted_by_name` is the denormalised hero name at that moment so
    # item tooltips can show "Iron Sword crafted by Tova" without a join,
    # and so the mark survives even after the crafter is dead and gone.
    # NULL for seeded items, mob drops, and pre-Phase-5 inventory.
    crafted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    crafted_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)


class Tournament(Base):
    """A scheduled or running competition. Heroes register; PvP kills in
    `zone` during the window count toward the leaderboard. Top entry wins
    `prize_gold` + faction rep when the tournament closes.

    Status flow: scheduled → open → in_progress → complete.
    """

    __tablename__ = "tournaments"

    slug: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    division: Mapped[str] = mapped_column(String(32), nullable=False)  # featherweight | middleweight | heavyweight
    zone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # scheduled | open | in_progress | complete
    starts_at_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ends_at_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_entries: Mapped[int] = mapped_column(Integer, nullable=False, default=16)
    prize_gold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prize_faction: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prize_faction_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Contract(Base):
    """The labor market that binds non-combat specialists to fighters.
    Phase 4 of the build-diversity roadmap: a unified table for every
    "I'll pay you to do X" arrangement in the world. The bounty board is
    one filtered view (`kind='bounty'`); the rest are the kinds that let
    a fisher hire an escort, an alchemist post a delivery, a vendor
    fund their own zone defense.

    Status flow:
      • open      — posted, gold escrowed.
      • claimed   — a hero has taken the job (defense / delivery / escort
                    / caravan). Skipped for kinds that pay any-finder
                    (bounty / assassination) — those go open → fulfilled.
      • fulfilled — terms met, payout sent.
      • expired   — timed out or cancelled. Gold refunded to poster.

    `target_hero_id` is set for hero-targeting contracts (bounty,
    assassination); `target_ref` is the free-form string for kinds that
    point at NPCs / items / zones (delivery dest_npc, etc.). Both
    nullable — defense, escort have no single target.

    `terms` is a JSON blob whose shape is kind-specific (see
    `domains/contract/router.py` for the per-kind contract). Keeping it
    permissive here means new kinds can land without schema churn.
    """

    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    poster_hero_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    poster_name: Mapped[str] = mapped_column(String(120), nullable=False, default="anonymous")
    target_hero_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    target_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reward_gold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", index=True)
    zone_scope: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(String(280), nullable=False, default="")
    terms: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at_tick: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claimed_by_hero_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    claimed_at_tick: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fulfilled_at_tick: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TournamentEntry(Base):
    """A hero's entry into a tournament. `kills` is bumped each PvP kill
    they make in the tournament's zone during the window."""

    __tablename__ = "tournament_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tournament_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    hero_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    kills: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="registered")  # registered | winner | runner_up | eliminated
    registered_at_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TradeOffer(Base):
    """A pending hero-to-hero trade. A `offer`s items+gold to B in exchange for
    items+gold; B `accept`s or `reject`s. Resolved instantly on accept (no
    multi-tick escrow yet). Offers expire after `expires_at_tick`."""

    __tablename__ = "trade_offers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_hero_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    to_hero_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    # JSON: [{slug, qty}, ...]
    offered_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    offered_gold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wanted_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    wanted_gold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    expires_at_tick: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Tick(Base):
    """Append-only record of every world tick. The 'event log' lives across this and Event."""

    __tablename__ = "ticks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(String, nullable=True)


class Event(Base):
    """Anything that happened in the world. Source of truth for replays + spectator streams."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tick_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    hero_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    zone: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)  # action.submitted, action.resolved, ...
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
