"""Booking routes. Ownership enforced; 404 (not 403) for others' bookings."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import pagination
from app.api.deps import get_current_user, get_db
from app.models import Booking, User
from app.schemas import BookingCreate, BookingOut, Page
from app.services import booking_service

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post(
    "",
    response_model=BookingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Book a test",
)
def create_booking(
    body: BookingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Booking:
    return booking_service.create_booking(
        db, user, body.centre_id, body.test_id, body.appointment_at
    )


@router.get("", response_model=Page[BookingOut], summary="List my bookings")
def list_bookings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    status: str | None = Query(
        default=None, pattern="^(PENDING|CONFIRMED|FAILED|CANCELLED)$"
    ),
    limit_offset: tuple[int, int] = Depends(pagination),
) -> Page[BookingOut]:
    limit, offset = limit_offset
    stmt = select(Booking).where(Booking.user_id == user.id)
    count_stmt = (
        select(func.count()).select_from(Booking).where(Booking.user_id == user.id)
    )
    if status:
        stmt = stmt.where(Booking.status == status)
        count_stmt = count_stmt.where(Booking.status == status)
    total = db.execute(count_stmt).scalar_one()
    rows = (
        db.execute(stmt.order_by(Booking.created_at.desc()).limit(limit).offset(offset))
        .scalars()
        .all()
    )
    return Page[BookingOut](
        items=[BookingOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{booking_id}", response_model=BookingOut, summary="Get my booking")
def get_booking(
    booking_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Booking:
    return booking_service.get_user_booking(db, user, booking_id)


@router.post(
    "/{booking_id}/cancel", response_model=BookingOut, summary="Cancel my booking"
)
def cancel_booking(
    booking_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Booking:
    return booking_service.cancel_booking(db, user, booking_id)
