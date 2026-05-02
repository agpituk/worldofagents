"""v1_7_memory_schema_version

Adds memory_schema_version column to heroes so future shape changes to
the JSON memory blob can run forward migrations keyed on the current
version. Defaults to 1 for existing heroes.

Revision ID: 8c4c14e9a7d2
Revises: 06eaaa83af21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8c4c14e9a7d2"
down_revision: Union[str, None] = "06eaaa83af21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "heroes",
        sa.Column(
            "memory_schema_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )


def downgrade() -> None:
    op.drop_column("heroes", "memory_schema_version")
