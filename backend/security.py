"""Password hashing and opaque database-backed, revocable cookie sessions."""

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession
from backend.database import get_db
from backend.models import User, Session
from backend.config import get_settings


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return (
        "scrypt$"
        + base64.b64encode(salt).decode()
        + "$"
        + base64.b64encode(digest).decode()
    )


def verify_password(password, stored):
    try:
        kind, salt, expected = stored.split("$")
        if kind != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=16384, r=8, p=1
        )
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


def session_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def set_session(db, user, response):
    token = secrets.token_urlsafe(40)
    db.add(
        Session(
            token_hash=session_hash(token),
            user_id=user.id,
            expires_at=(datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        )
    )
    db.commit()
    response.set_cookie(
        "atlas_session",
        token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        path="/",
    )


def current_user(request: Request, db: DBSession = Depends(get_db)):
    token = request.cookies.get("atlas_session", "")
    record = db.get(Session, session_hash(token)) if token else None
    if not record or record.expires_at <= datetime.now(timezone.utc).isoformat():
        raise HTTPException(401, "请先登录")
    user = db.get(User, record.user_id)
    if not user:
        raise HTTPException(401, "请先登录")
    return user
