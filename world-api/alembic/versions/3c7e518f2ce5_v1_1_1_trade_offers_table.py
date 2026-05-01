"""v1_1_1 trade offers table (empty placeholder, real shape in next migration)"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '3c7e518f2ce5'
down_revision: Union[str, None] = '24464aba5147'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass
