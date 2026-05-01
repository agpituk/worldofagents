from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.models import Recipe, Spell

router = APIRouter(tags=["catalog"])


class RecipeOut(BaseModel):
    slug: str
    name: str
    output_slug: str
    output_name: str
    output_kind: str
    inputs: list
    skill_required: str
    skill_min: int
    workstation_kind: str


@router.get("/recipes", response_model=list[RecipeOut])
def list_recipes(db: Annotated[Session, Depends(get_db)]):
    """Public recipe catalogue — hidden recipes are excluded by design.
    Heroes can still craft them; they just have to *discover* the inputs."""
    rows = list(db.scalars(
        select(Recipe).where(Recipe.hidden.is_(False)).order_by(Recipe.slug)
    ))
    return [
        RecipeOut(
            slug=r.slug, name=r.name,
            output_slug=r.output_slug, output_name=r.output_name, output_kind=r.output_kind,
            inputs=list(r.inputs or []),
            skill_required=r.skill_required, skill_min=r.skill_min,
            workstation_kind=r.workstation_kind,
        )
        for r in rows
    ]


class SpellOut(BaseModel):
    slug: str
    name: str
    description: str
    school: str
    target_kind: str
    mana_cost: int
    range: int
    damage_dice: str
    heal_dice: str
    skill_min: int


@router.get("/spells", response_model=list[SpellOut])
def list_spells(db: Annotated[Session, Depends(get_db)]):
    rows = list(db.scalars(select(Spell).order_by(Spell.slug)))
    return [
        SpellOut(
            slug=s.slug, name=s.name, description=s.description, school=s.school,
            target_kind=s.target_kind, mana_cost=s.mana_cost, range=s.range,
            damage_dice=s.damage_dice, heal_dice=s.heal_dice, skill_min=s.skill_min,
        )
        for s in rows
    ]
