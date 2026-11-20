import json
import re
import time
from typing import Any

from bs4 import BeautifulSoup
from google import genai
from google.genai import types
import httpx
from pydantic import BaseModel, Field
import trafilatura

from app.config import settings
from app.mealie_client import MealieAuthError, MealieUnavailableError, mealie_client

_CATALOG_CACHE: dict[str, Any] = {"expires_at": 0.0, "foods": {}, "units": {}}
_CATALOG_TTL_SECONDS = 600


class ParsedIngredient(BaseModel):
    original_text: str = Field(..., description="Raw ingredient line from the recipe")
    quantity: float | None = Field(default=None, description="Numeric quantity (fractions converted to floats)")
    unit: str | None = Field(default=None, description="Canonical measurement unit name, or null if unitless")
    food: str = Field(..., description="Canonical base ingredient name with prep modifiers stripped (e.g. 'basil', not 'fresh basil')")
    note: str | None = Field(default=None, description="Preparation state or modifier (e.g. 'fresh, chopped', 'minced', 'divided')")


class ParsedRecipePayload(BaseModel):
    name: str
    description: str = ""
    prep_time_minutes: int | None = None
    cook_time_minutes: int | None = None
    total_time_minutes: int | None = None
    recipe_yield: str | None = None
    image_url: str | None = None
    tags: list[str] = Field(default_factory=list)
    ingredients: list[ParsedIngredient]
    instructions: list[str]


def _extract_json_ld_recipe(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Pull schema.org Recipe JSON-LD if embedded in the page."""
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        candidates = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            rtype = item.get("@type")
            if rtype == "Recipe" or (isinstance(rtype, list) and "Recipe" in rtype):
                return item
    return None


async def fetch_and_reduce_url(url: str) -> dict[str, Any]:
    """Stage 1 & 2: Fetch recipe HTML, extract JSON-LD, and reduce noisy DOM to clean text."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; FamilyMealPlannerBot/1.0; +https://github.com/jaross07/family-meal-planner)"
    }
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        html = resp.text

    soup = BeautifulSoup(html, "html.parser")
    json_ld = _extract_json_ld_recipe(soup)

    og_image = None
    og_tag = soup.find("meta", property="og:image")
    if og_tag and og_tag.get("content"):
        og_image = str(og_tag["content"]).strip()

    clean_text = trafilatura.extract(html, include_comments=False, include_tables=True) or ""
    if not clean_text:
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        clean_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:12000]

    return {
        "url": str(resp.url),
        "json_ld": json_ld,
        "og_image": og_image,
        "clean_text": clean_text[:12000],
    }


async def get_mealie_catalog(user_token: str, force_refresh: bool = False) -> tuple[dict[str, dict], dict[str, dict]]:
    """Stage 3: Fetch and TTL-cache Mealie's canonical foods and units."""
    now = time.monotonic()
    if not force_refresh and now < _CATALOG_CACHE["expires_at"] and _CATALOG_CACHE["foods"]:
        return _CATALOG_CACHE["foods"], _CATALOG_CACHE["units"]

    auth_headers = {"Authorization": f"Bearer {user_token}", "Accept": "application/json"}
    async with httpx.AsyncClient(base_url=mealie_client.base_url, timeout=15.0) as client:
        foods_resp = await client.get("/api/foods", params={"perPage": 2000}, headers=auth_headers)
        units_resp = await client.get("/api/units", params={"perPage": 500}, headers=auth_headers)
        foods_resp.raise_for_status()
        units_resp.raise_for_status()

    foods_items = foods_resp.json().get("items", [])
    units_items = units_resp.json().get("items", [])

    foods_map = {f["name"].strip().lower(): f for f in foods_items if f.get("name")}
    units_map = {u["name"].strip().lower(): u for u in units_items if u.get("name")}
    for u in units_items:
        if u.get("abbreviation"):
            units_map.setdefault(u["abbreviation"].strip().lower(), u)

    _CATALOG_CACHE["foods"] = foods_map
    _CATALOG_CACHE["units"] = units_map
    _CATALOG_CACHE["expires_at"] = now + _CATALOG_TTL_SECONDS
    return foods_map, units_map


async def preview_recipe_from_url(url: str, user_token: str) -> ParsedRecipePayload:
    """Stage 1-4: Fetch URL, match against Mealie catalog, and extract structured recipe via Gemini Flash."""
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured in .env")

    reduced = await fetch_and_reduce_url(url)
    foods_map, units_map = await get_mealie_catalog(user_token)

    known_foods_sample = sorted(foods_map.keys())[:400]
    known_units_sample = sorted(units_map.keys())[:150]

    prompt = (
        "Extract and normalize the recipe from the provided webpage data into the required JSON schema.\n"
        "Rules:\n"
        "1. Convert fraction quantities (like 1/2 or 1 1/2) to decimal floats (0.5, 1.5).\n"
        "2. Map 'unit' to an existing canonical unit name when possible, or null if unitless (e.g. '2 eggs').\n"
        "3. Normalize 'food' to the singular/canonical base ingredient name WITHOUT preparation adjectives "
        "(e.g., 'fresh basil' -> food='basil', note='fresh'; 'minced garlic cloves' -> food='garlic', note='minced').\n"
        "4. Prefer exact matches from Existing Canonical Foods and Existing Canonical Units when appropriate.\n"
        "5. Extract clean step-by-step instructions without step numbers prefixed.\n\n"
        f"Existing Canonical Units: {', '.join(known_units_sample)}\n"
        f"Existing Canonical Foods: {', '.join(known_foods_sample)}\n\n"
        f"JSON-LD Data: {json.dumps(reduced['json_ld'])[:6000]}\n\n"
        f"Cleaned Page Text:\n{reduced['clean_text'][:6000]}"
    )

    client = genai.Client(api_key=settings.gemini_api_key)
    response = await client.aio.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ParsedRecipePayload,
            temperature=0.1,
        ),
    )

    parsed = ParsedRecipePayload.model_validate_json(response.text)
    if not parsed.image_url and reduced["og_image"]:
        parsed.image_url = reduced["og_image"]
    return parsed


async def _ensure_mealie_entity(
    client: httpx.AsyncClient,
    endpoint: str,
    name: str,
    cache_map: dict[str, dict],
    headers: dict[str, str],
) -> dict[str, Any]:
    clean_name = name.strip()
    key = clean_name.lower()
    if key in cache_map:
        return cache_map[key]

    resp = await client.post(endpoint, json={"name": clean_name}, headers=headers)
    if resp.status_code in (200, 201):
        created = resp.json()
        cache_map[key] = created
        return created

    if resp.status_code == 409:
        # Mealie detected an existing singular/plural/alias match — fetch it via search
        search_resp = await client.get(endpoint, params={"search": clean_name, "perPage": 50}, headers=headers)
        if search_resp.status_code == 200:
            items = search_resp.json().get("items", [])
            for item in items:
                names = {
                    (item.get("name") or "").strip().lower(),
                    (item.get("pluralName") or "").strip().lower(),
                }
                names.update(
                    (a.get("name") or "").strip().lower()
                    for a in (item.get("aliases") or [])
                    if isinstance(a, dict)
                )
                if key in names:
                    cache_map[key] = item
                    return item
            if items:
                cache_map[key] = items[0]
                return items[0]

    resp.raise_for_status()
    return resp.json()


async def commit_recipe_to_mealie(
    payload: ParsedRecipePayload,
    source_url: str,
    user_token: str,
) -> dict[str, Any]:
    """Stage 5: Create missing foods/units in Mealie, inject normalized recipe, and upload cover image."""
    foods_map, units_map = await get_mealie_catalog(user_token)
    headers = {"Authorization": f"Bearer {user_token}", "Accept": "application/json"}

    async with httpx.AsyncClient(base_url=mealie_client.base_url, timeout=25.0) as client:
        # 1. Create blank recipe shell in Mealie to obtain its canonical slug & ID
        create_resp = await client.post("/api/recipes", json={"name": payload.name.strip()}, headers=headers)
        if create_resp.status_code in (401, 403):
            raise MealieAuthError("Mealie rejected user token while creating recipe")
        if create_resp.status_code >= 500:
            raise MealieUnavailableError(f"Mealie error {create_resp.status_code} creating recipe")
        create_resp.raise_for_status()
        slug = create_resp.json().strip('"')

        # 2. Resolve canonical foods & units for each parsed ingredient
        structured_ingredients = []
        for ing in payload.ingredients:
            food_obj = await _ensure_mealie_entity(client, "/api/foods", ing.food, foods_map, headers)
            unit_obj = None
            if ing.unit and ing.unit.strip():
                unit_obj = await _ensure_mealie_entity(client, "/api/units", ing.unit, units_map, headers)

            structured_ingredients.append(
                {
                    "quantity": ing.quantity,
                    "unit": {"id": unit_obj["id"], "name": unit_obj["name"]} if unit_obj else None,
                    "food": {"id": food_obj["id"], "name": food_obj["name"]},
                    "note": ing.note or "",
                    "display": ing.original_text,
                }
            )

        # 3. Patch full normalized recipe details into Mealie
        patch_body: dict[str, Any] = {
            "name": payload.name.strip(),
            "description": payload.description,
            "orgURL": source_url,
            "recipeYield": payload.recipe_yield or "",
            "prepTime": f"{payload.prep_time_minutes} Minutes" if payload.prep_time_minutes else None,
            "cookTime": f"{payload.cook_time_minutes} Minutes" if payload.cook_time_minutes else None,
            "totalTime": f"{payload.total_time_minutes} Minutes" if payload.total_time_minutes else None,
            "recipeIngredient": structured_ingredients,
            "recipeInstructions": [{"text": step.strip()} for step in payload.instructions if step.strip()],
        }
        patch_resp = await client.patch(f"/api/recipes/{slug}", json=patch_body, headers=headers)
        patch_resp.raise_for_status()
        updated_recipe = patch_resp.json()

        # 4. Download and attach hero image if available
        if payload.image_url:
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as img_client:
                    img_resp = await img_client.get(payload.image_url)
                    if img_resp.status_code == 200 and img_resp.content:
                        ext = "png" if "png" in img_resp.headers.get("content-type", "") else "jpg"
                        await client.put(
                            f"/api/recipes/{slug}/image",
                            headers={"Authorization": f"Bearer {user_token}"},
                            data={"extension": ext},
                            files={"image": (f"cover.{ext}", img_resp.content, img_resp.headers.get("content-type", "image/jpeg"))},
                        )
            except Exception:
                pass  # Non-fatal if remote blog blocks image hotlinking

    return {
        "mealie_recipe_id": str(updated_recipe.get("id", "")),
        "slug": slug,
        "name": updated_recipe.get("name", payload.name),
    }
