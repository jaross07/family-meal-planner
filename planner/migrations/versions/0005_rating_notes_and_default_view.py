"""add note to recipe_ratings and default_view to user_profile

Revision ID: 0005_notes_view
Revises: 0004_day_modes
Create Date: 2026-11-15 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_notes_view"
down_revision: Union[str, None] = "0004_day_modes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recipe_ratings",
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_profile",
        sa.Column("default_view", sa.String(16), server_default="planner", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("user_profile", "default_view")
    op.drop_column("recipe_ratings", "note")
