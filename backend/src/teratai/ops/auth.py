"""Signed-cookie sessions (stdlib hmac) and role checks. No tokens in the body, no third-party auth."""

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from teratai.ops import db, settings


@dataclass(frozen=True)
class User:
    username: str
    name: str
    role: str
    languages: list[str]
    limit: Decimal | None  # None = unlimited


def _sign(payload: str) -> str:
    return hmac.new(settings.secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_cookie(username: str) -> str:
    payload = f"{username}.{int(time.time()) + settings.SESSION_SECONDS}"
    return f"{payload}.{_sign(payload)}"


def get_user(username: str) -> User | None:
    with db.connect() as con:
        r = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if r is None:
        return None
    lim = r["approval_limit_myr"]
    return User(r["username"], r["name"], r["role"], json.loads(r["languages"]),
                Decimal(lim) if lim is not None else None)


def _user_from_cookie(value: str) -> User | None:
    payload, _, sig = value.rpartition(".")
    if not payload or not hmac.compare_digest(sig, _sign(payload)):
        return None
    username, _, expiry = payload.rpartition(".")
    if not expiry.isdigit() or int(expiry) < time.time():
        return None
    return get_user(username)


def authenticate(username: str, password: str) -> User | None:
    with db.connect() as con:
        r = con.execute("SELECT pw_hash FROM users WHERE username=?", (username,)).fetchone()
    if r is None or not db.verify_password(password, r["pw_hash"]):
        return None
    return get_user(username)


def current_user(request: Request) -> User:
    cookie = request.cookies.get(settings.COOKIE)
    user = _user_from_cookie(cookie) if cookie else None
    if user is None:
        raise HTTPException(401, detail="Sign in first")
    return user


def require_role(*roles: str) -> Callable[[User], User]:
    def dep(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(403, detail=f"{user.role} can't do this")
        return user

    return dep


def me(user: User) -> dict[str, object]:
    return {
        "username": user.username, "name": user.name, "role": user.role, "languages": user.languages,
        "approval_limit_myr": f"{user.limit:.2f}" if user.limit is not None else None,
    }
