"""Skill titles & rendered identity strings.

Phase 5 derived helpers — there's no schema change here, just text
formatting that several surfaces (HeroOut, perception, leaderboards,
item tooltips) need to agree on. Living in its own module means a new
caller can import the title formatter without dragging in the rest of
the actions package.
"""

from __future__ import annotations


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
