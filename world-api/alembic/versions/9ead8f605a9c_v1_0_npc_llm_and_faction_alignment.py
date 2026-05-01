"""v1_0 npc llm and faction alignment

Revision ID: 9ead8f605a9c
Revises: 71391ad69298
Create Date: 2026-04-30 07:11:33.801881

This was originally generated empty (model edit hadn't landed). Kept as
a no-op so alembic_version remains consistent; the real columns ship in
the next revision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9ead8f605a9c'
down_revision: Union[str, None] = '71391ad69298'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
