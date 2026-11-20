import asyncio
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, "/app")

from google import genai
from google.genai import types

from app.config import settings
from app.database import SessionLocal
from app.ingest import ParsedRecipePayload, commit_recipe_to_mealie, get_mealie_catalog
from app.mealie_client import mealie_client
from app.sync import sync_recipes_from_mealie


def _parse_iso_minutes(val: str | None) -> int | None:
    if not val or not isinstance(val, str):
        return None
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?$", val.strip().upper())
    if not m:
        return None
    total = int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    return total if total > 0 else None


async def normalize_file_with_gemini(
    file_path: Path,
    client: genai.Client,
    known_foods: list[str],
    known_units: list[str],
) -> tuple[ParsedRecipePayload, str]:
    raw_text = file_path.read_text(encoding="utf-8", errors="replace")
    source_url = ""

    if file_path.suffix.lower() == ".json":
        try:
            obj = json.loads(raw_text)
            if isinstance(obj, dict):
                desc = str(obj.get("description") or "")
                url_match = re.search(r"https?://[^\s\"'<>]+", str(obj.get("url") or desc))
                if url_match:
                    source_url = url_match.group(0).rstrip(".,)")
        except json.JSONDecodeError:
            pass

    prompt = (
        "Convert and normalize the following recipe file into the required JSON schema.\n"
        "Rules:\n"
        "1. Convert fraction quantities (like 1/2 or 1 1/2) to decimal floats (0.5, 1.5).\n"
        "2. Map 'unit' to an existing canonical unit name when possible, or null if unitless (e.g. '3 eggs').\n"
        "3. Normalize 'food' to the singular/canonical base ingredient name WITHOUT preparation adjectives "
        "(e.g., 'fresh basil, chopped' -> food='basil', note='fresh, chopped'; '2 cup Cottage Cheese' -> food='cottage cheese').\n"
        "4. Skip non-food section headers or cookware lines in ingredient lists (like 'For the filling:', 'You will also need:', 'Nonstick skillet').\n"
        "5. Prefer exact matches from Existing Canonical Foods and Existing Canonical Units when appropriate.\n"
        "6. Clean up recipe title capitalization if ALL CAPS (e.g. 'ARTISAN NO-KNEAD BREAD' -> 'Artisan No-Knead Bread').\n"
        "7. Extract clean step-by-step instructions without step numbers prefixed.\n\n"
        f"Existing Canonical Units: {', '.join(known_units[:150])}\n"
        f"Existing Canonical Foods: {', '.join(known_foods[:400])}\n\n"
        f"Filename: {file_path.name}\n"
        f"File Contents:\n{raw_text[:12000]}"
    )

    resp = await client.aio.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ParsedRecipePayload,
            temperature=0.1,
        ),
    )
    parsed = ParsedRecipePayload.model_validate_json(resp.text)

    if file_path.suffix.lower() == ".json":
        try:
            obj = json.loads(raw_text)
            if parsed.prep_time_minutes is None:
                parsed.prep_time_minutes = _parse_iso_minutes(obj.get("prepTime"))
            if parsed.cook_time_minutes is None:
                parsed.cook_time_minutes = _parse_iso_minutes(obj.get("cookTime"))
        except Exception:
            pass

    return parsed, source_url


async def main(import_dir: str) -> None:
    root = Path(import_dir)
    files = sorted(
        [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".json", ".md"}]
    )
    if not files:
        print(f"No .json or .md files found in {import_dir}")
        return

    print(f"Found {len(files)} recipe file(s)...")

    existing_recipes = await mealie_client.fetch_all_recipes()
    existing_names = {r["name"].strip().lower() for r in existing_recipes}

    foods_map, units_map = await get_mealie_catalog(settings.mealie_service_token, force_refresh=True)
    known_foods = sorted(foods_map.keys())
    known_units = sorted(units_map.keys())

    ai_client = genai.Client(api_key=settings.gemini_api_key)
    imported = 0
    skipped = 0
    failed = 0

    for idx, fpath in enumerate(files, start=1):
        # Quick pre-check using JSON "name" or filename stem to avoid spending a Gemini call on already-imported recipes
        candidate_name = fpath.stem.strip().lower()
        if fpath.suffix.lower() == ".json":
            try:
                obj = json.loads(fpath.read_text(encoding="utf-8", errors="replace"))
                if isinstance(obj, dict) and obj.get("name"):
                    candidate_name = str(obj["name"]).strip().lower()
            except Exception:
                pass
        if candidate_name in existing_names:
            skipped += 1
            continue

        try:
            parsed, source_url = await normalize_file_with_gemini(
                fpath, ai_client, known_foods, known_units
            )
            if parsed.name.strip().lower() in existing_names:
                print(f"[{idx}/{len(files)}] SKIP (already exists): {parsed.name}")
                skipped += 1
                continue

            created = await commit_recipe_to_mealie(
                payload=parsed,
                source_url=source_url,
                user_token=settings.mealie_service_token,
            )
            existing_names.add(created["name"].strip().lower())
            imported += 1
            print(f"[{idx}/{len(files)}] IMPORTED: {created['name']} ({len(parsed.ingredients)} ingredients)")
        except Exception as exc:
            failed += 1
            print(f"[{idx}/{len(files)}] FAILED ({fpath.name}): {exc}")

    db = SessionLocal()
    try:
        sync_res = await sync_recipes_from_mealie(db)
        print(f"\nDone! Imported: {imported}, Skipped: {skipped}, Failed: {failed}")
        print(f"Planner cache synced: {sync_res['synced_total']} total active recipes.")
    finally:
        db.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "/tmp/recipe-import"
    asyncio.run(main(target))
