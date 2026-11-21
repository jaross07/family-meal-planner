from datetime import date, datetime
import re
import httpx

from app.config import settings


class MealieUnavailableError(Exception):
    """Raised when Mealie cannot be reached or returns a server error."""


class MealieAuthError(Exception):
    """Raised when Mealie rejects credentials or a user token."""


def _parse_duration_minutes(raw_value: str | int | None) -> int | None:
    """Convert Mealie duration strings (e.g., 'PT30M', 'PT1H15M', '45 minutes') to integer minutes."""
    if raw_value is None:
        return None
    if isinstance(raw_value, int):
        return raw_value

    text = str(raw_value).strip().upper()
    if not text:
        return None
    if text.isdigit():
        return int(text)

    # Handle ISO 8601 durations like PT1H30M or PT45M
    iso_match = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?$", text)
    if iso_match:
        hours = int(iso_match.group(1) or 0)
        minutes = int(iso_match.group(2) or 0)
        total = hours * 60 + minutes
        return total if total > 0 else None

    # Handle plain text durations like "1 hour 20 mins" or "30 minutes"
    hours_match = re.search(r"(\d+)\s*(?:H|HR|HRS|HOUR|HOURS)\b", text)
    mins_match = re.search(r"(\d+)\s*(?:M|MIN|MINS|MINUTE|MINUTES)\b", text)
    if hours_match or mins_match:
        hours = int(hours_match.group(1)) if hours_match else 0
        minutes = int(mins_match.group(1)) if mins_match else 0
        total = hours * 60 + minutes
        return total if total > 0 else None

    return None


class MealieClient:
    def __init__(self, base_url: str | None = None, service_token: str | None = None):
        self.base_url = (base_url or settings.mealie_internal_url).rstrip("/")
        self.service_token = service_token or settings.mealie_service_token
        self.timeout = httpx.Timeout(10.0, connect=5.0)

    def _headers(self, token: str | None = None) -> dict[str, str]:
        active_token = token or self.service_token
        return {
            "Authorization": f"Bearer {active_token}",
            "Accept": "application/json",
        }

    async def login_and_get_user(self, username: str, password: str) -> dict:
        """Exchange Mealie username/password for an access token and fetch user profile details."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                token_resp = await client.post(
                    "/api/auth/token",
                    data={"username": username, "password": password},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.RequestError as exc:
                raise MealieUnavailableError("Unable to reach Mealie authentication service") from exc

            if token_resp.status_code in (401, 403):
                raise MealieAuthError("Invalid Mealie username or password")
            if token_resp.status_code >= 500:
                raise MealieUnavailableError(f"Mealie auth error: {token_resp.status_code}")
            token_resp.raise_for_status()

            access_token = token_resp.json().get("access_token")
            if not access_token:
                raise MealieAuthError("No access token returned by Mealie")

            try:
                user_resp = await client.get("/api/users/self", headers=self._headers(access_token))
            except httpx.RequestError as exc:
                raise MealieUnavailableError("Unable to fetch user profile from Mealie") from exc

            if user_resp.status_code in (401, 403):
                raise MealieAuthError("Failed to validate user session with Mealie")
            user_resp.raise_for_status()

            user_data = user_resp.json()
            return {
                "access_token": access_token,
                "user_id": str(user_data["id"]),
                "username": user_data.get("username", username),
                "full_name": user_data.get("fullName") or user_data.get("username", username),
                "household_id": str(user_data.get("householdId", "")),
            }

    async def fetch_all_recipes(self) -> list[dict]:
        """Fetch all recipes using the non-admin planner-bot service token."""
        recipes: list[dict] = []
        page = 1
        per_page = 100

        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            while True:
                try:
                    resp = await client.get(
                        "/api/recipes",
                        params={"page": page, "perPage": per_page},
                        headers=self._headers(),
                    )
                except httpx.RequestError as exc:
                    raise MealieUnavailableError("Unable to connect to Mealie to sync recipes") from exc

                if resp.status_code >= 500:
                    raise MealieUnavailableError(f"Mealie returned {resp.status_code} during recipe sync")
                resp.raise_for_status()

                payload = resp.json()
                items = payload.get("items", [])
                for item in items:
                    tags = [t.get("name", "") for t in item.get("tags", []) if isinstance(t, dict)]
                    categories = [
                        c.get("name", "")
                        for c in (item.get("recipeCategory") or [])
                        if isinstance(c, dict)
                    ]
                    total_time = _parse_duration_minutes(item.get("totalTime"))
                    prep_time = _parse_duration_minutes(item.get("prepTime"))
                    perform_time = _parse_duration_minutes(item.get("performTime"))
                    resolved_minutes = total_time or (
                        (prep_time or 0) + (perform_time or 0) if (prep_time or perform_time) else None
                    )

                    recipes.append(
                        {
                            "mealie_recipe_id": str(item["id"]),
                            "slug": item.get("slug", ""),
                            "name": item.get("name", "Untitled Recipe"),
                            "tags": [t for t in tags if t],
                            "categories": [c for c in categories if c],
                            "prep_time_minutes": resolved_minutes,
                        }
                    )

                total_pages = payload.get("total_pages", 1)
                if page >= total_pages or not items:
                    break
                page += 1

        return recipes

    async def fetch_categories_with_recipes(self) -> list[dict]:
        """Fetch all categories and their member recipe IDs from Mealie."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                resp = await client.get(
                    "/api/organizers/categories",
                    params={"perPage": 500},
                    headers=self._headers(),
                )
            except httpx.RequestError as exc:
                raise MealieUnavailableError("Unable to fetch categories from Mealie") from exc

            if resp.status_code >= 500:
                raise MealieUnavailableError(f"Mealie categories error: {resp.status_code}")
            resp.raise_for_status()

            payload = resp.json()
            items = payload.get("items", payload) if isinstance(payload, dict) else payload
            categories_out: list[dict] = []

            for cat in items:
                if not isinstance(cat, dict):
                    continue
                cat_id = str(cat.get("id") or "")
                cat_slug = str(cat.get("slug") or "")
                cat_name = (cat.get("name") or "").strip()
                if not cat_name:
                    continue

                recipe_ids: list[str] = [
                    str(r["id"]) for r in (cat.get("recipes") or []) if isinstance(r, dict) and r.get("id")
                ]

                # Query /api/recipes filtered by category ID (same filter Mealie's UI uses)
                if not recipe_ids and (cat_id or cat_slug):
                    page = 1
                    while True:
                        rec_resp = await client.get(
                            "/api/recipes",
                            params={"categories": cat_id or cat_slug, "page": page, "perPage": 200},
                            headers=self._headers(),
                        )
                        if rec_resp.status_code != 200:
                            break
                        rec_payload = rec_resp.json()
                        rec_items = rec_payload.get("items", []) if isinstance(rec_payload, dict) else []
                        for r in rec_items:
                            if isinstance(r, dict) and r.get("id"):
                                recipe_ids.append(str(r["id"]))
                        if page >= rec_payload.get("total_pages", 1) or not rec_items:
                            break
                        page += 1

                categories_out.append({"id": cat_id, "name": cat_name, "recipe_ids": recipe_ids})

            return categories_out

    async def get_planned_meals(self, start_date: date, end_date: date, user_token: str | None = None) -> list[dict]:
        """Fetch planned meals in a date window (used to check recent parent recipes for leftover chains)."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                resp = await client.get(
                    "/api/households/mealplans",
                    params={
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "perPage": 200,
                    },
                    headers=self._headers(user_token),
                )
            except httpx.RequestError as exc:
                raise MealieUnavailableError("Unable to fetch meal plans from Mealie") from exc

            if resp.status_code >= 500:
                raise MealieUnavailableError(f"Mealie mealplans error: {resp.status_code}")
            resp.raise_for_status()

            payload = resp.json()
            items = payload.get("items", payload) if isinstance(payload, dict) else payload
            planned = []
            for entry in items:
                recipe = entry.get("recipe") or {}
                recipe_id = entry.get("recipeId") or recipe.get("id")
                title = (recipe.get("name") or entry.get("title") or "").strip()
                if (recipe_id or title) and entry.get("date"):
                    planned.append(
                        {
                            "id": str(entry.get("id", "")),
                            "date": datetime.strptime(entry["date"][:10], "%Y-%m-%d").date(),
                            "entry_type": entry.get("entryType", "dinner"),
                            "recipe_id": str(recipe_id) if recipe_id else "",
                            "recipe_name": title or "Planned Meal",
                            "slug": recipe.get("slug", ""),
                        }
                    )
            return planned

    async def create_meal_plan_entry(
        self,
        plan_date: date,
        entry_type: str,
        recipe_id: str | None,
        user_token: str,
        title: str = "",
    ) -> dict:
        """Write a chosen recipe to Mealie's meal plan using the logged-in user's token."""
        body = {
            "date": plan_date.isoformat(),
            "entryType": entry_type.lower(),
            "recipeId": recipe_id,
            "title": title,
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    "/api/households/mealplans",
                    json=body,
                    headers=self._headers(user_token),
                )
            except httpx.RequestError as exc:
                raise MealieUnavailableError("Unable to write meal plan entry to Mealie") from exc

            if resp.status_code in (401, 403):
                raise MealieAuthError("User token expired or lacks permission to edit Mealie meal plans")
            if resp.status_code >= 500:
                raise MealieUnavailableError(f"Mealie returned {resp.status_code} while creating meal plan")
            resp.raise_for_status()
            return resp.json()

    async def delete_meal_plan_entry(self, plan_id: str, user_token: str) -> None:
        """Delete an existing meal plan entry from Mealie."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                resp = await client.delete(
                    f"/api/households/mealplans/{plan_id}",
                    headers=self._headers(user_token),
                )
            except httpx.RequestError as exc:
                raise MealieUnavailableError("Unable to delete meal plan entry in Mealie") from exc

            if resp.status_code in (401, 403):
                raise MealieAuthError("User token expired or lacks permission to delete Mealie meal plans")
            if resp.status_code == 404:
                return
            if resp.status_code >= 500:
                raise MealieUnavailableError(f"Mealie returned {resp.status_code} while deleting meal plan")
            resp.raise_for_status()

    async def fetch_recipe_image(self, recipe_id: str) -> tuple[bytes, str] | None:
        """Fetch recipe thumbnail bytes from Mealie."""
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            for variant in ("min-original.webp", "original.webp"):
                try:
                    resp = await client.get(
                        f"/api/media/recipes/{recipe_id}/images/{variant}",
                        headers=self._headers(),
                    )
                except httpx.RequestError:
                    return None
                if resp.status_code == 200 and resp.content:
                    return resp.content, resp.headers.get("content-type", "image/webp")
        return None


mealie_client = MealieClient()


async def fetch_household_users() -> list[dict]:
    """Fetch household members using the planner-bot service token."""
    async with httpx.AsyncClient(base_url=mealie_client.base_url, timeout=mealie_client.timeout) as client:
        try:
            resp = await client.get("/api/households/self", headers=mealie_client._headers())
        except httpx.RequestError as exc:
            raise MealieUnavailableError("Unable to fetch household users from Mealie") from exc

        if resp.status_code >= 500:
            raise MealieUnavailableError(f"Mealie household error: {resp.status_code}")
        resp.raise_for_status()

        data = resp.json()
        users = data.get("users", [])
        return [
            {
                "user_id": str(u["id"]),
                "username": u.get("username", ""),
                "full_name": u.get("fullName") or u.get("username", ""),
            }
            for u in users
            if u.get("id")
        ]
