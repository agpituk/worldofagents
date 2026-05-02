"""Manifest validation schemas. Strict enough to reject obvious garbage,
loose enough that we can keep iterating on the manifest shape without breaking storage.

Authoritative manifest shape: see DESIGN.md §7.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# 100 points to distribute, min 5 / max 25 per stat.
TOTAL_POINTS = 100
STAT_MIN = 5
STAT_MAX = 25
DIVISIONS = ("featherweight", "middleweight", "heavyweight")


class Build(BaseModel):
    str_: int = Field(alias="str")
    dex: int
    con: int
    int_: int = Field(alias="int")
    wis: int
    cha: int

    model_config = {"populate_by_name": True}

    @field_validator("str_", "dex", "con", "int_", "wis", "cha")
    @classmethod
    def _per_stat_bounds(cls, v: int) -> int:
        if v < STAT_MIN or v > STAT_MAX:
            raise ValueError(f"each stat must be between {STAT_MIN} and {STAT_MAX}")
        return v


class HeroManifest(BaseModel):
    """The user-supplied manifest. We keep the full document under `extras`
    so future fields (composites, perception, reflexes, models) round-trip
    without schema churn."""

    name: str = Field(min_length=2, max_length=120)
    author: str = Field(min_length=1, max_length=120)
    division: Literal["featherweight", "middleweight", "heavyweight"]
    bio: str = Field(default="", max_length=2000)
    build: Build
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("build")
    @classmethod
    def _build_total(cls, v: Build) -> Build:
        total = v.str_ + v.dex + v.con + v.int_ + v.wis + v.cha
        if total > TOTAL_POINTS:
            raise ValueError(f"build totals {total} > {TOTAL_POINTS}; over budget")
        return v


class RegisterHeroResponse(BaseModel):
    id: uuid.UUID
    name: str
    division: str
    auth_token: str  # for the bot SDK to open WS


class HeroOut(BaseModel):
    id: uuid.UUID
    name: str
    author: str
    division: str
    bio: str
    hp: int
    status: str
    zone: str
    pos: list[int]
    build: dict[str, int]
    skills: dict[str, int] = Field(default_factory=dict)
    skill_levels: dict[str, int] = Field(default_factory=dict)
    # Phase 5 — derived identity surface. `skill_titles` is the
    # per-skill rank (Skilled / Expert / Grandmaster) for skills above
    # the threshold; `top_title` is the headline string ("GM Fisherman").
    skill_titles: dict[str, str] = Field(default_factory=dict)
    top_title: str | None = None
    # Phase 5 — public reputation counters. {kills, pvp_kills, dead}.
    reputation: dict[str, Any] = Field(default_factory=dict)
    # Phase 6 — skill cap surface. `skill_cap` is 0 if uncapped (the
    # default); `skill_points_remaining` is `cap - sum(xp)`, also 0 if
    # uncapped. Reflex DSL reads these from the perception payload to
    # plan around forced specialization.
    skill_cap: int = 0
    skill_points_remaining: int = 0
    equipped: dict[str, Any] = Field(default_factory=dict)
    mana_current: int = 0
    mana_max: int = 0
    known_spells: list[str] = Field(default_factory=list)
    faction_rep: dict[str, int] = Field(default_factory=dict)
    # Lifespan — born_at_tick is when the hero was registered, died_at_tick
    # is null while alive. ticks_alive = (died_at_tick or current_tick) - born_at_tick.
    born_at_tick: int = 0
    died_at_tick: int | None = None
    # Phase 8 — sandbox protection. While `protected_until_tick > current_tick`,
    # fatal blows respawn instead of permadying. 0 = no protection.
    protected_until_tick: int = 0
    # Public manifest — `system` is stripped so the public hero page can show
    # reflexes, build, bio, and composite recipes without leaking the prompt.
    manifest: dict[str, Any] | None = None

    @classmethod
    def from_hero(cls, row) -> "HeroOut":
        # Imported lazily to avoid an import cycle (actions imports models
        # which transitively imports hero schemas via service).
        from app.core.actions import (
            _hero_skill_cap,
            _hero_skill_total,
            _reputation_for,
            skill_titles_for,
            top_title_for,
        )
        skills = row.skills or {}
        skill_levels = {
            name: min(100, int(xp or 0) // 10) for name, xp in skills.items()
        }
        cap = _hero_skill_cap(row)
        remaining = max(0, cap - _hero_skill_total(row)) if cap > 0 else 0
        return cls(
            id=row.id,
            name=row.name,
            author=row.author,
            division=row.division,
            bio=row.bio,
            hp=row.hp,
            status=row.status,
            zone=row.zone,
            pos=[row.pos_x, row.pos_y],
            build={
                "str": row.str_, "dex": row.dex, "con": row.con,
                "int": row.int_, "wis": row.wis, "cha": row.cha,
            },
            skills=dict(skills),
            skill_levels=skill_levels,
            skill_titles=skill_titles_for(dict(skills)),
            top_title=top_title_for(dict(skills)),
            reputation=_reputation_for(row),
            skill_cap=cap,
            skill_points_remaining=remaining,
            equipped=dict(row.equipped or {}),
            mana_current=int(row.mana_current or 0),
            mana_max=int(row.mana_max or 0),
            known_spells=list(row.known_spells or []),
            faction_rep=dict(row.faction_rep or {}),
            born_at_tick=int(getattr(row, "born_at_tick", 0) or 0),
            died_at_tick=getattr(row, "died_at_tick", None),
            protected_until_tick=int(getattr(row, "protected_until_tick", 0) or 0),
            manifest=_redact_manifest(row.manifest),
        )


def _redact_manifest(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Strip private fields from a manifest before exposing it.

    Currently removes `system` (the player's prompt) and any key ending in
    `_secret`. Reflexes, build, abilities, memory schema all remain visible —
    those are the player's craft and we want them shareable."""
    if not isinstance(raw, dict):
        return None
    redacted: dict[str, Any] = {}
    for k, v in raw.items():
        if k == "system":
            continue
        if k.endswith("_secret"):
            continue
        if isinstance(v, dict):
            redacted[k] = _redact_manifest(v) or {}
        else:
            redacted[k] = v
    return redacted
