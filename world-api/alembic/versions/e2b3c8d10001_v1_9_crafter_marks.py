"""v1_9_crafter_marks

Phase 5 of the build-diversity roadmap: stamp the crafter on every
crafted item. `crafted_by` holds the hero's UUID at craft time;
`crafted_by_name` is the denormalised hero name so item tooltips and
spectator UIs don't have to join Hero on every render. Both nullable —
seeded items, mob drops, and pre-migration items have NULL.

Revision ID: e2b3c8d10001
Revises: d1a7f4c0b001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "e2b3c8d10001"
down_revision: Union[str, None] = "d1a7f4c0b001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("crafted_by", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "items",
        sa.Column("crafted_by_name", sa.String(length=120), nullable=True),
    )
    op.create_index("ix_items_crafted_by", "items", ["crafted_by"])


def downgrade() -> None:
    op.drop_index("ix_items_crafted_by", table_name="items")
    op.drop_column("items", "crafted_by_name")
    op.drop_column("items", "crafted_by")
