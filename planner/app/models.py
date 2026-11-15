from datetime import date, datetime
from sqlalchemy import (
    Text,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RecipeCache(Base):
    __tablename__ = "recipe_cache"

    mealie_recipe_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tags: Mapped[list] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), default=list, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RecipeMeta(Base):
    __tablename__ = "recipe_meta"

    mealie_recipe_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    leftover_yield: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    prep_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    leftover_type: Mapped[str | None] = mapped_column(String(100), nullable=True)


class RecipeLeftoverChain(Base):
    __tablename__ = "recipe_leftover_chains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_recipe_id: Mapped[str] = mapped_column(String(64), nullable=False)
    child_recipe_id: Mapped[str] = mapped_column(String(64), nullable=False)
    max_days_after: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    __table_args__ = (
        UniqueConstraint("parent_recipe_id", "child_recipe_id", name="uq_leftover_chain"),
        CheckConstraint("max_days_after >= 1 AND max_days_after <= 7", name="ck_max_days_after"),
    )


class MealContext(Base):
    __tablename__ = "meal_context"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    require_leftovers: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_prep_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_planned: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    eating_leftovers: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    henleys_choice: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("date", "meal_type", name="uq_meal_context_date_type"),
    )


class UserProfile(Base):
    __tablename__ = "user_profile"

    mealie_user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    initials: Mapped[str] = mapped_column(String(4), nullable=False)
    color_code: Mapped[str] = mapped_column(String(7), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    week_start_day: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calendar_view: Mapped[str] = mapped_column(String(16), default="month", nullable=False)
    default_view: Mapped[str] = mapped_column(String(16), default="planner", nullable=False)

    __table_args__ = (
        CheckConstraint("LENGTH(color_code) = 7 AND color_code LIKE '#%'", name="ck_user_profile_color_hex"),
    )


class RecipeRating(Base):
    __tablename__ = "recipe_ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mealie_recipe_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mealie_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("mealie_recipe_id", "mealie_user_id", name="uq_recipe_user_rating"),
        CheckConstraint("score IN (-1, 0, 1)", name="ck_rating_score_values"),
    )


class MealAttendance(Base):
    __tablename__ = "meal_attendance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    mealie_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint("date", "meal_type", "mealie_user_id", name="uq_attendance_slot"),
        CheckConstraint("status IN ('home', 'out', 'away')", name="ck_attendance_status"),
        CheckConstraint("source IN ('manual')", name="ck_attendance_source"),
    )


class RecurringRule(Base):
    __tablename__ = "recurring_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mealie_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    meal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)

    exceptions: Mapped[list["RuleException"]] = relationship(
        "RuleException", back_populates="rule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_rule_weekday"),
        CheckConstraint("status IN ('home', 'out', 'away')", name="ck_rule_status"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="ck_rule_dates"),
    )


class RuleException(Base):
    __tablename__ = "rule_exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recurring_rules.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)

    rule: Mapped["RecurringRule"] = relationship("RecurringRule", back_populates="exceptions")

    __table_args__ = (
        UniqueConstraint("rule_id", "date", name="uq_rule_exception_date"),
    )
