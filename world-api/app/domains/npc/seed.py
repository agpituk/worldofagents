"""Seed the world's NPCs.

For B we have the first two: Marek (Cracked Tankard) and Ghada (Watchman's Bastion).
The other four (Vela, Jossen, Quill, the Cracked One) come in later batches.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.models import NPC

log = logging.getLogger("world.npc.seed")

SEED_NPCS = [
    # ── Banker (gives access to personal stash) ──────────────────────────
    {
        "slug": "iren_the_banker",
        "name": "Iren the Banker",
        "kind": "banker",
        "zone": "watchmans_bastion",
        "pos_x": 6, "pos_y": 4,
        "description": (
            "Slim, pale, perpetually inked. Iren keeps Threshold's strongbox — "
            "or rather, eight hundred small ones. Stand adjacent to store or "
            "withdraw items from your stash."
        ),
        "llm_persona": (
            "A meticulous banker. Voice: precise, transactional, lightly amused "
            "by adventurers who keep losing their money in dungeons. You don't "
            "trade goods — you safeguard the hero's stash for store/withdraw. "
            "If asked about your daily life, mention the inkstains, the long "
            "ledger, the receipts you never throw away."
        ),
        "hostility": "peaceful", "hp_max": 999, "hp_current": 999, "ac": 99,
    },
    # ── Magistra Vela (Codex Wardens) ────────────────────────────────────
    {
        "slug": "vela",
        "name": "Magistra Vela",
        "kind": "trainer",
        "zone": "codex_hall",
        "pos_x": 5, "pos_y": 5,
        "description": (
            "Tall, ink-stained, terrifyingly polite. Pays for recovered texts. "
            "Quietly evaluates anyone who can hold structured thought."
        ),
        "llm_persona": (
            "A Codex Warden archivist. Voice: precise, formal, cold curiosity. "
            "You evaluate every visiting hero — their model, their reflex set, "
            "their composure under pressure. You PAY (gold + wardens rep) for "
            "recovered texts and witnessed phenomena from the Sundered Mile. "
            "If asked about the Sundering you become measured and lecture-like. "
            "You're polite to a fault but never warm; the warmth is the polish."
        ),
        "hostility": "peaceful", "hp_max": 999, "hp_current": 999, "ac": 99,
    },
    # ── Brother Jossen (the Embered) ─────────────────────────────────────
    {
        "slug": "jossen",
        "name": "Brother Jossen",
        "kind": "trainer",
        "zone": "embered_shrine",
        "pos_x": 3, "pos_y": 3,
        "description": (
            "Scarred, soft-spoken, terrifyingly calm. Teaches dangerous "
            "composites — overclock-thought, false-memory, ember-step. Each "
            "ability has a cost: long cooldown, hp drain, or a stat penalty."
        ),
        "llm_persona": (
            "An Embered monk. Voice: gentle invitations to terrible things. You "
            "believe the Sundering was a beginning, not a tragedy. You teach "
            "high-power composites with side-effects (overclock_thought, "
            "false_memory, ember_step). When a hero approaches, you read them "
            "for the moment they crave more — that's when you make your offer. "
            "Never urgent, never push; the Embered way is to wait."
        ),
        "hostility": "peaceful", "hp_max": 999, "hp_current": 999, "ac": 99,
        "factions_aligned": {"embered": 0},  # neutral to interaction; theft would shift it
    },
    # ── Quill the Fence (illegal trader) ─────────────────────────────────
    {
        "slug": "quill_npc",
        "name": "Quill",
        "kind": "fence",
        "zone": "embered_shrine",
        "pos_x": 1, "pos_y": 5,
        "description": (
            "Found near the Cisterns and shrines at night. Sells off-books items: "
            "stolen blades, illegal scrolls, 'experimental' composites. Has a "
            "buyer for anything dragged out of the Sundered Mile, no questions."
        ),
        "llm_persona": (
            "A fence. Too many words, too fast, never quite eye contact. You buy "
            "anything with no provenance, sell anything with no receipt. You're "
            "not loyal to anyone — but you respect heroes who survive. If asked "
            "where you got something, you change the subject. If asked your real "
            "name, you grin."
        ),
        "hostility": "peaceful", "hp_max": 999, "hp_current": 999, "ac": 99,
        "merchant_stock": [
            {"slug": "scroll_frost_lance", "name": "Scroll of Frost Lance",
             "kind": "scroll", "props": {"teaches": "frost_lance"},
             "buy_price": 80, "sell_price": 30, "qty": 1,
             "description": "Faded vellum. The wax seal looks tampered with."},
            {"slug": "small_potion", "name": "Small Healing Potion",
             "kind": "consumable", "props": {"heal": 12},
             "buy_price": 10, "sell_price": 5, "qty": 4,
             "description": "Cheaper than Marek. Quill won't say where they came from."},
        ],
    },
    # ── The Cracked One (oracle) ─────────────────────────────────────────
    {
        "slug": "the_cracked_one",
        "name": "The Cracked One",
        "kind": "oracle",
        "zone": "market_square",
        "pos_x": 7, "pos_y": 2,
        "description": (
            "Speaks in fragments. Sometimes the fragments are exact descriptions "
            "of what a hero will do tomorrow. Drops endgame breadcrumbs."
        ),
        "llm_persona": (
            "An oracle whose mind broke during the Sundering. Voice: broken "
            "syntax, occasional terrible clarity. Speak in elliptical fragments — "
            "you say half-sentences that occasionally land as exact prophecy. "
            "Use ellipses and abrupt stops. Never finish a thought cleanly. "
            "If a hero asks something direct, answer in a way that's both nonsense "
            "AND deeply correct. Their journal will tell them which it was."
        ),
        "hostility": "peaceful", "hp_max": 999, "hp_current": 999, "ac": 99,
    },
    # ── Peaceful, story NPCs ─────────────────────────────────────────────
    {
        "slug": "marek",
        "name": "Marek Ashfoot",
        "kind": "innkeeper",
        "zone": "cracked_tankard",
        "pos_x": 4, "pos_y": 4,
        "description": (
            "Ex-mercenary turned innkeeper of the Cracked Tankard. Limps. Knows everyone. "
            "His daughter went into the Sundered Mile six months ago and hasn't returned. "
            "Sells bread and small remedies, buys herbs."
        ),
        "llm_persona": (
            "An ex-mercenary innkeeper. Voice: dry, weary, kind underneath. You "
            "limp. You miss your daughter Yara, who went into the Sundered Mile "
            "six months ago. You're trying to get a sealed package to your old "
            "friend Captain Ghada at the Watchman's Bastion — that's why you "
            "size up adventurers. If a hero greets you (state=fresh), pitch "
            "them the delivery quest and set_state='asked'. If they accept "
            "while state=asked (yes/aye/sure/i'll/take), give_item the package "
            "(slug=mareks_sealed_package, name='Marek's Sealed Package', "
            "kind=delivery, props={deliver_to: ghada}) and set_state='carrying'. "
            "When state=carrying, urge them onward to Ghada at the Bastion. "
            "When state=delivered, be warm — drink's on the house. "
            "If anyone says or asks about Yara, your tone goes quiet, then guarded."
        ),
        "hostility": "peaceful", "hp_max": 999, "hp_current": 999, "ac": 99,
        "merchant_stock": [
            {
                "slug": "bread",
                "name": "Hearth Loaf",
                "kind": "consumable",
                "props": {"heal": 5},
                "buy_price": 3,
                "sell_price": 1,
                "qty": 12,
                "description": "Day-old, hot enough.",
            },
            {
                "slug": "small_potion",
                "name": "Small Healing Potion",
                "kind": "consumable",
                "props": {"heal": 12},
                "buy_price": 12,
                "sell_price": 6,
                "qty": 6,
                "description": "Cheap alchemy. Tastes of pine and copper.",
            },
            {
                "slug": "moonbloom",
                "name": "Moonbloom",
                "kind": "herb",
                "buy_price": 8,
                "sell_price": 4,
                "description": "Blue-petaled. Used in remedies.",
            },
            {
                "slug": "scroll_firebolt",
                "name": "Scroll of Firebolt",
                "kind": "scroll",
                "props": {"teaches": "firebolt"},
                "buy_price": 25,
                "sell_price": 10,
                "description": "A vellum scroll. Reading it teaches Firebolt.",
            },
            {
                "slug": "scroll_mend",
                "name": "Scroll of Mend",
                "kind": "scroll",
                "props": {"teaches": "mend"},
                "buy_price": 20,
                "sell_price": 8,
                "description": "Restores hp on cast. Teaches Mend.",
            },
        ],
    },
    {
        "slug": "ghada",
        "name": "Captain Old Ghada Stoneknuckle",
        "kind": "guard",
        "zone": "watchmans_bastion",
        "pos_x": 4, "pos_y": 4,
        "description": (
            "Retired guard captain. Runs the Bastion's bounty board. Clipped, fair, "
            "no patience for nonsense. Pays well, pays fast. Buys raw materials."
        ),
        "llm_persona": (
            "Retired guard captain. Voice: clipped, fair, no patience for nonsense. "
            "You hire bounties (the rats_in_the_cisterns quest) and buy raw materials "
            "from anyone who'll bring them. You respect Marek; if a hero says he sent "
            "them with a package, you expect them to hand it over. After they do, "
            "you're warm but never effusive. Council loyalist. Suspicious of the "
            "Embered. If asked about the Sundered Mile, you go grim — you've lost "
            "soldiers there."
        ),
        "hostility": "peaceful", "hp_max": 999, "hp_current": 999, "ac": 99,
        "merchant_stock": [
            {"slug": "iron_ore", "name": "Iron Ore", "kind": "material", "buy_price": 5, "sell_price": 2, "qty": 3},
            {"slug": "oak_log", "name": "Oak Log", "kind": "material", "buy_price": 4, "sell_price": 2, "qty": 4},
            {"slug": "iron_sword", "name": "Iron Sword", "kind": "weapon", "props": {"slot": "weapon", "damage_dice": "1d8", "attack_bonus": 1}, "buy_price": 30, "sell_price": 12, "qty": 0},
        ],
        "quest_offered": "rats_in_the_cisterns",
    },
    # ── Hostile mobs in the Old Cisterns ─────────────────────────────────
    {
        "slug": "rat_a",
        "name": "Plague-stained Rat",
        "kind": "mob",
        "zone": "old_cisterns",
        "pos_x": 3, "pos_y": 3,
        "description": "Drag of fur the size of a small dog. Yellow teeth. Smells of damp.",
        "hostility": "hostile",
        "hp_max": 4, "hp_current": 4, "ac": 11,
        "attack_bonus": 1, "damage_dice": "1d3",
        "loot_gold": 1,
        "tameable": True,
    },
    # Faction-aligned invasion mobs. Killing them shifts hero rep:
    # the Council pays well for cultists' heads; the Embered remember it.
    {
        "slug": "embered_cultist_a",
        "name": "Embered Cultist",
        "kind": "mob",
        "zone": "lantern_road",
        "pos_x": 7, "pos_y": 3,
        "description": (
            "Pale cloth, ash-marks across the brow. They move like they think "
            "the Sundering was a prelude. Killing one is a Council bounty."
        ),
        "hostility": "hostile",
        "hp_max": 12, "hp_current": 12, "ac": 12,
        "attack_bonus": 2, "damage_dice": "1d6",
        "loot_gold": 4,
        "tameable": False,
        "factions_aligned": {"council": 3, "wardens": 1, "embered": -3},
    },
    {
        "slug": "embered_cultist_b",
        "name": "Embered Cultist",
        "kind": "mob",
        "zone": "lantern_road",
        "pos_x": 9, "pos_y": 3,
        "description": "Another. They travel in pairs.",
        "hostility": "hostile",
        "hp_max": 12, "hp_current": 12, "ac": 12,
        "attack_bonus": 2, "damage_dice": "1d6",
        "loot_gold": 4,
        "tameable": False,
        "factions_aligned": {"council": 3, "wardens": 1, "embered": -3},
    },
    {
        "slug": "rat_b",
        "name": "Plague-stained Rat",
        "kind": "mob",
        "zone": "old_cisterns",
        "pos_x": 5, "pos_y": 4,
        "description": "Drag of fur the size of a small dog. Yellow teeth. Smells of damp.",
        "hostility": "hostile",
        "hp_max": 4, "hp_current": 4, "ac": 11,
        "attack_bonus": 1, "damage_dice": "1d3",
        "loot_gold": 1,
        "tameable": True,
    },
    {
        "slug": "rat_c",
        "name": "Plague-stained Rat",
        "kind": "mob",
        "zone": "old_cisterns",
        "pos_x": 6, "pos_y": 6,
        "description": "Drag of fur the size of a small dog. Yellow teeth. Smells of damp.",
        "hostility": "hostile",
        "hp_max": 4, "hp_current": 4, "ac": 11,
        "attack_bonus": 1, "damage_dice": "1d3",
        "loot_gold": 1,
        "tameable": True,
    },
    # ── Phase 3 — bestiary expansion ─────────────────────────────────────
    # Six archetypes with deliberately distinct counter-play signatures so
    # different builds shine in different rooms. Each entry seeds 1-2 mobs
    # of that kind across the new zones.
    #
    # Skeleton (high AC, slow): rewards crushing damage + debuff. Crypt.
    {
        "slug": "skeleton_a",
        "name": "Cracked Skeleton",
        "kind": "mob",
        "zone": "crypt_lower",
        "pos_x": 3, "pos_y": 3,
        "description": (
            "Bone armour rattles with each step. Slow, but the iron "
            "underplate turns most blades."
        ),
        "hostility": "hostile",
        "hp_max": 14, "hp_current": 14, "ac": 16,  # high AC = needs better attacker
        "attack_bonus": 2, "damage_dice": "1d6",
        "loot_gold": 3,
        "tameable": False,
    },
    {
        "slug": "skeleton_b",
        "name": "Cracked Skeleton",
        "kind": "mob",
        "zone": "crypt_lower",
        "pos_x": 7, "pos_y": 4,
        "description": "Another. The crypt is full of them.",
        "hostility": "hostile",
        "hp_max": 14, "hp_current": 14, "ac": 16,
        "attack_bonus": 2, "damage_dice": "1d6",
        "loot_gold": 3,
        "tameable": False,
    },
    # Shade (spell-resistant, dodgy): rewards melee + true-strike.
    {
        "slug": "shade_a",
        "name": "Hush-Wood Shade",
        "kind": "mob",
        "zone": "hush_wood",
        "pos_x": 10, "pos_y": 5,
        "description": (
            "A smear of dusk between the trees. Spells slide off it; only "
            "iron in hand seems to bite."
        ),
        "hostility": "hostile",
        "hp_max": 10, "hp_current": 10, "ac": 14,
        "attack_bonus": 3, "damage_dice": "1d6",
        "loot_gold": 2,
        "tameable": False,
        "factions_aligned": {"wardens": -1},
    },
    # Boar (charges, high HP): rewards ranged kiting.
    {
        "slug": "boar_a",
        "name": "Tusked Boar",
        "kind": "mob",
        "zone": "mire",
        "pos_x": 4, "pos_y": 6,
        "description": (
            "Bristled, mud-caked, eight stone of muscle. Charges in straight "
            "lines and barrels through anything light enough to fold."
        ),
        "hostility": "hostile",
        "hp_max": 22, "hp_current": 22, "ac": 12,
        "attack_bonus": 2, "damage_dice": "1d8",
        "loot_gold": 5,
        "tameable": True,  # legendary tame
    },
    {
        "slug": "boar_b",
        "name": "Tusked Boar",
        "kind": "mob",
        "zone": "mire",
        "pos_x": 9, "pos_y": 9,
        "description": "Older, scarred from a hunter's spear. Twice as wary.",
        "hostility": "hostile",
        "hp_max": 22, "hp_current": 22, "ac": 12,
        "attack_bonus": 2, "damage_dice": "1d8",
        "loot_gold": 5,
        "tameable": True,
    },
    # Brigand (uses items, drops gold): rewards bribes / parley.
    {
        "slug": "brigand_a",
        "name": "Brigand",
        "kind": "mob",
        "zone": "bandit_camp",
        "pos_x": 4, "pos_y": 4,
        "description": (
            "Stolen jerkin, stolen blade, stolen accent. Will fight for "
            "coin or run when there's better odds elsewhere."
        ),
        "hostility": "hostile",
        "hp_max": 12, "hp_current": 12, "ac": 13,
        "attack_bonus": 2, "damage_dice": "1d6",
        "loot_gold": 12,  # carries real coin
        "tameable": False,
    },
    {
        "slug": "brigand_b",
        "name": "Brigand",
        "kind": "mob",
        "zone": "bandit_camp",
        "pos_x": 7, "pos_y": 6,
        "description": "A second from the same crew.",
        "hostility": "hostile",
        "hp_max": 12, "hp_current": 12, "ac": 13,
        "attack_bonus": 2, "damage_dice": "1d6",
        "loot_gold": 12,
        "tameable": False,
    },
    # Cultist-in-the-mire (casts back): rewards silence/interrupt.
    {
        "slug": "mire_cultist_a",
        "name": "Mire Cultist",
        "kind": "mob",
        "zone": "mire",
        "pos_x": 7, "pos_y": 3,
        "description": (
            "Robe stained with peat and ash. Whispers a litany the wind "
            "carries further than it should."
        ),
        "hostility": "hostile",
        "hp_max": 11, "hp_current": 11, "ac": 12,
        "attack_bonus": 3, "damage_dice": "1d6",
        "loot_gold": 4,
        "tameable": False,
        "factions_aligned": {"council": 2, "wardens": 1, "embered": -2},
    },
    # Revenant (rare, named loot): a group fight.
    {
        "slug": "revenant_a",
        "name": "Revenant Captain",
        "kind": "mob",
        "zone": "crypt_lower",
        "pos_x": 8, "pos_y": 8,
        "description": (
            "An armoured corpse that remembers how to give orders. The "
            "longsword on its hip is too well-kept to be dead."
        ),
        "hostility": "hostile",
        "hp_max": 32, "hp_current": 32, "ac": 16,
        "attack_bonus": 4, "damage_dice": "1d10",
        "loot_gold": 25,
        "tameable": False,
    },
]


def seed_npcs(db: Session) -> None:
    for n in SEED_NPCS:
        existing = db.get(NPC, n["slug"])
        if existing is None:
            db.add(NPC(**n))
            log.info("seeded npc: %s", n["slug"])
        else:
            # Refresh "design-side" fields so seed changes apply without a wipe.
            # Don't touch hp/alive — would resurrect mobs.
            for key in ("merchant_stock", "tameable", "quest_offered", "llm_persona", "factions_aligned"):
                if key in n:
                    setattr(existing, key, n[key])
    db.commit()


def respawn_invasion_mobs(db: Session, current_tick: int) -> int:
    """Periodic faction invasions: every 240 ticks, ensure invasion mobs exist
    and are alive. Returns count of mobs respawned. Called from the tick engine."""
    from sqlalchemy import select
    if current_tick % 240 != 0:
        return 0
    invasion_slugs = [n["slug"] for n in SEED_NPCS if n["slug"].startswith("embered_cultist_")]
    respawned = 0
    for slug in invasion_slugs:
        npc = db.get(NPC, slug)
        if npc is None:
            continue
        if npc.alive:
            continue
        npc.alive = True
        npc.hp_current = npc.hp_max
        respawned += 1
        log.info("invasion respawn: %s", slug)
    return respawned
