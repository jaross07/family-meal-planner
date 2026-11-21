"""add categories column to recipe_cache

Revision ID: 0008_recipe_categories
Revises: 0007_family_events
Create Date: 2026-11-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_recipe_categories"
down_revision = '0007_family_events'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recipe_cache",
        sa.Column("categories", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("recipe_cache", "categories")
