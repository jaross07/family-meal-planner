from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.auth import ensure_user_profile
from app.mealie_client import fetch_household_users, mealie_client
from app.models import RecipeCache, RecipeMeta


async def sync_recipes_from_mealie(db: Session) -> dict:
    """Refresh recipe_cache, seed recipe_meta, and sync household user profiles from Mealie."""
    household_users = await fetch_household_users()
    for member in household_users:
        ensure_user_profile(
            db=db,
            user_id=member["user_id"],
            username=member["username"],
            full_name=member["full_name"],
        )

    fetched = await mealie_client.fetch_all_recipes()
    now = datetime.now(timezone.utc)
    seen_ids: set[str] = set()

    created_count = 0
    updated_count = 0

    for item in fetched:
        rid = item["mealie_recipe_id"]
        seen_ids.add(rid)

        cached = db.get(RecipeCache, rid)
        if cached is None:
            cached = RecipeCache(
                mealie_recipe_id=rid,
                slug=item["slug"],
                name=item["name"],
                tags=item["tags"],
                last_seen_at=now,
                active=True,
            )
            db.add(cached)
            created_count += 1
        else:
            cached.slug = item["slug"]
            cached.name = item["name"]
            cached.tags = item["tags"]
            cached.last_seen_at = now
            cached.active = True
            updated_count += 1

        meta = db.get(RecipeMeta, rid)
        lower_tags = {t.lower() for t in item["tags"]}
        auto_leftover_yield = bool(lower_tags & {"leftovers", "make-extra", "batch-cook"})

        if meta is None:
            meta = RecipeMeta(
                mealie_recipe_id=rid,
                leftover_yield=auto_leftover_yield,
                prep_time_minutes=item["prep_time_minutes"],
            )
            db.add(meta)
        elif meta.prep_time_minutes is None and item["prep_time_minutes"] is not None:
            meta.prep_time_minutes = item["prep_time_minutes"]

    deactivated_count = 0
    if seen_ids:
        stale_recipes = (
            db.query(RecipeCache)
            .filter(RecipeCache.active.is_(True), ~RecipeCache.mealie_recipe_id.in_(seen_ids))
            .all()
        )
    else:
        stale_recipes = db.query(RecipeCache).filter(RecipeCache.active.is_(True)).all()

    for stale in stale_recipes:
        stale.active = False
        deactivated_count += 1

    db.commit()
    return {
        "synced_total": len(seen_ids),
        "created": created_count,
        "updated": updated_count,
        "deactivated": deactivated_count,
        "synced_at": now.isoformat(),
    }
