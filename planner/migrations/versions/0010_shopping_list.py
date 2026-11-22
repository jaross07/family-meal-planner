"""add shopping list and item preferences tables

Revision ID: 0009_shopping_list
Revises: 0009_recipe_categories
Create Date: 2026-11-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_shopping_list"
down_revision = "0009_recipe_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "item_preferences",
        sa.Column("normalized_name", sa.String(length=255), primary_key=True),
        sa.Column("default_store", sa.String(length=64), nullable=False, server_default="WinCo"),
        sa.Column("default_category", sa.String(length=64), nullable=False, server_default="Pantry"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "shopping_list_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False, index=True),
        sa.Column("quantity", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False, server_default="Pantry"),
        sa.Column("store", sa.String(length=64), nullable=False, server_default="WinCo"),
        sa.Column("checked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_recipes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("shopping_list_items")
    op.drop_table("item_preferences")
