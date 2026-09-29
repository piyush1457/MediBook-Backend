"""Shared route dependencies: DB session, current user, admin guard."""

import uuid
from collections.abc import Generator

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.db.session import SessionLocal
from app.models import User

_bearer = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    db: Session = Depends(get_db),
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    if creds is None or not creds.credentials:
        raise UnauthorizedError("Not authenticated")
    subject = decode_token(creds.credentials)
    try:
        user_id = uuid.UUID(str(subject))
    except ValueError:
        raise UnauthorizedError("Invalid token")
    user = db.get(User, user_id)
    if user is None:
        raise UnauthorizedError("Invalid token")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise ForbiddenError("Admin access required")
    return user


def optional_idempotency_key(
    key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
) -> str | None:
    return key
