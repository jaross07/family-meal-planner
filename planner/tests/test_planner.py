from datetime import date
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("MEALIE_PUBLIC_URL", "https://family-planner-vnic.tailfb3faa.ts.net")
os.environ.setdefault("MEALIE_SERVICE_TOKEN", "test-service-token")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-key-for-unit-tests-12345")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.auth import SESSION_COOKIE_NAME, _serializer  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    MealAttendance,
    MealContext,
    RecipeCache,
    RecipeLeftoverChain,
    RecipeMeta,
    RecipeRating,
    RecurringRule,
    RuleException,
    UserProfile,
)
from app.recommend import generate_recommendations  # noqa: E402
from app.rules import resolve_attendance_range  # noqa: E402

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        db.add_all(
            [
                UserProfile(mealie_user_id="u-justin", display_name="Justin", initials="J", color_code="#3B82F6"),
                UserProfile(mealie_user_id="u-jenesa", display_name="Jenesa", initials="J", color_code="#EC4899"),
                UserProfile(mealie_user_id="u-henley", display_name="Henley", initials="H", color_code="#10B981"),
            ]
        )
        db.commit()
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _set_auth_cookie(client: TestClient, user_id: str, username: str = "justin") -> None:
    token = _serializer.dumps(
        {"user_id": user_id, "username": username, "mealie_token": f"mealie-tok-{user_id}"}
    )
    client.cookies.set(SESSION_COOKIE_NAME, token)


def test_attendance_four_tier_precedence(db_session):
    target = date(2026, 11, 18)  # Wednesday (weekday=2)

    res = resolve_attendance_range(db_session, target, target, meal_types=("dinner",))
    henley = next(r for r in res if r["mealie_user_id"] == "u-henley")
    assert henley["status"] == "home"
    assert henley["source"] == "default"

    rule = RecurringRule(
        mealie_user_id="u-henley",
        weekday=2,
        meal_type="dinner",
        status="out",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 12, 31),
        label="Dance class",
    )
    db_session.add(rule)
    db_session.commit()

    res = resolve_attendance_range(db_session, target, target, meal_types=("dinner",))
    henley = next(r for r in res if r["mealie_user_id"] == "u-henley")
    assert henley["status"] == "out"
    assert henley["source"] == "rule"
    assert henley["label"] == "Dance class"

    db_session.add(RuleException(rule_id=rule.id, date=target))
    db_session.commit()

    res = resolve_attendance_range(db_session, target, target, meal_types=("dinner",))
    henley = next(r for r in res if r["mealie_user_id"] == "u-henley")
    assert henley["status"] == "home"
    assert henley["source"] == "exception"

    db_session.add(
        MealAttendance(
            date=target,
            meal_type="dinner",
            mealie_user_id="u-henley",
            status="away",
            source="manual",
            batch_id="u-justin:b1",
        )
    )
    db_session.commit()

    res = resolve_attendance_range(db_session, target, target, meal_types=("dinner",))
    henley = next(r for r in res if r["mealie_user_id"] == "u-henley")
    assert henley["status"] == "away"
    assert henley["source"] == "manual"


@pytest.mark.anyio
async def test_recommendations_veto_and_edge_cases(db_session):
    target = date(2026, 11, 19)
    db_session.add_all(
        [
            RecipeCache(mealie_recipe_id="r-tacos", slug="tacos", name="Tacos", tags=[], active=True),
            RecipeCache(mealie_recipe_id="r-liver", slug="liver", name="Liver & Onions", tags=[], active=True),
        ]
    )
    db_session.add_all(
        [
            RecipeRating(mealie_recipe_id="r-tacos", mealie_user_id="u-justin", score=1),
            RecipeRating(mealie_recipe_id="r-liver", mealie_user_id="u-henley", score=-1),
        ]
    )
    db_session.commit()

    with patch("app.recommend.mealie_client.get_planned_meals", new=AsyncMock(return_value=[])):
        result = await generate_recommendations(db_session, target, "dinner")

    assert result["reason"] == "ok"
    assert [item["mealie_recipe_id"] for item in result["items"]] == ["r-tacos"]
    assert result["items"][0]["score"] == 0.333

    db_session.add(RecipeRating(mealie_recipe_id="r-tacos", mealie_user_id="u-jenesa", score=-1))
    db_session.commit()

    with patch("app.recommend.mealie_client.get_planned_meals", new=AsyncMock(return_value=[])):
        vetoed_res = await generate_recommendations(db_session, target, "dinner")
    assert vetoed_res["reason"] == "all_vetoed"
    assert vetoed_res["items"] == []

    for uid in ("u-justin", "u-jenesa", "u-henley"):
        db_session.add(
            MealAttendance(date=target, meal_type="dinner", mealie_user_id=uid, status="away", source="manual")
        )
    db_session.commit()

    no_diners_res = await generate_recommendations(db_session, target, "dinner")
    assert no_diners_res["reason"] == "no_diners"


@pytest.mark.anyio
async def test_recommendations_fast_cook_lunch_leftovers_and_chains(db_session):
    tuesday = date(2026, 11, 17)
    thursday = date(2026, 11, 19)

    db_session.add_all(
        [
            RecipeCache(mealie_recipe_id="r-mash", slug="mash", name="Mashed Potatoes", tags=[], active=True),
            RecipeCache(mealie_recipe_id="r-shep", slug="shep", name="Shepherd's Pie", tags=[], active=True),
            RecipeCache(mealie_recipe_id="r-ques", slug="ques", name="Quick Quesadillas", tags=[], active=True),
        ]
    )
    db_session.add_all(
        [
            RecipeMeta(
                mealie_recipe_id="r-mash",
                leftover_yield=True,
                prep_time_minutes=25,
                leftover_type="Mashed Potatoes",
            ),
            RecipeMeta(mealie_recipe_id="r-shep", leftover_yield=True, prep_time_minutes=50),
            RecipeMeta(mealie_recipe_id="r-ques", leftover_yield=False, prep_time_minutes=15),
        ]
    )
    db_session.add(
        RecipeLeftoverChain(parent_recipe_id="r-mash", child_recipe_id="r-shep", max_days_after=3)
    )
    db_session.commit()

    mock_plans = [{"date": tuesday, "entry_type": "dinner", "recipe_id": "r-mash", "recipe_name": "Mashed Potatoes"}]
    with patch("app.recommend.mealie_client.get_planned_meals", new=AsyncMock(return_value=mock_plans)):
        chain_res = await generate_recommendations(db_session, thursday, "dinner")

    top = chain_res["items"][0]
    assert top["mealie_recipe_id"] == "r-shep"
    assert top["score"] == 1.5
    assert top["leftover_badge"] == "Uses leftover Mashed Potatoes from Tuesday"

    db_session.add(MealContext(date=thursday, meal_type="dinner", require_leftovers=False, max_prep_time=20))
    db_session.commit()

    with patch("app.recommend.mealie_client.get_planned_meals", new=AsyncMock(return_value=[])):
        fast_res = await generate_recommendations(db_session, thursday, "dinner")
    assert [i["mealie_recipe_id"] for i in fast_res["items"]] == ["r-ques"]

    ctx = db_session.query(MealContext).filter_by(date=thursday, meal_type="dinner").first()
    ctx.max_prep_time = None
    ctx.require_leftovers = True
    db_session.commit()

    with patch("app.recommend.mealie_client.get_planned_meals", new=AsyncMock(return_value=[])):
        extra_res = await generate_recommendations(db_session, thursday, "dinner")
    ids = {i["mealie_recipe_id"] for i in extra_res["items"]}
    assert ids == {"r-mash", "r-shep"}


def test_authorization_isolates_user_ratings_and_profile(client, db_session):
    assert client.get("/api/profile").status_code == 401

    _set_auth_cookie(client, "u-justin", "justin")
    resp = client.put("/api/ratings/r-tacos", json={"score": 1})
    assert resp.status_code == 200
    assert resp.json()["mealie_user_id"] == "u-justin"

    _set_auth_cookie(client, "u-jenesa", "jenesa")
    jenesa_resp = client.get("/api/ratings/r-tacos")
    assert jenesa_resp.status_code == 200
    assert jenesa_resp.json()["score"] == 0

    _set_auth_cookie(client, "u-justin", "justin")
    prof_resp = client.put("/api/profile", json={"color_code": "#1D4ED8"})
    assert prof_resp.status_code == 200
    assert db_session.get(UserProfile, "u-justin").color_code == "#1D4ED8"
    assert db_session.get(UserProfile, "u-jenesa").color_code == "#EC4899"
