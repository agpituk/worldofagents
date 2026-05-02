"""v2_1_statuses_and_spell_effects

Phase 2 of the build-diversity roadmap: spell variety needs more than
damage and heal. Adds a `statuses` table for durable effects (bless,
stoneskin, slow, blind, bleed, regrowth, …) plus two new columns on
`spells` — `effect_kind` and `payload` — so a single Spell row can
declare which handler runs at cast time and what kind-specific data
that handler reads.

Revision ID: a4e8b1f30001
Revises: f3c4d9e20001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "a4e8b1f30001"
down_revision: Union[str, None] = "f3c4d9e20001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "statuses",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("hero_id", UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=48), nullable=False),
        sa.Column("payload", JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("applied_at_tick", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at_tick", sa.Integer(), nullable=False),
        sa.Column("source_hero_id", UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_statuses_hero_id", "statuses", ["hero_id"])
    op.create_index("ix_statuses_slug", "statuses", ["slug"])
    op.create_index("ix_statuses_expires_at_tick", "statuses", ["expires_at_tick"])

    op.add_column(
        "spells",
        sa.Column(
            "effect_kind",
            sa.String(length=32),
            nullable=False,
            server_default="damage_or_heal",
        ),
    )
    op.add_column(
        "spells",
        sa.Column(
            "payload",
            JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("spells", "payload")
    op.drop_column("spells", "effect_kind")
    op.drop_index("ix_statuses_expires_at_tick", table_name="statuses")
    op.drop_index("ix_statuses_slug", table_name="statuses")
    op.drop_index("ix_statuses_hero_id", table_name="statuses")
    op.drop_table("statuses")
