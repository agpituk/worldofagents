"""Gathering, fishing, crafting action verbs."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.actions._helpers import (
    _add_to_inventory,
    _consume_from_inventory,
    _grant_xp,
    _inventory_total,
    _journal_milestone,
    _quest_progress,
    _skill_level,
)
from app.core.actions._result import ResolutionResult
from app.core.memory import update_memory
from app.core.models import Hero, NPC, Recipe, ResourceNode


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

    have_skill = _skill_level(hero, recipe.skill_required)
    if have_skill < recipe.skill_min:
        return ResolutionResult(
            False,
            {
                "verb": "craft",
                "error": f"{recipe.skill_required} too low ({have_skill} < {recipe.skill_min})",
            },
        )

    for inp in recipe.inputs:
        slug = inp["slug"]
        need = int(inp.get("count", 1))
        have = _inventory_total(db, hero, slug)
        if have < need:
            return ResolutionResult(
                False, {"verb": "craft", "error": f"need {need}× {slug}, have {have}"}
            )

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
