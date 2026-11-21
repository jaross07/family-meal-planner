import asyncio
from contextlib import asynccontextmanager
from datetime import date, timedelta
import logging
from pathlib import Path
import uuid

import holidays as pyholidays

import httpx

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
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
    DayNote,
    MealAttendance,
    FamilyEvent,
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
from app.ingest import ParsedRecipePayload, commit_recipe_to_mealie, preview_recipe_from_url
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
    note: str | None = Field(default=None, max_length=500)


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    initials: str | None = Field(default=None, min_length=1, max_length=4)
    color_code: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    active: bool | None = None
    week_start_day: int | None = Field(default=None, ge=0, le=1)
    calendar_view: str | None = Field(default=None, pattern=r"^(month|2week|1week)$")
    default_view: str | None = Field(default=None, pattern=r"^(planner|ratings)$")


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
    eating_leftovers: bool = False
    henleys_choice: bool = False


class RecipeMetaUpdateRequest(BaseModel):
    leftover_yield: bool = False
    prep_time_minutes: int | None = Field(default=None, ge=1, le=480)
    leftover_type: str | None = Field(default=None, max_length=100)


class LeftoverChainCreateRequest(BaseModel):
    parent_recipe_id: str
    child_recipe_id: str
    max_days_after: int = Field(default=3, ge=1, le=7)


class PlanMealRequest(BaseModel):
    date: date
    meal_type: str = Field(default="dinner", pattern=r"^(breakfast|lunch|dinner)$")
    mealie_recipe_id: str | None = None
    title: str | None = Field(default=None, max_length=200)


# --- Health & Auth ---

@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.post("/api/auth/login")
async def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    try:
        user_info = await mealie_client.login_and_get_user(payload.username, payload.password)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
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
        "mealie_public_url": settings.mealie_public_url,
        "current_user": {
            "mealie_user_id": profile.mealie_user_id,
            "display_name": profile.display_name,
            "initials": profile.initials,
            "color_code": profile.color_code,
            "week_start_day": profile.week_start_day,
            "calendar_view": profile.calendar_view,
            "default_view": profile.default_view,
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
    if payload.default_view is not None:
        profile.default_view = payload.default_view

    db.commit()
    db.refresh(profile)
    return {
        "mealie_user_id": profile.mealie_user_id,
        "display_name": profile.display_name,
        "initials": profile.initials,
        "color_code": profile.color_code,
        "week_start_day": profile.week_start_day,
        "calendar_view": profile.calendar_view,
        "default_view": profile.default_view,
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

# --- Hidden Recipes ---

class RecipeHiddenUpdate(BaseModel):
    hidden: bool


@app.get("/api/recipes/hidden")
def list_hidden_recipes(
    _: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(RecipeCache)
        .filter(RecipeCache.active.is_(True), RecipeCache.hidden.is_(True))
        .order_by(RecipeCache.name)
        .all()
    )
    return {
        "items": [
            {"mealie_recipe_id": r.mealie_recipe_id, "slug": r.slug, "name": r.name}
            for r in rows
        ]
    }


@app.put("/api/recipes/{recipe_id}/hidden")
def set_recipe_hidden(
    recipe_id: str,
    payload: RecipeHiddenUpdate,
    _: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    recipe = db.get(RecipeCache, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    recipe.hidden = payload.hidden
    db.commit()
    return {
        "mealie_recipe_id": recipe.mealie_recipe_id,
        "name": recipe.name,
        "hidden": recipe.hidden,
    }


# --- Ratings ---

@app.get("/api/ratings")
def get_all_my_ratings(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    my_rows = (
        db.query(RecipeRating)
        .filter(RecipeRating.mealie_user_id == user_id)
        .all()
    )
    my_ratings = {
        row.mealie_recipe_id: {"score": row.score, "note": row.note}
        for row in my_rows
    }

    all_notes = (
        db.query(RecipeRating)
        .filter(RecipeRating.note.isnot(None), RecipeRating.note != "")
        .all()
    )
    profiles = {p.mealie_user_id: p for p in db.query(UserProfile).all()}
    family_notes: dict[str, list] = {}
    for row in all_notes:
        profile = profiles.get(row.mealie_user_id)
        display_name = profile.display_name if profile else row.mealie_user_id
        family_notes.setdefault(row.mealie_recipe_id, []).append({
            "user_id": row.mealie_user_id,
            "display_name": display_name,
            "note": row.note,
            "score": row.score,
        })

    return {"my_ratings": my_ratings, "family_notes": family_notes}


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
        "note": row.note if row else None,
    }


@app.put("/api/ratings/{recipe_id}")
def upsert_recipe_rating(
    recipe_id: str,
    payload: RatingUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    clean_note = payload.note.strip() if payload.note and payload.note.strip() else None
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
            note=clean_note,
        )
        db.add(row)
    else:
        row.score = payload.score
        if payload.note is not None:
            row.note = clean_note

    db.commit()
    return {
        "mealie_recipe_id": recipe_id,
        "mealie_user_id": user_id,
        "score": row.score,
        "note": row.note,
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
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    end = payload.end_date or payload.start_date
    if end < payload.start_date:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    if (end - payload.start_date).days > 62:
        raise HTTPException(status_code=400, detail="Range cannot exceed 62 days")

    # Tag batch_id with acting user's ID so undo reverts only the current user's last batch
    batch_id = f"{user_id}:{uuid.uuid4().hex[:24]}"
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

class DayNoteUpdateRequest(BaseModel):
    note: str = Field(default="", max_length=2000)


@app.get("/api/day-notes")
def list_day_notes(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(DayNote)
        .filter(DayNote.date >= from_date, DayNote.date <= to_date, DayNote.note != "")
        .all()
    )
    return {row.date.isoformat(): row.note for row in rows}


@app.put("/api/day-notes/{target_date}")
def upsert_day_note(
    target_date: date,
    payload: DayNoteUpdateRequest,
    _: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    cleaned = payload.note.strip()
    row = db.get(DayNote, target_date)
    if not cleaned:
        if row is not None:
            db.delete(row)
            db.commit()
        return {"date": target_date.isoformat(), "note": ""}

    if row is None:
        row = DayNote(date=target_date, note=cleaned)
        db.add(row)
    else:
        row.note = cleaned
    db.commit()
    return {"date": target_date.isoformat(), "note": row.note}


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
            "eating_leftovers": r.eating_leftovers,
            "henleys_choice": r.henleys_choice,
        }
        for r in rows
    ]


@app.get("/api/context")
def get_meal_context(
    target_date: date = Query(..., alias="date"),
    meal_type: str = Query(default="dinner", pattern=r"^(breakfast|lunch|dinner)$"),
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
        "eating_leftovers": ctx.eating_leftovers if ctx else False,
        "henleys_choice": ctx.henleys_choice if ctx else False,
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
            eating_leftovers=payload.eating_leftovers,
            henleys_choice=payload.henleys_choice,
        )
        db.add(ctx)
    else:
        ctx.require_leftovers = payload.require_leftovers
        ctx.max_prep_time = payload.max_prep_time
        ctx.is_planned = payload.is_planned
        ctx.eating_leftovers = payload.eating_leftovers
        ctx.henleys_choice = payload.henleys_choice

    db.commit()
    return {
        "date": ctx.date.isoformat(),
        "meal_type": ctx.meal_type,
        "require_leftovers": ctx.require_leftovers,
        "max_prep_time": ctx.max_prep_time,
        "is_planned": ctx.is_planned,
        "eating_leftovers": ctx.eating_leftovers,
        "henleys_choice": ctx.henleys_choice,
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

@app.get("/api/categories")
def list_recipe_categories(
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    """Return sorted distinct Mealie recipe categories from active cached recipes."""
    rows = db.query(RecipeCache.categories).filter(RecipeCache.active.is_(True)).all()
    seen: dict[str, str] = {}
    for (cats,) in rows:
        for c in cats or []:
            cleaned = (c or "").strip()
            if cleaned and cleaned.lower() not in seen:
                seen[cleaned.lower()] = cleaned
    return {"items": sorted(seen.values(), key=lambda s: s.lower())}


@app.get("/api/recommendations")
async def get_recommendations(
    target_date: date = Query(..., alias="date"),
    meal_type: str = Query(default="dinner", pattern=r"^(breakfast|lunch|dinner)$"),
    page: int = Query(default=1, ge=1),
    include_vetoed: bool = Query(default=False),
    q: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None, max_length=120),
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
        q=q,
        category=category,
    )


@app.post("/api/plan")
async def plan_meal_in_mealie(
    payload: PlanMealRequest,
    session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    recipe = db.get(RecipeCache, payload.mealie_recipe_id) if payload.mealie_recipe_id else None
    title = (payload.title or "").strip() or (recipe.name if recipe else "")
    if not payload.mealie_recipe_id and not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either a recipe or a custom meal title.",
        )
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


class BatchPlanItem(BaseModel):
    date: date
    meal_type: str = Field(default="dinner", pattern=r"^(breakfast|lunch|dinner|side)$")
    mealie_recipe_id: str


class BatchPlanRequest(BaseModel):
    items: list[BatchPlanItem]


@app.put("/api/recipes/{recipe_id}/meta")
def update_recipe_meta(
    recipe_id: str,
    payload: RecipeMetaUpdateRequest,
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    """Toggle Make Extra (leftover_yield) or prep metadata directly from the Planner UI."""
    meta = db.get(RecipeMeta, recipe_id)
    if meta is None:
        meta = RecipeMeta(
            mealie_recipe_id=recipe_id,
            leftover_yield=payload.leftover_yield,
            prep_time_minutes=payload.prep_time_minutes,
            leftover_type=payload.leftover_type,
        )
        db.add(meta)
    else:
        meta.leftover_yield = payload.leftover_yield
        if payload.prep_time_minutes is not None:
            meta.prep_time_minutes = payload.prep_time_minutes
        if payload.leftover_type is not None:
            meta.leftover_type = payload.leftover_type

    db.commit()
    return {
        "mealie_recipe_id": recipe_id,
        "leftover_yield": meta.leftover_yield,
        "prep_time_minutes": meta.prep_time_minutes,
        "leftover_type": meta.leftover_type,
    }


@app.get("/api/recipes/{recipe_id}/image")
async def get_recipe_thumbnail(
    recipe_id: str,
    _: dict = Depends(get_current_session),
):
    """Proxy recipe thumbnail image from Mealie."""
    img = await mealie_client.fetch_recipe_image(recipe_id)
    if not img:
        return Response(status_code=404)
    content, media_type = img
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.get("/api/planned")
async def get_planned_meals_range(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    session: dict = Depends(get_current_session),
):
    """Fetch existing planned meals from Mealie for the visible calendar range."""
    try:
        entries = await mealie_client.get_planned_meals(
            start_date=from_date,
            end_date=to_date,
            user_token=session["mealie_token"],
        )
        return {
            "mealie_available": True,
            "items": [
                {
                    "id": e["id"],
                    "date": e["date"].isoformat(),
                    "meal_type": e["entry_type"],
                    "mealie_recipe_id": e["recipe_id"],
                    "name": e["recipe_name"],
                    "slug": e["slug"],
                }
                for e in entries
            ],
        }
    except MealieUnavailableError:
        return {"mealie_available": False, "items": []}


@app.delete("/api/plan/{plan_id}")
async def remove_planned_meal(
    plan_id: str,
    session: dict = Depends(get_current_session),
):
    """Delete a planned meal entry from Mealie."""
    try:
        await mealie_client.delete_meal_plan_entry(
            plan_id=plan_id,
            user_token=session["mealie_token"],
        )
        return {"status": "deleted", "id": plan_id}
    except MealieAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except MealieUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@app.get("/api/week-preview")
async def preview_week_plan(
    start_date: date = Query(...),
    meal_type: str = Query(default="dinner", pattern=r"^(breakfast|lunch|dinner)$"),
    session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    """Generate a 7-day non-repeating meal plan preview respecting attendance & day context."""
    days_out = []
    used_recipe_ids: set[str] = set()
    mealie_ok = True

    for offset in range(7):
        day = start_date + timedelta(days=offset)
        ctx = (
            db.query(MealContext)
            .filter(MealContext.date == day, MealContext.meal_type == meal_type)
            .first()
        )
        default_planned = (meal_type == "dinner")
        is_planned = ctx.is_planned if ctx else default_planned

        eating_leftovers = ctx.eating_leftovers if ctx else False
        henleys_choice = ctx.henleys_choice if ctx else False
        if not is_planned or eating_leftovers or henleys_choice:
            reason = (
                "eating_leftovers"
                if eating_leftovers
                else "henleys_choice"
                if henleys_choice
                else "not_planned"
            )
            days_out.append({
                "date": day.isoformat(),
                "is_planned": False,
                "reason": reason,
                "diners": [],
                "selected_recipe_id": None,
                "candidates": [],
            })
            continue

        rec = await generate_recommendations(
            db=db,
            target_date=day,
            meal_type=meal_type,
            page=1,
            include_vetoed=False,
            user_token=session["mealie_token"],
        )
        if rec.get("mealie_available") is False:
            mealie_ok = False

        candidates = rec.get("items", [])
        chosen = next((c for c in candidates if c["mealie_recipe_id"] not in used_recipe_ids), None)
        if chosen is None and candidates:
            chosen = candidates[0]

        if chosen:
            used_recipe_ids.add(chosen["mealie_recipe_id"])

        days_out.append({
            "date": day.isoformat(),
            "is_planned": True,
            "reason": rec.get("reason"),
            "diners": rec.get("diners", []),
            "selected_recipe_id": chosen["mealie_recipe_id"] if chosen else None,
            "candidates": candidates[:8],
        })

    return {
        "start_date": start_date.isoformat(),
        "meal_type": meal_type,
        "mealie_available": mealie_ok,
        "days": days_out,
    }


@app.post("/api/plan-week")
async def commit_week_plan(
    payload: BatchPlanRequest,
    session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    """Write multiple planned meals to Mealie in one batch."""
    created = []
    for item in payload.items:
        cached = db.get(RecipeCache, item.mealie_recipe_id)
        title = cached.name if cached else ""
        try:
            res = await mealie_client.create_meal_plan_entry(
                plan_date=item.date,
                entry_type=item.meal_type,
                recipe_id=item.mealie_recipe_id,
                user_token=session["mealie_token"],
                title=title,
            )
            created.append({"date": item.date.isoformat(), "mealie_entry": res})
        except MealieAuthError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
        except MealieUnavailableError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            ) from exc
    return {"status": "planned", "count": len(created), "entries": created}


class IngestPreviewRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)


class IngestCommitRequest(BaseModel):
    source_url: str = Field(..., min_length=8, max_length=2048)
    recipe: ParsedRecipePayload


@app.post("/api/ingest/preview")
async def ingest_recipe_preview(
    payload: IngestPreviewRequest,
    session: dict = Depends(get_current_session),
):
    """Fetch a recipe URL and extract normalized ingredients/steps via Gemini Flash for HITL review."""
    try:
        parsed = await preview_recipe_from_url(
            url=payload.url.strip(),
            user_token=session["mealie_token"],
        )
        return {"source_url": payload.url.strip(), "recipe": parsed.model_dump()}
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Target site blocked or failed request (HTTP {exc.response.status_code})",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to fetch recipe URL: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Gemini extraction error: {exc}") from exc


@app.post("/api/ingest/commit", status_code=201)
async def ingest_recipe_commit(
    payload: IngestCommitRequest,
    session: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    """Inject the user-reviewed normalized recipe into Mealie and refresh local recipe_cache."""
    try:
        created = await commit_recipe_to_mealie(
            payload=payload.recipe,
            source_url=payload.source_url.strip(),
            user_token=session["mealie_token"],
        )
        await sync_recipes_from_mealie(db)
        return {"status": "imported", "recipe": created}
    except MealieAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except MealieUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Mealie rejected recipe payload: {exc}") from exc


class FamilyEventCreate(BaseModel):
    month: int = Field(..., ge=1, le=12)
    day: int = Field(..., ge=1, le=31)
    label: str = Field(..., min_length=1, max_length=120)
    emoji: str = Field(default="🎉", min_length=1, max_length=16)


HOLIDAY_EMOJIS = {
    "New Year's Day": "🎆",
    "Martin Luther King Jr. Day": "✊",
    "Washington's Birthday": "🇺🇸",
    "Memorial Day": "🇺🇸",
    "Juneteenth National Independence Day": "🎉",
    "Independence Day": "🎇",
    "Labor Day": "🛠️",
    "Columbus Day": "🧭",
    "Veterans Day": "🎖️",
    "Thanksgiving Day": "🦃",
    "Christmas Day": "🎄",
}


@app.get("/api/holidays")
def get_holidays_and_events(
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    """Return US Federal Holidays + custom recurring family dates for the visible window."""
    years = list(range(from_date.year, to_date.year + 1))
    us_hols = pyholidays.country_holidays("US", years=years)
    custom_rows = db.query(FamilyEvent).order_by(FamilyEvent.month, FamilyEvent.day, FamilyEvent.id).all()

    items = []
    cur = from_date
    while cur <= to_date:
        if cur in us_hols:
            name = us_hols.get(cur)
            items.append({
                "date": cur.isoformat(),
                "label": name,
                "emoji": HOLIDAY_EMOJIS.get(name, "🏛️"),
                "source": "us_holiday",
            })
        for ev in custom_rows:
            if ev.month == cur.month and ev.day == cur.day:
                items.append({
                    "id": ev.id,
                    "date": cur.isoformat(),
                    "label": ev.label,
                    "emoji": ev.emoji or "🎉",
                    "source": "family",
                })
        cur += timedelta(days=1)

    return {
        "items": items,
        "family_events": [
            {
                "id": ev.id,
                "month": ev.month,
                "day": ev.day,
                "label": ev.label,
                "emoji": ev.emoji,
            }
            for ev in custom_rows
        ],
    }


@app.post("/api/family-events", status_code=201)
def create_family_event(
    payload: FamilyEventCreate,
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    # Validate calendar month/day (allow Feb 29)
    try:
        date(2024, payload.month, payload.day)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid month/day combination") from exc

    ev = FamilyEvent(
        month=payload.month,
        day=payload.day,
        label=payload.label.strip(),
        emoji=(payload.emoji or "🎉").strip(),
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return {
        "id": ev.id,
        "month": ev.month,
        "day": ev.day,
        "label": ev.label,
        "emoji": ev.emoji,
    }


@app.delete("/api/family-events/{event_id}")
def delete_family_event(
    event_id: int,
    _: dict = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    ev = db.get(FamilyEvent, event_id)
    if not ev:
        raise HTTPException(status_code=404, detail="Family event not found")
    db.delete(ev)
    db.commit()
    return {"status": "deleted", "id": event_id}


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
