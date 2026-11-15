"""add eating_leftovers and henleys_choice to meal_context

Revision ID: 0004_day_modes
Revises: 0003_prefs_and_plan
Create Date: 2026-11-15 08:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_day_modes"
down_revision: Union[str, None] = "0003_prefs_and_plan"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "meal_context",
        sa.Column("eating_leftovers", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "meal_context",
        sa.Column("henleys_choice", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("meal_context", "henleys_choice")
    op.drop_column("meal_context", "eating_leftovers")
