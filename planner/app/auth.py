from fastapi import Cookie, Depends, HTTPException, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import UserProfile

SESSION_COOKIE_NAME = "family_planner_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 14  # 14 days

_serializer = URLSafeTimedSerializer(settings.session_secret, salt="planner-session-v1")

DEFAULT_PROFILES = {
    "justin": {"display_name": "Dad", "initials": "D", "color_code": "#3B82F6"},
    "dad": {"display_name": "Dad", "initials": "D", "color_code": "#3B82F6"},
    "jenesa": {"display_name": "Jenesa", "initials": "J", "color_code": "#EC4899"},
    "henley": {"display_name": "Henley", "initials": "H", "color_code": "#10B981"},
}


def create_session_cookie(response: Response, session_payload: dict) -> None:
    """Sign and attach an HttpOnly, Secure, SameSite=Strict session cookie."""
    signed_token = _serializer.dumps(session_payload)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=signed_token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


def ensure_user_profile(db: Session, user_id: str, username: str, full_name: str) -> UserProfile:
    """Create a default color-coded UserProfile on first login if one does not exist."""
    profile = db.get(UserProfile, user_id)
    if profile is not None:
        return profile

    key = username.strip().lower()
    preset = DEFAULT_PROFILES.get(key)
    if preset:
        display_name = preset["display_name"]
        initials = preset["initials"]
        color_code = preset["color_code"]
    else:
        display_name = full_name.strip() or username.strip()
        initials = display_name[:1].upper() or "U"
        color_code = "#6366F1"

    profile = UserProfile(
        mealie_user_id=user_id,
        display_name=display_name,
        initials=initials,
        color_code=color_code,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def get_current_session(
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict:
    """Validate and decode the signed session cookie for protected endpoints."""
    if not session_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        payload = _serializer.loads(session_cookie, max_age=SESSION_MAX_AGE_SECONDS)
    except SignatureExpired as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired, please log in again",
        ) from exc
    except BadSignature as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session signature",
        ) from exc

    if not payload.get("user_id") or not payload.get("mealie_token"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed session payload",
        )
    return payload


def get_current_user_id(session: dict = Depends(get_current_session)) -> str:
    return str(session["user_id"])
