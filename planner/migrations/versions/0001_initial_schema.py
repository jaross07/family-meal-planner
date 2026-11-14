"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-11-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recipe_cache",
        sa.Column("mealie_recipe_id", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("mealie_recipe_id"),
    )

    op.create_table(
        "recipe_meta",
        sa.Column("mealie_recipe_id", sa.String(length=64), nullable=False),
        sa.Column("leftover_yield", sa.Boolean(), nullable=False),
        sa.Column("prep_time_minutes", sa.Integer(), nullable=True),
        sa.Column("leftover_type", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("mealie_recipe_id"),
    )

    op.create_table(
        "recipe_leftover_chains",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parent_recipe_id", sa.String(length=64), nullable=False),
        sa.Column("child_recipe_id", sa.String(length=64), nullable=False),
        sa.Column("max_days_after", sa.Integer(), nullable=False),
        sa.CheckConstraint("max_days_after >= 1 AND max_days_after <= 7", name="ck_max_days_after"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parent_recipe_id", "child_recipe_id", name="uq_leftover_chain"),
    )

    op.create_table(
        "meal_context",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.String(length=32), nullable=False),
        sa.Column("require_leftovers", sa.Boolean(), nullable=False),
        sa.Column("max_prep_time", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "meal_type", name="uq_meal_context_date_type"),
    )

    op.create_table(
        "user_profile",
        sa.Column("mealie_user_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("initials", sa.String(length=4), nullable=False),
        sa.Column("color_code", sa.String(length=7), nullable=False),
        sa.CheckConstraint("color_code ~ '^#[0-9A-Fa-f]{6}$'", name="ck_user_profile_color_hex"),
        sa.PrimaryKeyConstraint("mealie_user_id"),
    )

    op.create_table(
        "recipe_ratings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mealie_recipe_id", sa.String(length=64), nullable=False),
        sa.Column("mealie_user_id", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("score IN (-1, 0, 1)", name="ck_rating_score_values"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mealie_recipe_id", "mealie_user_id", name="uq_recipe_user_rating"),
    )

    op.create_table(
        "meal_attendance",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.String(length=32), nullable=False),
        sa.Column("mealie_user_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.CheckConstraint("status IN ('home', 'out', 'away')", name="ck_attendance_status"),
        sa.CheckConstraint("source IN ('manual')", name="ck_attendance_source"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "meal_type", "mealie_user_id", name="uq_attendance_slot"),
    )

    op.create_table(
        "recurring_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mealie_user_id", sa.String(length=64), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("meal_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_rule_weekday"),
        sa.CheckConstraint("status IN ('home', 'out', 'away')", name="ck_rule_status"),
        sa.CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_rule_dates"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "rule_exceptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["recurring_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "date", name="uq_rule_exception_date"),
    )


def downgrade() -> None:
    op.drop_table("rule_exceptions")
    op.drop_table("recurring_rules")
    op.drop_table("meal_attendance")
    op.drop_table("recipe_ratings")
    op.drop_table("user_profile")
    op.drop_table("meal_context")
    op.drop_table("recipe_leftover_chains")
    op.drop_table("recipe_meta")
    op.drop_table("recipe_cache")
