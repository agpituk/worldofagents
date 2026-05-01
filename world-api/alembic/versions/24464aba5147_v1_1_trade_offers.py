"""v1_1 trade offers (empty placeholder)

Revision ID: 24464aba5147
Revises: 49814a487a1b
Create Date: 2026-04-30 07:36:34.428134

This was originally generated empty (model edit hadn't reloaded). Kept as
a no-op so alembic_version stays consistent; the real columns ship in the
next revision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '24464aba5147'
down_revision: Union[str, None] = '49814a487a1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
