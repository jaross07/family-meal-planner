"""add categories column to recipe_cache

Revision ID: 0009_recipe_categories
Revises: 0008_day_notes
Create Date: 2026-11-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_recipe_categories"
down_revision = '0008_day_notes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recipe_cache",
        sa.Column("categories", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("recipe_cache", "categories")
