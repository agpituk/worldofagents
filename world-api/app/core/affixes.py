"""Item quality + affixes (Phase 7).

The roadmap's plan: a crafted or dropped weapon gets a quality tier
(rough / fine / exceptional / masterwork) plus optionally one prefix
and one suffix. None of this needs a schema change — everything lives
inside `item.props` JSON.

This module is the only place that knows the affix tables and the
roll math. Callers (`_resolve_craft`, mob loot hooks) hand it a
`base_props` dict and parameters, get back a `props` dict with
quality + prefix + suffix folded in. Whatever's already in
`base_props` (slot, damage_dice, ac_bonus) is preserved and modified
in place by the affix payload.

`name_affixed_for(base_name, props)` renders the display name —
"Flaming Iron Sword of Warding" — from the affix metadata.
"""

from __future__ import annotations

import random
from typing import Any


# ── Quality tiers ────────────────────────────────────────────────────────
#
# Multiplicative on the base item's primary stat. A masterwork iron sword
# rolls its damage at +50% effective; a rough one at -20%. We don't
# rewrite damage_dice (that breaks the existing "1d8" parser) — instead
# the quality multiplier is recorded on `props.damage_multiplier` and
# `props.ac_multiplier`, and the combat resolver multiplies the rolled
# damage at hit time. Existing un-affixed items have multiplier=1.0
# implicitly so this stays backward-compatible.

QUALITY_TIERS = ["rough", "fine", "exceptional", "masterwork"]

QUALITY_MULTIPLIER: dict[str, float] = {
    "rough":       0.8,
    "fine":        1.0,   # the default; no display tag if standalone
    "exceptional": 1.25,
    "masterwork":  1.5,
}


def _quality_tier_for_skill(skill_level: int) -> str:
    """Pick a quality tier driven by the crafter's skill, with a small
    upward variance so a high-skill smith occasionally drops to fine
    (and a mid-skill smith occasionally rolls exceptional).

    Bands:
      lvl  0–29  → rough (with 10% chance fine)
      lvl 30–69  → fine  (with 10% chance exceptional)
      lvl 70–89  → exceptional (with 10% chance masterwork)
      lvl 90+    → masterwork (with 20% chance exceptional)
    """
    if skill_level >= 90:
        return "masterwork" if random.random() >= 0.2 else "exceptional"
    if skill_level >= 70:
        return "exceptional" if random.random() >= 0.1 else "masterwork"
    if skill_level >= 30:
        return "fine" if random.random() >= 0.1 else "exceptional"
    return "rough" if random.random() >= 0.1 else "fine"


# ── Affixes ──────────────────────────────────────────────────────────────
#
# Each affix has a slug, a display name (used in the rendered item name),
# and a `payload` dict that's shallow-merged into `props`. The combat
# resolver reads `extra_damage_dice` (added at hit time), `heal_on_hit`,
# `crit_bonus`, `ac_bonus_extra`, etc. so adding a new affix is "tweak
# the table here" — no resolver changes needed.

PREFIX_AFFIXES: list[dict[str, Any]] = [
    {
        "slug": "flaming",
        "display": "Flaming",
        "applies_to": ("weapon",),
        "payload": {"extra_damage_dice": "1d4", "extra_damage_kind": "fire"},
    },
    {
        "slug": "frostbound",
        "display": "Frostbound",
        "applies_to": ("weapon",),
        "payload": {"extra_damage_dice": "1d4", "extra_damage_kind": "cold"},
    },
    {
        "slug": "thirsty",
        "display": "Thirsty",
        "applies_to": ("weapon",),
        "payload": {"heal_on_hit": 2},
    },
    {
        "slug": "keen",
        "display": "Keen",
        "applies_to": ("weapon",),
        "payload": {"crit_bonus": 1},  # 19-20 crit instead of 20
    },
    {
        "slug": "reinforced",
        "display": "Reinforced",
        "applies_to": ("armor",),
        "payload": {"ac_bonus_extra": 1},
    },
    {
        "slug": "swift",
        "display": "Swift",
        "applies_to": ("armor",),
        "payload": {"speed_bonus": 1},  # +1 to move speed
    },
]

SUFFIX_AFFIXES: list[dict[str, Any]] = [
    {
        "slug": "of_warding",
        "display": "of Warding",
        "applies_to": ("weapon", "armor"),
        "payload": {"ac_bonus_extra": 1},
    },
    {
        "slug": "of_haste",
        "display": "of Haste",
        "applies_to": ("weapon", "armor"),
        "payload": {"speed_bonus": 1},
    },
    {
        "slug": "of_the_bear",
        "display": "of the Bear",
        "applies_to": ("weapon", "armor"),
        "payload": {"to_hit_bonus_extra": 1},
    },
    {
        "slug": "of_silver_blood",
        "display": "of Silver Blood",
        "applies_to": ("weapon",),
        "payload": {"undead_bonus_dice": "1d6"},  # vs revenant/skeleton
    },
]


def _matching_affix(pool: list[dict[str, Any]], slot: str | None) -> dict[str, Any] | None:
    """Pick a random affix whose `applies_to` includes `slot`. Returns
    None if the pool has no eligible entries (eg. a trinket with no
    matching prefix table)."""
    eligible = [a for a in pool if slot is None or slot in a["applies_to"]]
    if not eligible:
        return None
    return random.choice(eligible)


def roll_affixes(
    base_props: dict[str, Any],
    *,
    skill_level: int = 0,
    prefix_chance: float = 0.0,
    suffix_chance: float = 0.0,
    force_quality: str | None = None,
) -> dict[str, Any]:
    """Return a new props dict with quality + (optional) affixes folded
    in. The base_props are deep-copied so the caller can keep the
    original untouched.

    `prefix_chance` / `suffix_chance` are probabilities in [0, 1] that
    a prefix/suffix is rolled. Mob loot tables typically pass 0.5/0.25;
    masterwork crafts pass higher. `force_quality` overrides the
    skill-driven quality roll (used by mob drops where the mob
    specifies its own quality tier).
    """
    out = dict(base_props or {})
    quality = force_quality or _quality_tier_for_skill(skill_level)
    out["quality"] = quality

    # Apply quality multipliers to damage / AC. We store the multiplier
    # rather than rewriting damage_dice so the dice notation stays
    # parseable. The combat resolver multiplies at hit time.
    mult = QUALITY_MULTIPLIER.get(quality, 1.0)
    if "damage_dice" in out and out["damage_dice"] != "0d0":
        out["damage_multiplier"] = mult
    if "ac_bonus" in out:
        out["ac_multiplier"] = mult

    slot = out.get("slot")
    affixes: list[dict[str, Any]] = []

    if random.random() < prefix_chance:
        prefix = _matching_affix(PREFIX_AFFIXES, slot)
        if prefix is not None:
            affixes.append({"role": "prefix", "slug": prefix["slug"], "display": prefix["display"]})
            for k, v in prefix["payload"].items():
                # numeric stacking: ac_bonus_extra etc. add to whatever
                # the suffix or base might also write.
                if isinstance(v, (int, float)) and isinstance(out.get(k), (int, float)):
                    out[k] = out[k] + v
                else:
                    out[k] = v

    if random.random() < suffix_chance:
        suffix = _matching_affix(SUFFIX_AFFIXES, slot)
        if suffix is not None:
            affixes.append({"role": "suffix", "slug": suffix["slug"], "display": suffix["display"]})
            for k, v in suffix["payload"].items():
                if isinstance(v, (int, float)) and isinstance(out.get(k), (int, float)):
                    out[k] = out[k] + v
                else:
                    out[k] = v

    if affixes:
        out["affixes"] = affixes
    return out


def render_affixed_name(base_name: str, props: dict[str, Any]) -> str:
    """Render the display name from the affix metadata. Quality is
    folded in unless it's `fine` (the unmarked default) — a Masterwork
    Iron Sword of Warding reads loud; a Fine Iron Sword reads as just
    Iron Sword. Returns `base_name` unchanged when no affixes/quality
    apply, so old un-affixed items keep their text."""
    quality = (props or {}).get("quality")
    affixes = (props or {}).get("affixes") or []

    parts: list[str] = []
    prefix = next((a["display"] for a in affixes if a.get("role") == "prefix"), None)
    suffix = next((a["display"] for a in affixes if a.get("role") == "suffix"), None)

    if quality and quality not in (None, "fine"):
        parts.append(quality.title())
    if prefix:
        parts.append(prefix)
    parts.append(base_name)
    if suffix:
        parts.append(suffix)

    if len(parts) == 1:
        return base_name
    return " ".join(parts)
