"""v2_2_sandbox_protection

Phase 8 of the build-diversity roadmap: a 50-tick training zone where
new heroes can't be permakilled. Adds `protected_until_tick` to heroes
(0 = no protection / legacy behaviour). The sandbox zone itself is
seeded by `seed_zones` on startup so this migration only touches
schema.

Revision ID: b5f2c1e40001
Revises: a4e8b1f30001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b5f2c1e40001"
down_revision: Union[str, None] = "a4e8b1f30001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "heroes",
        sa.Column(
            "protected_until_tick",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("heroes", "protected_until_tick")
