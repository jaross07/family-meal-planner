"""add family_events table for custom annual holidays and birthdays

Revision ID: 0007_family_events
Revises: 0006_recipe_hidden
Create Date: 2026-11-19 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_family_events"
down_revision: Union[str, None] = "0006_recipe_hidden"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "family_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("day", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=False, server_default="🎉"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("family_events")
