"""v2_0_contracts

Phase 4 of the build-diversity roadmap: replaces the single-purpose
`bounties` table with a unified `contracts` table that supports six
kinds (bounty, assassination, defense, delivery, escort, caravan).
Existing bounty rows are copied across as `kind='bounty'` so claimed
prizes and historical hits keep their place on the board, then the old
table is dropped.

Revision ID: f3c4d9e20001
Revises: e2b3c8d10001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "f3c4d9e20001"
down_revision: Union[str, None] = "e2b3c8d10001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("poster_hero_id", UUID(as_uuid=True), nullable=True),
        sa.Column("poster_name", sa.String(length=120), nullable=False, server_default="anonymous"),
        sa.Column("target_hero_id", UUID(as_uuid=True), nullable=True),
        sa.Column("target_ref", sa.String(length=120), nullable=True),
        sa.Column("reward_gold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("zone_scope", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=280), nullable=False, server_default=""),
        sa.Column("terms", JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at_tick", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at_tick", sa.Integer(), nullable=True),
        sa.Column("claimed_by_hero_id", UUID(as_uuid=True), nullable=True),
        sa.Column("claimed_at_tick", sa.Integer(), nullable=True),
        sa.Column("fulfilled_at_tick", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contracts_kind", "contracts", ["kind"])
    op.create_index("ix_contracts_status", "contracts", ["status"])
    op.create_index("ix_contracts_zone_scope", "contracts", ["zone_scope"])
    op.create_index("ix_contracts_poster_hero_id", "contracts", ["poster_hero_id"])
    op.create_index("ix_contracts_target_hero_id", "contracts", ["target_hero_id"])
    op.create_index("ix_contracts_claimed_by_hero_id", "contracts", ["claimed_by_hero_id"])

    # Copy existing bounties across as kind='bounty'. The status column
    # had values open|claimed|expired which all carry forward unchanged
    # (open and claimed are unchanged; expired stays expired). Old code
    # used `gold`; new column is `reward_gold`. target_name → target_ref.
    op.execute(
        """
        INSERT INTO contracts (
            id, kind, poster_hero_id, poster_name,
            target_hero_id, target_ref,
            reward_gold, status, reason, terms,
            created_at_tick, claimed_by_hero_id, claimed_at_tick,
            fulfilled_at_tick
        )
        SELECT
            id, 'bounty', poster_hero_id, poster_name,
            target_hero_id, target_name,
            gold,
            CASE WHEN status = 'claimed' THEN 'fulfilled' ELSE status END,
            reason, '{}'::jsonb,
            created_at_tick, claimed_by_hero_id, claimed_at_tick,
            CASE WHEN status = 'claimed' THEN claimed_at_tick ELSE NULL END
        FROM bounties
        """
    )
    op.drop_table("bounties")


def downgrade() -> None:
    """One-way migration. The bounties table is recreated empty so the
    schema rolls back cleanly, but historical contracts are not copied
    back — they live as Contract rows from now on."""
    op.create_table(
        "bounties",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_hero_id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_name", sa.String(length=120), nullable=False),
        sa.Column("poster_hero_id", UUID(as_uuid=True), nullable=True),
        sa.Column("poster_name", sa.String(length=120), nullable=False, server_default="anonymous"),
        sa.Column("reason", sa.String(length=280), nullable=False, server_default=""),
        sa.Column("gold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at_tick", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claimed_by_hero_id", UUID(as_uuid=True), nullable=True),
        sa.Column("claimed_at_tick", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bounties_target_hero_id", "bounties", ["target_hero_id"])
    op.create_index("ix_bounties_poster_hero_id", "bounties", ["poster_hero_id"])

    op.drop_index("ix_contracts_claimed_by_hero_id", table_name="contracts")
    op.drop_index("ix_contracts_target_hero_id", table_name="contracts")
    op.drop_index("ix_contracts_poster_hero_id", table_name="contracts")
    op.drop_index("ix_contracts_zone_scope", table_name="contracts")
    op.drop_index("ix_contracts_status", table_name="contracts")
    op.drop_index("ix_contracts_kind", table_name="contracts")
    op.drop_table("contracts")
