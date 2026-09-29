"""Booking business rules. Owns the booking state machine (single place)."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BookingTransitionError, NotFoundError, UnprocessableError
from app.core.logging import get_logger, log_event
from app.models import Booking, CentreTest, User

log = get_logger("app.bookings")

# The ONE table of allowed transitions. Illegal -> BookingTransitionError -> 409.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"CONFIRMED", "FAILED", "CANCELLED"},
    "FAILED": {"CONFIRMED", "CANCELLED"},  # retry allowed: new payment can CONFIRM
    "CONFIRMED": {"CANCELLED"},  # refunds out of scope (see README)
    "CANCELLED": set(),  # terminal
}


def transition_booking(booking: Booking, to: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(booking.status, set())
    if to not in allowed:
        raise BookingTransitionError(
            f"Cannot transition booking from {booking.status} to {to}"
        )
    log_event(
        log,
        "booking_transition",
        booking_id=str(booking.id),
        **{"from": booking.status, "to": to},
    )
    booking.status = to
    booking.updated_at = datetime.now(timezone.utc)


def lock_booking(db: Session, booking_id: object) -> Booking | None:
    stmt = select(Booking).where(Booking.id == booking_id)  # type: ignore[arg-type]
    if db.bind and db.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def create_booking(
    db: Session,
    user: User,
    centre_id: object,
    test_id: object,
    appointment_at: datetime,
) -> Booking:
    now = datetime.now(timezone.utc)
    appt = (
        appointment_at
        if appointment_at.tzinfo
        else appointment_at.replace(tzinfo=timezone.utc)
    )
    if appt <= now:
        raise UnprocessableError("appointment_at must be in the future")

    offer = db.execute(
        select(CentreTest).where(
            CentreTest.centre_id == centre_id, CentreTest.test_id == test_id
        )  # type: ignore[arg-type]
    ).scalar_one_or_none()
    if offer is None:
        raise NotFoundError("This centre does not offer this test")

    booking = Booking(
        user_id=user.id,
        centre_id=offer.centre_id,
        test_id=offer.test_id,
        centre_test_id=offer.id,
        appointment_at=appt,
        amount=Decimal(offer.price),  # snapshot server-side price; never trust client
        status="PENDING",
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    log_event(log, "booking_created", booking_id=str(booking.id), user_id=str(user.id))
    return booking


def cancel_booking(db: Session, user: User, booking_id: object) -> Booking:
    """Owner-only cancel. Returns 404 for others' bookings (no existence leak)."""
    booking = lock_booking(db, booking_id)
    if booking is None or booking.user_id != user.id:
        raise NotFoundError("Booking not found")
    transition_booking(booking, "CANCELLED")
    db.commit()
    db.refresh(booking)
    return booking


def get_user_booking(db: Session, user: User, booking_id: object) -> Booking:
    booking = db.get(Booking, booking_id)  # type: ignore[arg-type]
    if booking is None or booking.user_id != user.id:
        raise NotFoundError("Booking not found")
    return booking
