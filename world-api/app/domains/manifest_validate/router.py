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

from fastapi import APIRouter, Depends, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import NPC, Recipe, Spell, Zone
from app.domains.hero.service import HeroService
from app.domains.manifest_validate.tools_validator import validate_tools

router = APIRouter(prefix="/manifest", tags=["manifest"])


# Verbs the world resolves today. Drift here means an out-of-date
# validator, not a runtime bug — the resolver is still authoritative.
VALID_VERBS = {
    "wait", "look", "move", "say", "examine", "pickup", "drop", "give",
    "travel", "equip", "unequip", "gather", "fish", "craft",
    "buy", "sell", "cast", "learn", "steal", "tame",
    "accept_quest", "claim_reward", "journal_write", "recall",
    "store", "withdraw", "buy_house",
    "offer", "accept_offer", "reject_offer",
    "register_tournament", "post_bounty",
    "post_contract", "claim_contract", "cancel_contract",
    "attack", "attack_hero", "defend", "flee", "leave_sandbox",
}


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
        },
    )
