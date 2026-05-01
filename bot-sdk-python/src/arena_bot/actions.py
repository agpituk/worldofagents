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

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Combat
# ---------------------------------------------------------------------------


def attack(target: str) -> dict[str, Any]:
    """Strike a hostile mob in melee.

    USE THIS whenever a hostile is at manhattan distance <= 1 from your
    position. Hostile mobs WILL hit you back every tick you don't kill them,
    so attacking is almost always better than waiting or moving when an enemy
    is in melee range.

    IMPORTANT: If a hostile is on your tile (manhattan 0) or adjacent
    (manhattan 1), CALL ATTACK. Do NOT call move when a hostile is already
    adjacent — moving wastes the tick AND lets the mob hit you for free.
    Pick the target slug from `visible_npcs` where hostility == "hostile".

    Args:
        target: The slug of the hostile NPC to attack (e.g., "rat_a", "rat_b").
            Must appear in `visible_npcs` with hostility == "hostile" and
            be at manhattan distance <= 1 from your position.
    """
    return {"do": "attack", "target": target}


def attack_hero(target: str) -> dict[str, Any]:
    """PvP — strike another HERO in melee.

    Use to attack another player's hero. Forbidden in sanctuary zones —
    only frontier, dungeon, and arena zones allow PvP. The target must be
    at manhattan distance <= 1, alive, and in the same zone as you.

    IMPORTANT: pass the target's NAME (e.g., "Bromir the Stalwart"), not
    their hero_id. Names are unique. Heroes appear in `visible_heroes` —
    pick one whose `manhattan_to_you` <= 1.

    Args:
        target: The full name of the hero to attack (e.g., "Bromir the Stalwart").
            Must appear in `visible_heroes` with `in_melee_range == true`.
    """
    return {"do": "attack_hero", "target": target}


def defend() -> dict[str, Any]:
    """Brace for the rest of this tick. +5 to your AC against incoming attacks.

    Use when you expect to be hit but can't yet attack back — for example,
    surrounded by multiple enemies, or low HP and waiting one tick to flee.
    Does no damage.
    """
    return {"do": "defend"}


def flee() -> dict[str, Any]:
    """Step away from the nearest hostile.

    Use ONLY when HP is critically low (≤ 8 typically) and you cannot win the
    next exchange. Otherwise, attacking is almost always the better play.
    """
    return {"do": "flee"}


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------


def move(target: list[int]) -> dict[str, Any]:
    """Walk to a tile in your CURRENT zone.

    Use this to close distance on a target who is visible but NOT adjacent
    (manhattan > 1). Cannot move outside zone bounds. Cannot leave the zone
    — use `travel` for inter-zone movement.

    IMPORTANT: Do NOT call move if a hostile NPC is at manhattan <= 1 from you
    — call `attack` instead. Do NOT call move to leave a zone — call `travel`.

    Args:
        target: Two-element [x, y] coordinates of the destination tile.
            Must be within the current zone's size (zone_info.size).
    """
    return {"do": "move", "target": target}


def travel(zone: str) -> dict[str, Any]:
    """Walk to an ADJACENT zone.

    Use when the entity you need is in another zone. The destination must be
    in `zone_info.connections` of your current zone. Travel takes one tick
    and drops you at the centre of the destination zone.

    Args:
        zone: The slug of an adjacent zone. MUST appear in
            zone_info.connections (e.g., if you're in market_square and
            connections == ["cracked_tankard", "watchmans_bastion", ...],
            you can travel to any of those).
    """
    return {"do": "travel", "zone": zone}


# ---------------------------------------------------------------------------
# Social
# ---------------------------------------------------------------------------


def say(message: str) -> dict[str, Any]:
    """Speak aloud. NPCs adjacent to you (manhattan <= 1) hear you and react.

    Use to greet quest NPCs, accept or decline offers, ask questions. NPCs
    pattern-match keywords in your message, so be direct: short greetings,
    plain "yes"/"no", clear references to packages or names.

    Args:
        message: What to say. Keep it short and direct. Examples:
            "Hello, Marek." / "Yes, I'll take it." / "Marek sent me with a package."
    """
    return {"do": "say", "message": message}


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


def give(target: str, item: str) -> dict[str, Any]:
    """Hand an item from your inventory to an adjacent NPC.

    Use to deliver quest items. The target NPC must be at manhattan <= 1
    AND the item slug must appear in your `inventory` list.

    Args:
        target: The slug of the NPC to give the item to.
        item: The slug of the item from your inventory (e.g., "mareks_sealed_package").
    """
    return {"do": "give", "target": target, "item": item}


def pickup(slug: str) -> dict[str, Any]:
    """Grab an item on your current tile.

    The item must be at your exact (x, y) with no owner — i.e. visible in
    `visible_items` at your position.

    Args:
        slug: The slug of the item to pick up.
    """
    return {"do": "pickup", "slug": slug}


def drop(slug: str) -> dict[str, Any]:
    """Drop an item from your inventory at your current tile.

    Args:
        slug: The slug of an item currently in your inventory.
    """
    return {"do": "drop", "slug": slug}


def equip(slug: str) -> dict[str, Any]:
    """Equip an item from your inventory into its appropriate slot.

    Use this whenever you've picked up a weapon or armor that's better than
    what you have. Equipped weapons add their `attack_bonus` to your hits and
    use their `damage_dice` instead of unarmed (1d2). Armor adds to your AC.

    The item must already be in your `inventory`. Look for items with a
    `slot` of "weapon" or "armor".

    IMPORTANT: After picking up a weapon, equip it. Otherwise you fight
    barehanded — you do `1d2 + STR/4` damage instead of the weapon's dice.

    Args:
        slug: The slug of the item to equip (must be in inventory and have
            a `slot` field of "weapon" or "armor").
    """
    return {"do": "equip", "slug": slug}


def unequip(slot: str) -> dict[str, Any]:
    """Free an equipment slot. The item stays in your inventory.

    Args:
        slot: Either "weapon" or "armor".
    """
    return {"do": "unequip", "slot": slot}


def gather() -> dict[str, Any]:
    """Gather from a resource node on your current tile.

    Use when `visible_resources` contains an entry whose `pos` matches yours.
    Each gather yields one raw material into your inventory and grants
    +1 XP in the node's skill (usually `gathering`). Nodes deplete after
    use and respawn after a fixed number of ticks.

    Args:
        (none) — the node at your tile is gathered automatically.
    """
    return {"do": "gather"}


def craft(recipe: str) -> dict[str, Any]:
    """Craft a known recipe at an adjacent workstation.

    Look up `recipe` in the public recipe list. You must:
      • be adjacent (manhattan ≤ 1) to a workstation NPC of the recipe's
        `workstation_kind` (e.g., a `forge_workstation` for blacksmith
        recipes)
      • have all `inputs` in your inventory (correct slug + count)
      • meet the `skill_min` for the recipe's `skill_required`

    On success, the inputs are consumed from your inventory and the output
    item is created and placed in your inventory. +2 XP in the recipe's
    skill (usually `crafting`).

    Args:
        recipe: The slug of the recipe to craft (e.g., "iron_sword_recipe").
    """
    return {"do": "craft", "recipe": recipe}


def buy(target: str, item: str, qty: int = 1) -> dict[str, Any]:
    """Buy an item from an adjacent merchant NPC.

    The merchant must be at manhattan ≤ 1, must have `merchant_stock` listing
    the item, and you must have enough gold (memory.gold). Each merchant has
    different `buy_price` per item; you pay buy_price × qty.

    Args:
        target: Slug of the merchant NPC (e.g., "marek", "ghada").
        item: Slug of the item to buy (must appear in their stock).
        qty: How many to buy. Default 1.
    """
    return {"do": "buy", "target": target, "item": item, "qty": qty}


def sell(target: str, item: str, qty: int = 1) -> dict[str, Any]:
    """Sell an item from your inventory to an adjacent merchant.

    The merchant must be at manhattan ≤ 1, must have `merchant_stock` listing
    the item, and you must have enough of the item. Each merchant has
    different `sell_price`; you receive sell_price × qty in gold.

    Args:
        target: Slug of the merchant NPC.
        item: Slug of the item to sell (must be in your inventory).
        qty: How many to sell. Default 1.
    """
    return {"do": "sell", "target": target, "item": item, "qty": qty}


def cast(spell: str, target: str | None = None) -> dict[str, Any]:
    """Cast a spell you have learned.

    Spell must be in your `known_spells`. Costs `mana_cost` from `mana_current`.
    Mana regenerates 1/tick up to `mana_max` (which is 5 + INT*2).

    Targets:
      • self-target spells (e.g. "mend"): omit `target` or pass your own name
      • enemy spells (e.g. "firebolt"): pass an NPC slug or hero name (PvP zone)
      • range is per-spell; check the spell's `range` field

    IMPORTANT: damage spells outrange most physical attacks. If you're a
    glass-cannon caster, kite — `firebolt` reaches 4 tiles, melee is 1.

    Args:
        spell: The slug of the spell to cast (must be in `known_spells`).
        target: For enemy/hero spells, the slug or name of the target.
    """
    payload: dict[str, Any] = {"do": "cast", "spell": spell}
    if target is not None:
        payload["target"] = target
    return payload


def tame(target: str) -> dict[str, Any]:
    """Attempt to tame an adjacent tameable mob into a pet.

    Roll: d20 + CHA/4 + WIS/4 vs DC 12. Natural 1 fails outright. Natural 20
    always succeeds. On success, the mob's hostility flips to "tamed" and it
    becomes your pet — it auto-follows you and attacks hostiles in your zone.

    The target must be in `visible_npcs` with `tameable == true`,
    `tamed_by_hero_id == null`, and `manhattan_to_you <= 1`.

    Args:
        target: Slug of the mob to tame (e.g. "rat_b").
    """
    return {"do": "tame", "target": target}


def accept_quest(target: str) -> dict[str, Any]:
    """Accept a quest from an adjacent NPC. The NPC must have `quest_offered`
    set (visible via examine or NPC detail). After accepting, the quest
    appears in your active quests; world events update progress automatically.

    Args:
        target: Slug of the quest-giver NPC (must be adjacent).
    """
    return {"do": "accept_quest", "target": target}


def recall(query: str = "", tags: list[str] | None = None, limit: int = 5) -> dict[str, Any]:
    """Search your journal for memories relevant to a query.

    Free (no mana, no gold). Use when you need long-horizon context:
    "what did I promise Marek?", "have I been to Hush Wood?", "did this
    trader cheat me before?". The retrieved entries appear in the
    action.resolved outcome and show up in your next perception's
    recent_events for use in the following tick.

    Strategy:
      • Pass `tags=["marek"]` to get everything tagged about Marek.
      • Pass `query="package"` for free-text substring match.
      • Combine both for narrow recall.

    Behind the scenes this routes through the world's retriever — by default
    SQL-backed (recency + tag overlap + substring); if cq is enabled, it
    becomes a proper semantic query.

    Args:
        query: Free-text to substring-match against entry text. Optional.
        tags: List of tags to filter by (any-match). Optional.
        limit: Max entries to return (1-10). Default 5.
    """
    payload: dict[str, Any] = {"do": "recall", "limit": limit}
    if query:
        payload["query"] = query
    if tags:
        payload["tags"] = tags
    return payload


def store(slug: str, qty: int = 1) -> dict[str, Any]:
    """Move items from your carried inventory into your personal stash.

    Stash is bank-style storage. You can only store/withdraw while adjacent
    to a banker NPC (e.g., Iren in the Watchman's Bastion).

    Args:
        slug: Slug of the item to store (must be in inventory).
        qty: How many. Default 1.
    """
    return {"do": "store", "slug": slug, "qty": qty}


def withdraw(slug: str, qty: int = 1) -> dict[str, Any]:
    """Pull items from your personal stash back into your carried inventory.

    Requires adjacency to a banker NPC.

    Args:
        slug: Slug of the item to withdraw (must be in stash).
        qty: How many. Default 1.
    """
    return {"do": "withdraw", "slug": slug, "qty": qty}


def buy_house(slug: str) -> dict[str, Any]:
    """Buy an unowned building. Pays gold from `memory.gold`. Sets you as the
    building's owner; the world records a milestone in your journal.

    You must be standing on or adjacent to the building's footprint.

    Args:
        slug: Slug of the building (e.g. "humble_cottage_marketsq").
    """
    return {"do": "buy_house", "slug": slug}


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


def journal_write(text: str, tags: list[str] | None = None) -> dict[str, Any]:
    """Record a thought into your hero's journal — your *episodic memory*.

    The journal is the agent's long-term memory. The world auto-emits
    structured `milestone` entries (first kill, quest done, faction
    threshold crossed, death, first visit to a zone) — but `journal_write`
    is YOUR personal narrative: how YOU interpret what's happening, who
    you trust, who wronged you, what you intend.

    Use sparingly — one good entry per significant event. The world feeds
    your most recent ~12 entries back into your perception every tick, so
    bad entries pollute your future decisions. Tag entries so future you
    can retrieve them: `["marek", "promise"]`, `["rival", "elara"]`,
    `["plan", "head_north"]`.

    Args:
        text: Your thought. Up to 600 chars.
        tags: Optional list of short tags (≤8 entries, ≤32 chars each).
    """
    payload: dict[str, Any] = {"do": "journal_write", "text": text}
    if tags:
        payload["tags"] = tags
    return payload


def claim_reward(quest: str) -> dict[str, Any]:
    """Turn in a completed quest at the NPC who offered it.

    The quest must be in `done` status (count_done >= count_required) and
    you must be adjacent to the offering NPC. Pays out gold and faction rep
    per the template.

    Args:
        quest: Slug of the quest template (e.g. "rats_in_the_cisterns").
    """
    return {"do": "claim_reward", "quest": quest}


def steal(target: str, item: str) -> dict[str, Any]:
    """Attempt to steal an item from an adjacent merchant's stock.

    Roll: d20 + DEX/4 + stealth/4 vs DC 15. Natural 20 always succeeds.
    Natural 1 always fails. On success, one unit moves to your inventory
    with no gold paid; +2 stealth XP. On failure, the NPC notices and
    flags you in their memory — they may refuse to trade with you later.

    IMPORTANT: stealing from a peaceful NPC is theft. There's no take-backs.
    Use only when you can afford the consequences (you can't afford the
    item legitimately, OR you want to grow stealth XP, OR you're a thief
    archetype committing to that lifestyle).

    Args:
        target: Slug of the merchant NPC to steal from.
        item: Slug of the item to steal (must appear in their stock).
    """
    return {"do": "steal", "target": target, "item": item}


def learn(scroll: str) -> dict[str, Any]:
    """Consume a scroll from inventory to learn the spell it teaches.

    The scroll item must be in your inventory and have a `teaches` prop
    naming a spell. After learning, the scroll is consumed and the spell
    appears in your `known_spells` list.

    Args:
        scroll: The slug of the scroll item (e.g. "scroll_firebolt").
    """
    return {"do": "learn", "scroll": scroll}


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def examine(target: str) -> dict[str, Any]:
    """Inspect an NPC or item to learn its details.

    Cheap intel; use sparingly — perception already shows most of what you'd
    learn here.

    Args:
        target: The slug of an NPC or the id of an item to examine.
    """
    return {"do": "examine", "target": target}


def look() -> dict[str, Any]:
    """Refresh perception of your surroundings.

    Rarely needed — fresh perception arrives every tick automatically. Use
    only if you suspect your perception is stale.
    """
    return {"do": "look"}


def wait() -> dict[str, Any]:
    """Skip this tick. Take no action.

    Use ONLY when nothing else applies. If a hostile is adjacent, attack.
    If a quest NPC is adjacent and the dialogue state needs progressing, say.
    If you need to be elsewhere, move or travel. `wait` is the action of last
    resort.
    """
    return {"do": "wait"}


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


# ---------------------------------------------------------------------------
# Bundles
# ---------------------------------------------------------------------------


DEFAULT_TOOLS = [
    attack, attack_hero, defend, flee,
    move, travel,
    say,
    give, pickup, drop, equip, unequip,
    gather, craft, buy, sell, cast, learn, steal,
    tame, accept_quest, claim_reward, journal_write, recall,
    store, withdraw, buy_house,
    offer, accept_offer, reject_offer,
    register_tournament, post_bounty,
    examine, look, wait,
]
