import asyncio
from contextlib import asynccontextmanager
from datetime import date, timedelta
import logging
from pathlib import Path
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import (
    clear_session_cookie,
    create_session_cookie,
    ensure_user_profile,
    get_current_session,
    get_current_user_id,
)
from app.database import SessionLocal, get_db
from app.mealie_client import MealieAuthError, MealieUnavailableError, mealie_client
from app.models import (
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
from app.recommend import generate_recommendations
from app.rules import resolve_attendance_range
from app.sync import sync_recipes_from_mealie

logger = logging.getLogger("planner")
SYNC_INTERVAL_SECONDS = 15 * 60


async def _periodic_sync_loop() -> None:
    while True:
        try:
            db = SessionLocal()
            try:
                await sync_recipes_from_mealie(db)
            finally:
                db.close()
        except Exception as exc:
            logger.warning("Background recipe sync failed: %s", exc)
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_periodic_sync_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Family Meal Planner", version="0.1.0", lifespan=lifespan)


# --- Pydantic Schemas ---

class LoginRequest(BaseModel):
    username: str
    password: str


class RatingUpdate(BaseModel):
    score: int = Field(..., ge=-1, le=1)


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    initials: str | None = Field(default=None, min_length=1, max_length=4)
    color_code: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    active: bool | None = None
    week_start_day: int | None = Field(default=None, ge=0, le=1)
    calendar_view: str | None = Field(default=None, pattern=r"^(month|2week|1week)$")


class AttendancePutRequest(BaseModel):
    start_date: date
    end_date: date | None = None
    meal_types: list[str] = Field(default_factory=lambda: ["dinner"])
    mealie_user_id: str
    status: str = Field(..., pattern=r"^(home|out|away)$")


class RuleCreateRequest(BaseModel):
    mealie_user_id: str
    weekday: int = Field(..., ge=0, le=6)
    meal_type: str = Field(..., pattern=r"^(breakfast|lunch|dinner)$")
    status: str = Field(..., pattern=r"^(home|out|away)$")
    start_date: date
    end_date: date | None = None
    label: str = Field(..., min_length=1, max_length=120)


class RuleUpdateRequest(BaseModel):
    weekday: int | None = Field(default=None, ge=0, le=6)
    meal_type: str | None = Field(default=None, pattern=r"^(breakfast|lunch|dinner)$")
    status: str | None = Field(default=None, pattern=r"^(home|out|away)$")
    start_date: date | None = None
    end_date: date | None = None
    label: str | None = Field(default=None, min_length=1, max_length=120)


class RuleExceptionRequest(BaseModel):
    date: date


class ContextUpdateRequest(BaseModel):
    date: date
    meal_type: str = Field(default="dinner", pattern=r"^(breakfast|lunch|dinner)$")
    require_leftovers: bool = False
    max_prep_time: int | None = Field(default=None, ge=5, le=480)
    is_planned: bool = True


class RecipeMetaUpdateRequest(BaseModel):
    leftover_yield: bool = False
    prep_time_minutes: int | None = Field(default=None, ge=1, le=1440)
    leftover_type: str | None = Field(default=None, max_length=100)


class LeftoverChainCreateRequest(BaseModel):
    parent_recipe_id: str
    child_recipe_id: str
    max_days_after: int = Field(default=3, ge=1, le=7)


class PlanMealRequest(BaseModel):
    date: date
    meal_type: str = Field(default="dinner", pattern=r"^(breakfast|lunch|dinner)$")
    mealie_recipe_id: str


# --- Health & Auth ---

@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/auth/login")
async def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    try:
        user_info = await mealie_client.login_and_get_user(payload.username, payload.password)
    except MealieAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except MealieUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    profile = ensure_user_profile(
        db=db,
        user_id=user_info["user_id"],
        username=user_info["username"],
        full_name=user_info["full_name"],
    )

    session_data = {
        "user_id": user_info["user_id"],
        "username": user_info["username"],
        "mealie_token": user_info["access_token"],
    }
    create_session_cookie(response, session_data)

    return {
        "user_id": profile.mealie_user_id,
        "display_name": profile.display_name,
        "initials": profile.initials,
        "color_code": profile.color_code,
    }


@app.post("/api/auth/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"status": "logged_out"}


# --- Profiles ---

@app.get("/api/profile")
def get_my_profile(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    profile = db.get(UserProfile, user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    all_profiles = db.query(UserProfile).order_by(UserProfile.display_name).all()
    return {
        "current_user": {
            "mealie_user_id": profile.mealie_user_id,
            "display_name": profile.display_name,
            "initials": profile.initials,
            "color_code": profile.color_code,
            "week_start_day": profile.week_start_day,
            "calendar_view": profile.calendar_view,
        },
        "household": [
            {
                "mealie_user_id": p.mealie_user_id,
                "display_name": p.display_name,
                "initials": p.initials,
                "color_code": p.color_code,
                "active": p.active,
            }
            for p in all_profiles
        ],
    }


@app.put("/api/profile")
def update_my_profile(
    payload: ProfileUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    profile = db.get(UserProfile, user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    if payload.display_name is not None:
        profile.display_name = payload.display_name.strip()
    if payload.initials is not None:
        profile.initials = payload.initials.strip().upper()
    if payload.color_code is not None:
        profile.color_code = payload.color_code.upper()
    if payload.week_start_day is not None:
        profile.week_start_day = payload.week_start_day
    if payload.calendar_view is not None:
        profile.calendar_view = payload.calendar_view

    db.commit()
    db.refresh(profile)
    return {
        "mealie_user_id": profile.mealie_user_id,
        "display_name": profile.display_name,
        "initials": profile.initials,
        "color_code": profile.color_code,
        "week_start_day": profile.week_start_day,
        "calendar_view": profile.calendar_view,
    }




@app.put("/api/household/{member_id}")
def update_household_member(
    member_id: str,
    payload: ProfileUpdate,
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    member = db.get(UserProfile, member_id)
    if not member:
        raise HTTPException(status_code=404, detail="Household member not found")

    if payload.display_name is not None:
        member.display_name = payload.display_name.strip()
    if payload.initials is not None:
        member.initials = payload.initials.strip().upper()
    if payload.color_code is not None:
        member.color_code = payload.color_code.upper()
    if payload.active is not None:
        member.active = payload.active

    db.commit()
    db.refresh(member)
    return {
        "mealie_user_id": member.mealie_user_id,
        "display_name": member.display_name,
        "initials": member.initials,
        "color_code": member.color_code,
        "active": member.active,
    }

# --- Ratings ---

@app.get("/api/ratings/{recipe_id}")
def get_recipe_rating(
    recipe_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    row = (
        db.query(RecipeRating)
        .filter(
            RecipeRating.mealie_recipe_id == recipe_id,
            RecipeRating.mealie_user_id == user_id,
        )
        .first()
    )
    return {
        "mealie_recipe_id": recipe_id,
        "mealie_user_id": user_id,
        "score": row.score if row else 0,
    }


@app.put("/api/ratings/{recipe_id}")
def upsert_recipe_rating(
    recipe_id: str,
    payload: RatingUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    row = (
        db.query(RecipeRating)
        .filter(
            RecipeRating.mealie_recipe_id == recipe_id,
            RecipeRating.mealie_user_id == user_id,
        )
        .first()
    )
    if row is None:
        row = RecipeRating(
            mealie_recipe_id=recipe_id,
            mealie_user_id=user_id,
            score=payload.score,
        )
        db.add(row)
    else:
        row.score = payload.score

    db.commit()
    return {
        "mealie_recipe_id": recipe_id,
        "mealie_user_id": user_id,
        "score": row.score,
    }


# --- Attendance & Undo ---

@app.get("/api/attendance")
def get_attendance(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    try:
        items = resolve_attendance_range(db, from_date, to_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"from": from_date.isoformat(), "to": to_date.isoformat(), "items": items}


@app.put("/api/attendance")
def put_attendance(
    payload: AttendancePutRequest,
    session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    end = payload.end_date or payload.start_date
    if end < payload.start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    if (end - payload.start_date).days > 62:
        raise HTTPException(status_code=400, detail="Range cannot exceed 62 days")

    # Tag batch_id with acting user's ID so undo reverts only the current user's last batch
    batch_id = f"{session['user_id']}:{uuid.uuid4().hex}"
    current = payload.start_date
    updated = 0

    while current <= end:
        for mtype in payload.meal_types:
            existing = (
                db.query(MealAttendance)
                .filter(
                    MealAttendance.date == current,
                    MealAttendance.meal_type == mtype,
                    MealAttendance.mealie_user_id == payload.mealie_user_id,
                )
                .first()
            )
            if existing:
                existing.status = payload.status
                existing.source = "manual"
                existing.batch_id = batch_id
            else:
                db.add(
                    MealAttendance(
                        date=current,
                        meal_type=mtype,
                        mealie_user_id=payload.mealie_user_id,
                        status=payload.status,
                        source="manual",
                        batch_id=batch_id,
                    )
                )
            updated += 1
        current += timedelta(days=1)

    db.commit()
    return {"batch_id": batch_id, "updated": updated}


@app.post("/api/attendance/undo")
def undo_last_attendance_batch(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    prefix = f"{user_id}:"
    latest = (
        db.query(MealAttendance)
        .filter(MealAttendance.batch_id.like(f"{prefix}%"))
        .order_by(MealAttendance.id.desc())
        .first()
    )
    if not latest or not latest.batch_id:
        return {"reverted": 0, "batch_id": None}

    target_batch = latest.batch_id
    deleted = (
        db.query(MealAttendance)
        .filter(MealAttendance.batch_id == target_batch)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"reverted": deleted, "batch_id": target_batch}


# --- Recurring Rules & Exceptions ---

@app.get("/api/rules")
def list_rules(_: dict = Depends(get_current_session), db: Session = Depends(get_db)):
    rules = db.query(RecurringRule).order_by(RecurringRule.weekday, RecurringRule.id).all()
    return [
        {
            "id": r.id,
            "mealie_user_id": r.mealie_user_id,
            "weekday": r.weekday,
            "meal_type": r.meal_type,
            "status": r.status,
            "start_date": r.start_date.isoformat(),
            "end_date": r.end_date.isoformat() if r.end_date else None,
            "label": r.label,
            "exceptions": [e.date.isoformat() for e in r.exceptions],
        }
        for r in rules
    ]


@app.post("/api/rules", status_code=201)
def create_rule(
    payload: RuleCreateRequest,
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    if payload.end_date and payload.end_date < payload.start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")

    rule = RecurringRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"id": rule.id, "label": rule.label}


@app.put("/api/rules/{rule_id}")
def update_rule(
    rule_id: int,
    payload: RuleUpdateRequest,
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    rule = db.get(RecurringRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, val in updates.items():
        setattr(rule, field, val)

    if rule.end_date and rule.end_date < rule.start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")

    db.commit()
    return {"id": rule.id, "status": "updated"}


@app.delete("/api/rules/{rule_id}")
def delete_rule(
    rule_id: int,
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    rule = db.get(RecurringRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"id": rule_id, "status": "deleted"}


@app.post("/api/rules/{rule_id}/exceptions", status_code=201)
def add_rule_exception(
    rule_id: int,
    payload: RuleExceptionRequest,
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    rule = db.get(RecurringRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    existing = (
        db.query(RuleException)
        .filter(RuleException.rule_id == rule_id, RuleException.date == payload.date)
        .first()
    )
    if not existing:
        db.add(RuleException(rule_id=rule_id, date=payload.date))
        db.commit()
    return {"rule_id": rule_id, "date": payload.date.isoformat()}


# --- Day Context, Recipe Meta & Leftover Chains ---

@app.get("/api/contexts")
def get_meal_contexts_range(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(MealContext)
        .filter(MealContext.date >= from_date, MealContext.date <= to_date)
        .all()
    )
    return [
        {
            "date": r.date.isoformat(),
            "meal_type": r.meal_type,
            "require_leftovers": r.require_leftovers,
            "max_prep_time": r.max_prep_time,
            "is_planned": r.is_planned,
        }
        for r in rows
    ]


@app.get("/api/context")
def get_meal_context(
    target_date: date = Query(..., alias="date"),
    meal_type: str = Query(default="dinner"),
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    ctx = (
        db.query(MealContext)
        .filter(MealContext.date == target_date, MealContext.meal_type == meal_type)
        .first()
    )
    default_planned = (meal_type == "dinner")
    return {
        "date": target_date.isoformat(),
        "meal_type": meal_type,
        "require_leftovers": ctx.require_leftovers if ctx else False,
        "max_prep_time": ctx.max_prep_time if ctx else None,
        "is_planned": ctx.is_planned if ctx else default_planned,
    }


@app.put("/api/context")
def put_meal_context(
    payload: ContextUpdateRequest,
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    ctx = (
        db.query(MealContext)
        .filter(MealContext.date == payload.date, MealContext.meal_type == payload.meal_type)
        .first()
    )
    if ctx is None:
        ctx = MealContext(
            date=payload.date,
            meal_type=payload.meal_type,
            require_leftovers=payload.require_leftovers,
            max_prep_time=payload.max_prep_time,
            is_planned=payload.is_planned,
        )
        db.add(ctx)
    else:
        ctx.require_leftovers = payload.require_leftovers
        ctx.max_prep_time = payload.max_prep_time
        ctx.is_planned = payload.is_planned

    db.commit()
    return {
        "date": ctx.date.isoformat(),
        "meal_type": ctx.meal_type,
        "require_leftovers": ctx.require_leftovers,
        "max_prep_time": ctx.max_prep_time,
        "is_planned": ctx.is_planned,
    }


@app.get("/api/recipe-meta/{recipe_id}")
def get_recipe_meta(
    recipe_id: str,
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    meta = db.get(RecipeMeta, recipe_id)
    return {
        "mealie_recipe_id": recipe_id,
        "leftover_yield": meta.leftover_yield if meta else False,
        "prep_time_minutes": meta.prep_time_minutes if meta else None,
        "leftover_type": meta.leftover_type if meta else None,
    }


@app.put("/api/recipe-meta/{recipe_id}")
def put_recipe_meta(
    recipe_id: str,
    payload: RecipeMetaUpdateRequest,
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    meta = db.get(RecipeMeta, recipe_id)
    if meta is None:
        meta = RecipeMeta(mealie_recipe_id=recipe_id, **payload.model_dump())
        db.add(meta)
    else:
        meta.leftover_yield = payload.leftover_yield
        meta.prep_time_minutes = payload.prep_time_minutes
        meta.leftover_type = payload.leftover_type

    db.commit()
    return {
        "mealie_recipe_id": recipe_id,
        "leftover_yield": meta.leftover_yield,
        "prep_time_minutes": meta.prep_time_minutes,
        "leftover_type": meta.leftover_type,
    }


@app.get("/api/leftover-chains")
def list_leftover_chains(_: dict = Depends(get_current_session), db: Session = Depends(get_db)):
    chains = db.query(RecipeLeftoverChain).all()
    return [
        {
            "id": c.id,
            "parent_recipe_id": c.parent_recipe_id,
            "child_recipe_id": c.child_recipe_id,
            "max_days_after": c.max_days_after,
        }
        for c in chains
    ]


@app.post("/api/leftover-chains", status_code=201)
def create_leftover_chain(
    payload: LeftoverChainCreateRequest,
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    existing = (
        db.query(RecipeLeftoverChain)
        .filter(
            RecipeLeftoverChain.parent_recipe_id == payload.parent_recipe_id,
            RecipeLeftoverChain.child_recipe_id == payload.child_recipe_id,
        )
        .first()
    )
    if existing:
        existing.max_days_after = payload.max_days_after
        db.commit()
        return {"id": existing.id, "max_days_after": existing.max_days_after}

    chain = RecipeLeftoverChain(**payload.model_dump())
    db.add(chain)
    db.commit()
    db.refresh(chain)
    return {"id": chain.id, "max_days_after": chain.max_days_after}


# --- Recommendations, Mealie Write-Back & Sync ---

@app.get("/api/recommendations")
async def get_recommendations(
    target_date: date = Query(..., alias="date"),
    meal_type: str = Query(default="dinner"),
    page: int = Query(default=1, ge=1),
    include_vetoed: bool = Query(default=False),
    session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    return await generate_recommendations(
        db=db,
        target_date=target_date,
        meal_type=meal_type,
        page=page,
        include_vetoed=include_vetoed,
        user_token=session["mealie_token"],
    )


@app.post("/api/plan")
async def plan_meal_in_mealie(
    payload: PlanMealRequest,
    session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    recipe = db.get(RecipeCache, payload.mealie_recipe_id)
    title = recipe.name if recipe else ""
    try:
        created = await mealie_client.create_meal_plan_entry(
            plan_date=payload.date,
            entry_type=payload.meal_type,
            recipe_id=payload.mealie_recipe_id,
            user_token=session["mealie_token"],
            title=title,
        )
    except MealieAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except MealieUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return {"status": "planned", "mealie_entry": created}


@app.post("/api/sync")
async def trigger_recipe_sync(
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    try:
        result = await sync_recipes_from_mealie(db)
    except MealieUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return result


# Serve built Vue 3 frontend when present in ./static
static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
