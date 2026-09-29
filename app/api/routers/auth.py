"""Auth routes: signup, login, me. Routers stay thin; hashing/JWT in core/security."""

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.errors import UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas import LoginIn, SignupIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_FAILED = "Invalid email or password"  # identical for both cases (no enumeration)


@router.post(
    "/signup",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
def signup(body: SignupIn, db: Session = Depends(get_db)) -> User:
    from app.core.errors import ConflictError

    email = body.email.strip().lower()
    exists = db.execute(
        select(User).where(func.lower(User.email) == email)
    ).scalar_one_or_none()
    if exists is not None:
        raise ConflictError("Email is already registered")
    user = User(
        email=email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name.strip(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenOut, summary="Log in and get a JWT")
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    email = body.email.strip().lower()
    user = db.execute(
        select(User).where(func.lower(User.email) == email)
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.hashed_password):
        raise UnauthorizedError(_LOGIN_FAILED)
    return TokenOut(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserOut, summary="Current user")
def me(user: User = Depends(get_current_user)) -> User:
    return user
