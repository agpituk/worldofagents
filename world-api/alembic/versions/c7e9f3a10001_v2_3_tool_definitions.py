"""v2_3_tool_definitions — agent-tools showcase tables

Phase 6 of the agent-tools rollout. Adds three tables that turn
user-defined tools into shareable artifacts:

  • tool_definitions  — content-addressed registry (sha256 of canonical
                         YAML). One row per unique tool body.
  • hero_tools        — which heroes currently expose which tool_id.
  • tool_copies       — record of every "Copy this tool" UX click;
                         feeds the most-copied leaderboard.

Revision ID: c7e9f3a10001
Revises: b5f2c1e40001
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7e9f3a10001"
down_revision: Union[str, None] = "b5f2c1e40001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tool_definitions",
        sa.Column("tool_id", sa.String(length=64), primary_key=True),
        sa.Column("canonical_yaml", sa.Text, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False, index=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("parent_tool_id", sa.String(length=64), nullable=True, index=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("first_seen_hero", sa.String(length=120), nullable=False),
    )

    op.create_table(
        "hero_tools",
        sa.Column("hero_id", sa.UUID(), nullable=False),
        sa.Column("tool_id", sa.String(length=64), nullable=False),
        sa.Column("added_tick", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("hero_id", "tool_id"),
    )
    op.create_index("ix_hero_tools_tool_id", "hero_tools", ["tool_id"])

    op.create_table(
        "tool_copies",
        sa.Column("copy_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source_tool_id", sa.String(length=64), nullable=False, index=True),
        sa.Column("copied_by_hero", sa.UUID(), nullable=False, index=True),
        sa.Column("copied_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("tool_copies")
    op.drop_index("ix_hero_tools_tool_id", table_name="hero_tools")
    op.drop_table("hero_tools")
    op.drop_table("tool_definitions")
