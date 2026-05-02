"""v1_8_skill_split_phase1

Phase 1 of the build-diversity roadmap: splits the single `crafting`
bucket into a real per-discipline skill tree. The gather verb already
keys on `node.skill_required` and the craft verb on
`recipe.skill_required` — this migration just reassigns those columns
on the existing seeded rows so XP starts flowing into the right buckets.

Per the roadmap's migration note, existing `hero.skills` dicts are
zeroed out so heroes regrind under the new skill keys (cleanest for the
prototype; copying the old `crafting` total into `smithing` is the
alternative but conflated gather + craft, so a clean slate is more
honest).

New seeded content (nodes/recipes/workstations) is inserted by the
`seed_world_economy` startup hook against rows that don't already exist;
it doesn't run inside this migration.

Revision ID: d1a7f4c0b001
Revises: 8c4c14e9a7d2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1a7f4c0b001"
down_revision: Union[str, None] = "8c4c14e9a7d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Existing seeded resource nodes get reassigned skill_required values.
# Anything not in this map keeps its current value (default
# "gathering" for nodes seeded before v1_8).
_NODE_SKILL_REASSIGNMENTS = [
    ("iron_ore_vein_1", "mining"),
    ("iron_ore_vein_2", "mining"),
    ("moonbloom_patch", "herbalism"),
    ("oak_log_pile", "lumberjacking"),
]


# Existing seeded recipes get reassigned skill_required + workstation.
# Forge stays as-is (still the smithing workstation kind); only the
# skill key changes for those rows.
_RECIPE_REASSIGNMENTS = [
    # slug, skill_required, workstation_kind
    ("iron_sword_recipe", "smithing", "forge_workstation"),
    ("leather_jerkin_recipe", "tailoring", "loom_workstation"),
    ("scaleforged_blade_recipe", "smithing", "forge_workstation"),
    ("tempered_charm_recipe", "tinkering", "tinker_workstation"),
]


def upgrade() -> None:
    bind = op.get_bind()

    for slug, skill in _NODE_SKILL_REASSIGNMENTS:
        bind.execute(
            sa.text(
                "UPDATE resource_nodes SET skill_required = :skill "
                "WHERE slug = :slug"
            ),
            {"skill": skill, "slug": slug},
        )

    for slug, skill, ws in _RECIPE_REASSIGNMENTS:
        bind.execute(
            sa.text(
                "UPDATE recipes SET skill_required = :skill, "
                "workstation_kind = :ws WHERE slug = :slug"
            ),
            {"skill": skill, "ws": ws, "slug": slug},
        )

    # Zero existing hero.skills dicts. Heroes regrind under new keys.
    # Cast to TEXT first because the column is JSON in postgres and
    # JSON literals can't be assigned via UPDATE without a cast on some
    # backends. Using JSON `'{}'` works on both sqlite (TEXT-backed) and
    # postgres (JSON column) without explicit casts.
    bind.execute(sa.text("UPDATE heroes SET skills = '{}'"))


def downgrade() -> None:
    """Best-effort reverse: put the old skill keys back. Hero skills
    cannot be unzeroed — this is a one-way data migration."""
    bind = op.get_bind()

    for slug, _, _ in _RECIPE_REASSIGNMENTS:
        bind.execute(
            sa.text(
                "UPDATE recipes SET skill_required = 'crafting', "
                "workstation_kind = 'forge_workstation' WHERE slug = :slug"
            ),
            {"slug": slug},
        )

    for slug, _ in _NODE_SKILL_REASSIGNMENTS:
        bind.execute(
            sa.text(
                "UPDATE resource_nodes SET skill_required = 'gathering' "
                "WHERE slug = :slug"
            ),
            {"slug": slug},
        )
