from datetime import date, timedelta
from sqlalchemy.orm import Session

from app.mealie_client import MealieUnavailableError, mealie_client
from app.models import (
    MealContext,
    RecipeCache,
    RecipeLeftoverChain,
    RecipeMeta,
    RecipeRating,
)
from app.rules import get_diners_for_meal

LEFTOVER_CHAIN_BOOST = 1.5


async def generate_recommendations(
    db: Session,
    target_date: date,
    meal_type: str,
    page: int = 1,
    page_size: int = 20,
    include_vetoed: bool = False,
    user_token: str | None = None,
) -> dict:
    """
    Compute ranked recipe recommendations for the diners eating on (target_date, meal_type).
    Applies hard diner vetoes, day-level prep-time caps, high-yield lunch leftover requirements,
    and multi-day Leftover Chain boosts.
    """
    diners = get_diners_for_meal(db, target_date, meal_type)
    if not diners:
        return {
            "date": target_date.isoformat(),
            "meal_type": meal_type,
            "reason": "no_diners",
            "diners": [],
            "context": None,
            "total": 0,
            "page": page,
            "page_size": page_size,
            "items": [],
        }

    diner_ids = [d["mealie_user_id"] for d in diners]

    # Fetch day-level context flags (Fast & Easy / Make Extra)
    context = (
        db.query(MealContext)
        .filter(MealContext.date == target_date, MealContext.meal_type == meal_type)
        .first()
    )
    require_leftovers = context.require_leftovers if context else False
    max_prep_time = context.max_prep_time if context else None

    # Load active recipes and their metadata
    active_recipes = db.query(RecipeCache).filter(RecipeCache.active.is_(True)).all()
    if not active_recipes:
        return {
            "date": target_date.isoformat(),
            "meal_type": meal_type,
            "reason": "no_recipes",
            "diners": diners,
            "context": {
                "require_leftovers": require_leftovers,
                "max_prep_time": max_prep_time,
            },
            "total": 0,
            "page": page,
            "page_size": page_size,
            "items": [],
        }

    recipe_map = {r.mealie_recipe_id: r for r in active_recipes}
    meta_rows = db.query(RecipeMeta).filter(RecipeMeta.mealie_recipe_id.in_(recipe_map.keys())).all()
    meta_map = {m.mealie_recipe_id: m for m in meta_rows}

    # Load all ratings for current diners across active recipes
    rating_rows = (
        db.query(RecipeRating)
        .filter(
            RecipeRating.mealie_recipe_id.in_(recipe_map.keys()),
            RecipeRating.mealie_user_id.in_(diner_ids),
        )
        .all()
    )
    ratings_by_recipe: dict[str, dict[str, int]] = {}
    for row in rating_rows:
        ratings_by_recipe.setdefault(row.mealie_recipe_id, {})[row.mealie_user_id] = row.score

    # Check Mealie planned meals from the past 7 days for Leftover Chains & variety recency
    last_planned_map: dict[str, date] = {}
    leftover_boost_reasons: dict[str, str] = {}
    mealie_available = True

    try:
        lookback_start = target_date - timedelta(days=14)
        lookback_end = target_date - timedelta(days=1)
        if lookback_end >= lookback_start:
            recent_plans = await mealie_client.get_planned_meals(
                lookback_start, lookback_end, user_token=user_token
            )
            for plan in recent_plans:
                rid = plan["recipe_id"]
                pdate = plan["date"]
                if rid not in last_planned_map or pdate > last_planned_map[rid]:
                    last_planned_map[rid] = pdate

            # Match recent parent recipes against recipe_leftover_chains
            if last_planned_map:
                chains = (
                    db.query(RecipeLeftoverChain)
                    .filter(RecipeLeftoverChain.parent_recipe_id.in_(last_planned_map.keys()))
                    .all()
                )
                for chain in chains:
                    parent_date = last_planned_map.get(chain.parent_recipe_id)
                    if parent_date is None:
                        continue
                    days_elapsed = (target_date - parent_date).days
                    if 1 <= days_elapsed <= chain.max_days_after:
                        parent_recipe = recipe_map.get(chain.parent_recipe_id)
                        parent_meta = meta_map.get(chain.parent_recipe_id)
                        leftover_label = (
                            parent_meta.leftover_type
                            if parent_meta and parent_meta.leftover_type
                            else (parent_recipe.name if parent_recipe else "recent meal")
                        )
                        day_name = parent_date.strftime("%A")
                        leftover_boost_reasons[chain.child_recipe_id] = (
                            f"Uses leftover {leftover_label} from {day_name}"
                        )
    except MealieUnavailableError:
        mealie_available = False

    scored_items: list[dict] = []
    vetoed_count = 0

    for rid, recipe in recipe_map.items():
        user_scores = ratings_by_recipe.get(rid, {})
        diner_scores = [user_scores.get(uid, 0) for uid in diner_ids]

        # 1. Hard Veto check
        is_vetoed = any(s == -1 for s in diner_scores)
        if is_vetoed:
            vetoed_count += 1
            if not include_vetoed:
                continue

        meta = meta_map.get(rid)
        prep_minutes = meta.prep_time_minutes if meta else None
        leftover_yield = meta.leftover_yield if meta else False

        # 2. Time constraint filtering (Fast & Easy days)
        if max_prep_time is not None:
            if prep_minutes is None or prep_minutes > max_prep_time:
                continue

        # 3. Lunch leftover filtering (Make Extra days)
        if require_leftovers and not leftover_yield:
            continue

        # 4. Base score (diners' average rating) + Leftover Chain boost
        avg_score = sum(diner_scores) / len(diner_ids)
        leftover_badge = leftover_boost_reasons.get(rid)
        final_score = avg_score + (LEFTOVER_CHAIN_BOOST if leftover_badge else 0.0)

        last_planned = last_planned_map.get(rid)
        # Sort key: highest final_score first, then least-recently planned first (None = never planned -> oldest)
        recency_sort = last_planned.toordinal() if last_planned else 0

        scored_items.append(
            {
                "mealie_recipe_id": rid,
                "slug": recipe.slug,
                "name": recipe.name,
                "tags": recipe.tags,
                "score": round(final_score, 3),
                "base_rating_avg": round(avg_score, 3),
                "is_vetoed": is_vetoed,
                "prep_time_minutes": prep_minutes,
                "leftover_yield": leftover_yield,
                "leftover_badge": leftover_badge,
                "last_planned_date": last_planned.isoformat() if last_planned else None,
                "_sort_key": (-final_score, recency_sort, recipe.name.lower()),
            }
        )

    if not scored_items:
        reason = "all_vetoed" if (vetoed_count > 0 and not include_vetoed) else "no_matching_recipes"
        return {
            "date": target_date.isoformat(),
            "meal_type": meal_type,
            "reason": reason,
            "mealie_available": mealie_available,
            "diners": diners,
            "context": {
                "require_leftovers": require_leftovers,
                "max_prep_time": max_prep_time,
            },
            "total": 0,
            "page": page,
            "page_size": page_size,
            "items": [],
        }

    scored_items.sort(key=lambda item: item["_sort_key"])
    for item in scored_items:
        item.pop("_sort_key", None)

    total = len(scored_items)
    start_idx = max(0, (page - 1) * page_size)
    paginated = scored_items[start_idx : start_idx + page_size]

    return {
        "date": target_date.isoformat(),
        "meal_type": meal_type,
        "reason": "ok",
        "mealie_available": mealie_available,
        "diners": diners,
        "context": {
            "require_leftovers": require_leftovers,
            "max_prep_time": max_prep_time,
        },
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": paginated,
    }
