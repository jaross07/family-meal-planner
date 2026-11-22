from datetime import date, datetime, timezone
import re
from sqlalchemy.orm import Session

from app.mealie_client import mealie_client
from app.models import ItemPreference, MealContext, RecipeCache, ShoppingListItem

STORES = ["WinCo", "Trader Joe's", "Costco", "Other"]
CATEGORIES = [
    "Produce",
    "Meat & Seafood",
    "Dairy & Eggs",
    "Bakery",
    "Frozen",
    "Pantry",
    "Other",
]

DEFAULT_STORE = "WinCo"
DEFAULT_CATEGORY = "Pantry"

_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (
        "Produce",
        (
            "apple", "avocado", "banana", "basil", "bell pepper", "berries", "blueberry",
            "broccoli", "cabbage", "carrot", "cauliflower", "celery", "cilantro", "cucumber",
            "garlic", "ginger", "grape", "green bean", "green onion", "jalapeno", "kale",
            "lemon", "lettuce", "lime", "mushroom", "onion", "orange", "parsley", "peach",
            "pear", "pepper", "pineapple", "potato", "romaine", "scallion", "shallot",
            "spinach", "squash", "strawberry", "sweet potato", "tomato", "zucchini",
        ),
    ),
    (
        "Meat & Seafood",
        (
            "bacon", "beef", "brisket", "chicken", "chorizo", "cod", "crab", "fish",
            "ground beef", "ground pork", "ground turkey", "ham", "kielbasa", "lamb",
            "meatball", "pork", "prosciutto", "roast", "salmon", "sausage", "shrimp",
            "steak", "tenderloin", "thigh", "tilapia", "tuna", "turkey",
        ),
    ),
    (
        "Dairy & Eggs",
        (
            "butter", "buttermilk", "cheddar", "cheese", "cottage cheese", "cream",
            "cream cheese", "egg", "feta", "half and half", "half-and-half", "milk",
            "mozzarella", "parmesan", "ricotta", "sour cream", "whipping cream", "yogurt",
        ),
    ),
    (
        "Bakery",
        (
            "bagel", "baguette", "bread", "brioche", "bun", "ciabatta", "croissant",
            "english muffin", "flatbread", "focaccia", "naan", "pita", "roll", "sourdough",
            "tortilla",
        ),
    ),
    (
        "Frozen",
        (
            "frozen", "ice cream", "tater tot", "edamame", "peas", "puff pastry", "waffle",
        ),
    ),
    (
        "Other",
        (
            "aluminum foil", "baggie", "bleach", "cat food", "detergent", "diaper",
            "dish soap", "dog food", "foil", "garbage bag", "napkin", "paper towel",
            "parchment", "plastic wrap", "shampoo", "soap", "sponge", "tissue",
            "toilet paper", "toothpaste", "trash bag", "wipe", "ziploc",
        ),
    ),
]


def normalize_item_name(raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", (raw or "").strip().lower())
    # Simple singularization for matching (e.g. "onions" -> "onion", "tomatoes" -> "tomato")
    if len(cleaned) > 4 and cleaned.endswith("oes"):
        cleaned = cleaned[:-2]
    elif len(cleaned) > 3 and cleaned.endswith("s") and not cleaned.endswith("ss"):
        cleaned = cleaned[:-1]
    return cleaned


def guess_category(normalized_name: str) -> str:
    for cat, keywords in _CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in normalized_name:
                return cat
    return DEFAULT_CATEGORY


def resolve_store_and_category(
    db: Session,
    normalized_name: str,
    explicit_store: str | None = None,
    explicit_category: str | None = None,
) -> tuple[str, str]:
    pref = db.get(ItemPreference, normalized_name)
    store = explicit_store if explicit_store in STORES else (pref.default_store if pref else DEFAULT_STORE)
    category = (
        explicit_category
        if explicit_category in CATEGORIES
        else (pref.default_category if pref else guess_category(normalized_name))
    )
    return store, category


def remember_item_preference(db: Session, normalized_name: str, store: str, category: str) -> None:
    if not normalized_name:
        return
    pref = db.get(ItemPreference, normalized_name)
    if pref is None:
        pref = ItemPreference(
            normalized_name=normalized_name,
            default_store=store if store in STORES else DEFAULT_STORE,
            default_category=category if category in CATEGORIES else DEFAULT_CATEGORY,
        )
        db.add(pref)
    else:
        if store in STORES:
            pref.default_store = store
        if category in CATEGORIES:
            pref.default_category = category


def _format_source_label(recipe_name: str, plan_date: date) -> str:
    return f"{recipe_name} ({plan_date.strftime('%a %m/%d')})"


async def get_planned_meals_for_import(
    db: Session,
    from_date: date,
    to_date: date,
) -> list[dict]:
    """Fetch planned Mealie meals in range, annotating days marked eating_leftovers or henleys_choice."""
    planned = await mealie_client.get_planned_meals(from_date, to_date)
    contexts = (
        db.query(MealContext)
        .filter(MealContext.date >= from_date, MealContext.date <= to_date)
        .all()
    )
    ctx_map = {(c.date, c.meal_type): c for c in contexts}

    cache_rows = db.query(RecipeCache).all()
    slug_by_id = {r.mealie_recipe_id: r.slug for r in cache_rows}

    results = []
    for entry in planned:
        pdate: date = entry["date"]
        mtype: str = entry["entry_type"]
        rid: str = entry["recipe_id"]
        slug: str = entry.get("slug") or slug_by_id.get(rid, "")
        ctx = ctx_map.get((pdate, mtype))
        skip_reason = None
        if ctx:
            if getattr(ctx, "eating_leftovers", False):
                skip_reason = "eating_leftovers"
            elif getattr(ctx, "henleys_choice", False):
                skip_reason = "henleys_choice"
            elif ctx.is_planned is False:
                skip_reason = "not_planned"

        results.append(
            {
                "id": entry.get("id", ""),
                "date": pdate.isoformat(),
                "meal_type": mtype,
                "recipe_id": rid,
                "slug": slug,
                "recipe_name": entry["recipe_name"],
                "has_recipe": bool(rid or slug),
                "skip_reason": skip_reason,
                "default_selected": bool((rid or slug) and not skip_reason),
            }
        )
    return results


async def import_recipes_to_shopping_list(
    db: Session,
    selections: list[dict],
) -> dict:
    """Pull ingredients for selected planned meals from Mealie and merge into shopping_list_items."""
    existing_unchecked = (
        db.query(ShoppingListItem)
        .filter(ShoppingListItem.checked.is_(False))
        .all()
    )
    # Key: (normalized_name, normalized_unit) -> ShoppingListItem
    active_by_key: dict[tuple[str, str], ShoppingListItem] = {}
    for row in existing_unchecked:
        ukey = (row.unit or "").strip().lower()
        active_by_key[(row.normalized_name, ukey)] = row

    recipe_cache: dict[str, dict | None] = {}
    added_count = 0
    merged_count = 0

    for sel in selections:
        lookup = sel.get("slug") or sel.get("recipe_id")
        if not lookup:
            continue
        if lookup not in recipe_cache:
            recipe_cache[lookup] = await mealie_client.fetch_recipe_details(lookup)
        recipe_data = recipe_cache[lookup]
        if not recipe_data:
            continue

        recipe_name = recipe_data.get("name") or sel.get("recipe_name") or "Planned Recipe"
        plan_date_str = sel.get("date", "")
        try:
            source_label = _format_source_label(recipe_name, date.fromisoformat(plan_date_str))
        except ValueError:
            source_label = recipe_name

        for ing in recipe_data.get("recipeIngredient") or []:
            food_obj = ing.get("food") or {}
            unit_obj = ing.get("unit") or {}
            food_name = (food_obj.get("name") or ing.get("display") or "").strip()
            if not food_name:
                continue

            norm_name = normalize_item_name(food_name)
            qty = ing.get("quantity")
            try:
                qty_val = float(qty) if qty is not None and float(qty) > 0 else None
            except (TypeError, ValueError):
                qty_val = None

            unit_name = (unit_obj.get("name") or "").strip() or None
            ukey = (unit_name or "").lower()
            note_val = (ing.get("note") or "").strip() or None

            match_key = (norm_name, ukey)
            if match_key in active_by_key:
                target = active_by_key[match_key]
                if qty_val is not None:
                    target.quantity = round((target.quantity or 0.0) + qty_val, 3)
                sources = list(target.source_recipes or [])
                if source_label not in sources:
                    sources.append(source_label)
                    target.source_recipes = sources
                merged_count += 1
            else:
                store, category = resolve_store_and_category(db, norm_name)
                new_item = ShoppingListItem(
                    name=food_name,
                    normalized_name=norm_name,
                    quantity=qty_val,
                    unit=unit_name,
                    note=note_val,
                    category=category,
                    store=store,
                    checked=False,
                    source_recipes=[source_label],
                )
                db.add(new_item)
                active_by_key[match_key] = new_item
                added_count += 1

    db.commit()
    return {"added": added_count, "merged": merged_count}
