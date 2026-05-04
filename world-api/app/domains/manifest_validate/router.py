"""Manifest validation surface (Phase 8).

The deploy form posts the user's YAML/JSON manifest here before
submission. We return a list of structured issues — `severity` and
`message`, optionally a `path` indicating where in the manifest the
issue lives — so the form can render red squigglies and a one-line
summary without the user having to re-deploy to learn their reflex
references a misspelled spell.

Checks:
  • Schema fits `HeroManifest` (delegated to the existing parse path).
  • Every referenced spell / item / verb / zone / NPC slug exists in
    the seed.
  • Skill-cap declared by the manifest is in the supported range.
  • Reflexes is a list of well-formed entries (best-effort lint).

This endpoint is read-only and does not write a hero.
"""

from __future__ import annotations

from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import NPC, Recipe, Spell, Zone
from app.core.verbs import VALID_VERBS
from app.domains.hero.service import HeroService
from app.domains.manifest_validate.clamp_table import CLAMP_TABLE
from app.domains.manifest_validate.shared import META_VERBS, SDK_CONVENIENCE_VERBS
from app.domains.manifest_validate.tools_validator import validate_tools

# Re-exported here so existing imports `from ...router import VALID_VERBS`
# keep working. New code should import from app.core.verbs directly.
__all__ = ["VALID_VERBS"]

router = APIRouter(prefix="/manifest", tags=["manifest"])

# A second router so the verb-catalog endpoint mounts under /admin without
# moving the existing /manifest/validate path.
admin_router = APIRouter(prefix="/admin", tags=["admin"])


class Issue(BaseModel):
    severity: str       # "error" | "warning" | "info"
    message: str
    path: str | None = None


class ValidationOut(BaseModel):
    valid: bool
    issues: list[Issue]
    summary: dict[str, Any]


def _walk_strings(node: Any, *, path: str = "") -> list[tuple[str, str]]:
    """Yield `(path, value)` for every string leaf reachable from
    `node`. Used by the lint phase to scan for spell/item/zone/NPC
    references no matter how deeply nested in the manifest's JSON."""
    out: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out.extend(_walk_strings(v, path=f"{path}.{k}" if path else k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_walk_strings(v, path=f"{path}[{i}]"))
    elif isinstance(node, str):
        out.append((path, node))
    return out


@router.post("/validate", response_model=ValidationOut)
async def validate_manifest(
    db: Annotated[Session, Depends(get_db)],
    manifest: UploadFile = File(..., description="YAML or JSON manifest"),
):
    raw = await manifest.read()
    issues: list[Issue] = []

    # Schema parse — surfaces every Pydantic validation error.
    try:
        parsed = HeroService.parse_manifest(raw)
    except Exception as exc:
        issues.append(Issue(severity="error", message=f"manifest parse failed: {exc}"))
        return ValidationOut(valid=False, issues=issues, summary={"parsed": False})

    # Cross-reference seed catalogues.
    spell_slugs = {s for s in db.scalars(select(Spell.slug))}
    npc_slugs = {s for s in db.scalars(select(NPC.slug))}
    zone_slugs = {s for s in db.scalars(select(Zone.slug))}
    recipe_slugs = {s for s in db.scalars(select(Recipe.slug))}

    extras = parsed.extras or {}
    abilities = extras.get("abilities") or {}

    # Tools — composites + docstring overrides (Phase 2). Phase 3 lifts the
    # gate on `when:` / `clamp:` / `after:` / `if`-step. The validator is
    # the single authority on what shapes the runtime will accept.
    tools_issues, parsed_tools = validate_tools(
        extras.get("tools"),
        valid_verbs=VALID_VERBS,
    )
    for issue in tools_issues:
        issues.append(Issue(**issue))
    composite_tool_names: set[str] = {
        t.name for t in parsed_tools if getattr(t, "kind", None) == "composite"
    }

    # Spells the manifest declares the hero will know.
    declared_spells = abilities.get("spells") or []
    if isinstance(declared_spells, list):
        for i, sp in enumerate(declared_spells):
            if isinstance(sp, str) and sp not in spell_slugs:
                issues.append(Issue(
                    severity="error",
                    message=f"unknown spell '{sp}' (no such row in /spells)",
                    path=f"abilities.spells[{i}]",
                ))

    # Reflexes — best-effort scan for `do: <verb>` and string references.
    reflexes = extras.get("reflexes")
    if reflexes is not None and not isinstance(reflexes, list):
        issues.append(Issue(
            severity="error",
            message=f"reflexes must be a list (got {type(reflexes).__name__})",
            path="reflexes",
        ))
    elif isinstance(reflexes, list):
        for i, rx in enumerate(reflexes):
            if not isinstance(rx, dict):
                issues.append(Issue(
                    severity="error",
                    message=f"reflex entry must be a mapping (got {type(rx).__name__})",
                    path=f"reflexes[{i}]",
                ))
                continue
            then = rx.get("then")
            if isinstance(then, dict):
                verb = then.get("do")
                if (
                    isinstance(verb, str)
                    and verb not in VALID_VERBS
                    and verb not in META_VERBS
                    and verb not in SDK_CONVENIENCE_VERBS
                    and verb not in composite_tool_names
                ):
                    issues.append(Issue(
                        severity="error",
                        message=f"unknown verb '{verb}' in reflex.then.do",
                        path=f"reflexes[{i}].then.do",
                    ))
                spell = then.get("spell")
                if isinstance(spell, str) and spell not in spell_slugs:
                    issues.append(Issue(
                        severity="warning",
                        message=f"reflex casts unknown spell '{spell}'",
                        path=f"reflexes[{i}].then.spell",
                    ))
                zone = then.get("zone")
                if isinstance(zone, str) and zone not in zone_slugs:
                    issues.append(Issue(
                        severity="warning",
                        message=f"reflex travels to unknown zone '{zone}'",
                        path=f"reflexes[{i}].then.zone",
                    ))
                recipe = then.get("recipe")
                if isinstance(recipe, str) and recipe not in recipe_slugs:
                    issues.append(Issue(
                        severity="warning",
                        message=f"reflex crafts unknown recipe '{recipe}'",
                        path=f"reflexes[{i}].then.recipe",
                    ))

    # Skill cap range check.
    build_block = extras.get("build") or {}
    if isinstance(build_block, dict) and "skill_cap" in build_block:
        try:
            cap = int(build_block["skill_cap"])
            if cap < 0:
                issues.append(Issue(severity="error", message="skill_cap cannot be negative", path="build.skill_cap"))
            elif cap > 0 and cap < 100:
                issues.append(Issue(
                    severity="warning",
                    message=f"skill_cap={cap} is below 100 — no skill will reach level 10",
                    path="build.skill_cap",
                ))
        except (TypeError, ValueError):
            issues.append(Issue(severity="error", message="skill_cap must be an integer", path="build.skill_cap"))

    # Recall tags — surface the size of the bag rather than the contents.
    memory_block = extras.get("memory") or {}
    recall_tags = (memory_block or {}).get("recall_tags") if isinstance(memory_block, dict) else None
    if isinstance(recall_tags, list) and len(recall_tags) > 16:
        issues.append(Issue(
            severity="warning",
            message=f"recall_tags has {len(recall_tags)} entries; only the first 16 are used",
            path="memory.recall_tags",
        ))

    # Surface tool entries as plain dicts so the deploy UI can render
    # them as cards without re-parsing YAML client-side. Truncated
    # description fields keep the response small.
    tools_preview: list[dict[str, Any]] = []
    for t in parsed_tools:
        if getattr(t, "kind", None) == "composite":
            tools_preview.append({
                "name": t.name,
                "kind": "composite",
                "description": (t.description or "").strip()[:200],
                "step_count": len(getattr(t, "steps", []) or []),
                "param_count": len(getattr(t, "parameters", []) or []),
            })
        else:
            tools_preview.append({
                "name": t.name,
                "kind": "override",
                "override_verb": getattr(t, "override_verb", t.name),
                "description": (getattr(t, "description", "") or "").strip()[:200],
                "has_when": getattr(t, "when_expr", None) is not None,
                "clamp_param_count": len(getattr(t, "clamp", {}) or {}),
                "after_step_count": len(getattr(t, "after", []) or []),
            })

    has_errors = any(i.severity == "error" for i in issues)
    return ValidationOut(
        valid=not has_errors,
        issues=issues,
        summary={
            "parsed": True,
            "name": parsed.name,
            "division": parsed.division,
            "spells_declared": len(declared_spells) if isinstance(declared_spells, list) else 0,
            "reflexes_declared": len(reflexes) if isinstance(reflexes, list) else 0,
            "tools_declared": len(parsed_tools),
            "tools": tools_preview,
        },
    )


# ---------------------------------------------------------------------------
# /admin/verb-catalog — read-only verb spec for the block editor
# ---------------------------------------------------------------------------


@router.post("/simulate-tick")
async def simulate_tick(
    manifest: UploadFile = File(..., description="YAML manifest"),
):
    """Run the reflex engine and tool dispatcher against a synthetic
    perception to show the user what would happen on tick 0. Powers
    the first-tick simulation panel in the block editor (Phase 1+).

    No DB; no actual gameplay state. The synthetic perception sets
    sensible defaults: full HP, market_square zone, no hostiles, full
    inventory. The point is to surface which reflex would fire (or
    `wait` if none match) and what tools the LLM would see.
    """
    raw = await manifest.read()
    try:
        doc = yaml.safe_load(raw) or {}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"yaml parse failed: {exc}")
    if not isinstance(doc, dict):
        raise HTTPException(status_code=400, detail="manifest must be a mapping")

    inner = doc.get("hero") if isinstance(doc.get("hero"), dict) else doc
    inner = inner or {}

    from arena_bot.actions import DEFAULT_TOOLS
    from arena_bot.client import Perception
    from arena_bot.reflexes import ReflexEngine
    from arena_bot.tool_dispatch import HeroToolset
    from arena_bot.tools import build_tool_specs_for_hero

    reflex_engine = ReflexEngine(inner.get("reflexes") or [])
    toolset = HeroToolset.from_manifest(doc)

    # Synthetic perception — sufficient for a deterministic dry-run.
    perception = Perception(
        tick_id=0,
        your_state={
            "hp": 30,
            "gold": 100,
            "zone": "market_square",
            "pos": [4, 4],
            "mana_current": 10,
            "mana_max": 10,
            "equipped": {},
            "inventory": [],
            "skills": {},
        },
        perception={
            "visible_npcs": [],
            "visible_heroes": [],
            "visible_items": [],
            "visible_resources": [],
            "memory": {"npcs": {}},
            "zone": {"connections": [], "kind": "sanctuary"},
            "inventory": [],
        },
        deadline_ms=6000,
    )

    chosen_reflex_index: int | None = None
    chosen_action: dict | None = None
    when_text: str | None = None
    try:
        action, debug = reflex_engine.evaluate_with_debug(perception)
        if action is not None:
            chosen_action = dict(action)
            chosen_reflex_index = (debug or {}).get("reflex_index")
            when_text = (debug or {}).get("when")
    except Exception:
        chosen_action = None

    manifest_tools = (
        list(toolset.composites.values()) + list(toolset.overrides.values())
    )
    specs = build_tool_specs_for_hero(list(DEFAULT_TOOLS), manifest_tools)

    return {
        "chosen_reflex_index": chosen_reflex_index,
        "chosen_action": chosen_action or {"do": "wait", "_note": "no reflex matched"},
        "when": when_text,
        "tools_visible_to_llm": [
            {"name": s["function"]["name"], "description": s["function"]["description"][:120]}
            for s in specs
        ],
        "composite_count": len(toolset.composites),
        "override_count": len(toolset.overrides),
    }


@admin_router.get("/hero/{hero_id}/tool-spec")
def hero_tool_spec(
    db: Annotated[Session, Depends(get_db)],
    hero_id: str,
):
    """Return the OpenAI-format tool list this hero would receive from
    the LLM gateway. Lets you verify a docstring override applied
    without spinning up the bot loop. Read-only."""
    import uuid as _uuid
    from app.core.models import Hero
    try:
        hid = _uuid.UUID(hero_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid hero_id")
    hero = db.get(Hero, hid)
    if hero is None:
        raise HTTPException(status_code=404, detail="hero not found")

    from arena_bot.actions import DEFAULT_TOOLS  # type: ignore
    from arena_bot.tool_dispatch import HeroToolset  # type: ignore
    from arena_bot.tools import build_tool_specs_for_hero  # type: ignore

    toolset = HeroToolset.from_manifest(hero.manifest or {})
    manifest_tools = (
        list(toolset.composites.values())
        + list(toolset.overrides.values())
    )
    specs = build_tool_specs_for_hero(list(DEFAULT_TOOLS), manifest_tools)
    return {
        "hero_id": hero_id,
        "hero_name": hero.name,
        "specs": specs,
        "composite_count": len(toolset.composites),
        "override_count": len(toolset.overrides),
    }


@admin_router.get("/verb-catalog")
def verb_catalog():
    """Public verb metadata: what verbs exist, which params each takes,
    which params are clampable. Consumed by the frontend's block-spec
    generator (BLOCK_EDITOR.md §8). No auth — the verb list is public
    information already exposed by the bot SDK's docstrings."""
    out: list[dict[str, Any]] = []
    for verb in sorted(VALID_VERBS):
        clamps = CLAMP_TABLE.get(verb, {})
        out.append({
            "verb": verb,
            "clampable": [
                {"param": p, "kind": spec.kind, "max_length": spec.max_length}
                for p, spec in clamps.items()
            ],
        })
    return {"verbs": out}
