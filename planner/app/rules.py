from datetime import date, timedelta
from sqlalchemy.orm import Session

from app.models import MealAttendance, RecurringRule, RuleException, UserProfile

MEAL_TYPES = ("breakfast", "lunch", "dinner")


def resolve_attendance_range(
    db: Session,
    start_date: date,
    end_date: date,
    meal_types: tuple[str, ...] = MEAL_TYPES,
) -> list[dict]:
    """
    Calculate effective attendance for every household user across [start_date, end_date].
    Precedence per (date, meal_type, user):
      1. Manual entry in meal_attendance
      2. Rule exception (cancels matching recurring rule -> falls through to default 'home')
      3. Active recurring rule matching weekday & meal_type
      4. Default status: 'home'
    """
    if end_date < start_date:
        raise ValueError("end_date must be on or after start_date")
    if (end_date - start_date).days > 62:
        raise ValueError("Date range cannot exceed 62 days")

    profiles = db.query(UserProfile).order_by(UserProfile.display_name).all()
    if not profiles:
        return []

    manual_rows = (
        db.query(MealAttendance)
        .filter(
            MealAttendance.date >= start_date,
            MealAttendance.date <= end_date,
            MealAttendance.meal_type.in_(meal_types),
        )
        .all()
    )
    manual_map: dict[tuple[date, str, str], MealAttendance] = {
        (row.date, row.meal_type, row.mealie_user_id): row for row in manual_rows
    }

    rules = (
        db.query(RecurringRule)
        .filter(
            RecurringRule.start_date <= end_date,
            (RecurringRule.end_date.is_(None)) | (RecurringRule.end_date >= start_date),
            RecurringRule.meal_type.in_(meal_types),
        )
        .all()
    )

    rule_ids = [r.id for r in rules]
    exception_set: set[tuple[int, date]] = set()
    if rule_ids:
        exceptions = (
            db.query(RuleException)
            .filter(
                RuleException.rule_id.in_(rule_ids),
                RuleException.date >= start_date,
                RuleException.date <= end_date,
            )
            .all()
        )
        exception_set = {(ex.rule_id, ex.date) for ex in exceptions}

    # Index rules by (user_id, weekday, meal_type)
    rule_index: dict[tuple[str, int, str], list[RecurringRule]] = {}
    for rule in rules:
        rule_index.setdefault((rule.mealie_user_id, rule.weekday, rule.meal_type), []).append(rule)

    results: list[dict] = []
    current = start_date
    while current <= end_date:
        weekday = current.weekday()  # Monday=0 .. Sunday=6
        for meal_type in meal_types:
            for profile in profiles:
                uid = profile.mealie_user_id

                # 1. Manual override
                manual = manual_map.get((current, meal_type, uid))
                if manual is not None:
                    results.append(
                        {
                            "date": current.isoformat(),
                            "meal_type": meal_type,
                            "mealie_user_id": uid,
                            "display_name": profile.display_name,
                            "initials": profile.initials,
                            "color_code": profile.color_code,
                            "status": manual.status,
                            "source": "manual",
                            "label": None,
                            "rule_id": None,
                        }
                    )
                    continue

                # 2 & 3. Recurring rule check with exception handling
                matched_rule: RecurringRule | None = None
                canceled_by_exception = False
                for candidate in rule_index.get((uid, weekday, meal_type), []):
                    if candidate.start_date <= current and (
                        candidate.end_date is None or candidate.end_date >= current
                    ):
                        if (candidate.id, current) in exception_set:
                            canceled_by_exception = True
                        else:
                            matched_rule = candidate
                            break

                if matched_rule is not None:
                    results.append(
                        {
                            "date": current.isoformat(),
                            "meal_type": meal_type,
                            "mealie_user_id": uid,
                            "display_name": profile.display_name,
                            "initials": profile.initials,
                            "color_code": profile.color_code,
                            "status": matched_rule.status,
                            "source": "rule",
                            "label": matched_rule.label,
                            "rule_id": matched_rule.id,
                        }
                    )
                else:
                    # 4. Default status ('home'), or reverted to 'home' via rule exception
                    results.append(
                        {
                            "date": current.isoformat(),
                            "meal_type": meal_type,
                            "mealie_user_id": uid,
                            "display_name": profile.display_name,
                            "initials": profile.initials,
                            "color_code": profile.color_code,
                            "status": "home",
                            "source": "exception" if canceled_by_exception else "default",
                            "label": None,
                            "rule_id": None,
                        }
                    )

        current += timedelta(days=1)

    return results


def get_diners_for_meal(db: Session, target_date: date, meal_type: str) -> list[dict]:
    """Return profiles of everyone whose status is 'home' for the requested date & meal."""
    entries = resolve_attendance_range(db, target_date, target_date, meal_types=(meal_type,))
    return [entry for entry in entries if entry["status"] == "home"]
