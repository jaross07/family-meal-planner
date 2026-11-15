"""add hidden column to recipe_cache

Revision ID: 0006_recipe_hidden
Revises: 0005_notes_view
Create Date: 2026-11-15 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_recipe_hidden"
down_revision: Union[str, None] = "0005_notes_view"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recipe_cache",
        sa.Column("hidden", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("recipe_cache", "hidden")
