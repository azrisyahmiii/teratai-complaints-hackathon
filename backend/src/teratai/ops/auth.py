"""Operations reuse platform sessions, CSRF protection and staff identities."""

from collections.abc import Callable
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, HTTPException

from teratai import db
from teratai.api.auth import ROLES, current_user, mutation_user
from teratai.api.auth import StaffUser as User


def get_user(username: str) -> User | None:
    with db.connect() as con:
        row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if row is None:
        return None
    return User(username=row["username"], role=row["role"], role_label=ROLES[row["role"]],
                approval_limit_myr=row["approval_limit_myr"])


def limit(user: User) -> Decimal | None:
    return Decimal(user.approval_limit_myr) if user.approval_limit_myr is not None else None


def require_role(*roles: str, mutation: bool = True) -> Callable[..., User]:
    def dep(user: Annotated[User, Depends(mutation_user if mutation else current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(403, detail=f"{user.role} can't do this")
        return user
    return dep
