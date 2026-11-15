"""add meal is_planned flag and user calendar preferences

Revision ID: 0003_prefs_and_plan
Revises: 0002_user_active
Create Date: 2026-11-15 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_prefs_and_plan"
down_revision: Union[str, None] = "0002_user_active"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "meal_context",
        sa.Column("is_planned", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "user_profile",
        sa.Column("week_start_day", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "user_profile",
        sa.Column("calendar_view", sa.String(length=16), server_default=sa.text("'month'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("user_profile", "calendar_view")
    op.drop_column("user_profile", "week_start_day")
    op.drop_column("meal_context", "is_planned")
