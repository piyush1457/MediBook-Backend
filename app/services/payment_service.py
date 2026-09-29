"""Simulated payment processing: one transaction, row lock, idempotency key."""

from __future__ import annotations

import random
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger, log_event
from app.models import Booking, Payment
from app.services.booking_service import lock_booking, transition_booking

log = get_logger("app.payments")

PAYABLE = {"PENDING", "FAILED"}


def _outcome(simulate: str | None) -> str:
    if simulate == "success":
        return "SUCCESS"
    if simulate == "failure":
        return "FAILED"
    return "SUCCESS" if random.random() < 0.8 else "FAILED"


def create_payment(
    db: Session,
    user_id: uuid.UUID,
    booking_id: uuid.UUID,
    simulate: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[Payment, bool]:
    """Returns (payment, created_new). Same key + same user replays the original."""
    if idempotency_key:
        existing = db.execute(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            owner = db.get(Booking, existing.booking_id)
            if owner is not None and owner.user_id == user_id:
                return existing, False
            # Key belongs to someone else's payment: fall through and create new
            # (unique constraint on the key will raise a clear 409 below).

    booking = lock_booking(db, booking_id)
    if booking is None or booking.user_id != user_id:
        raise NotFoundError("Booking not found")
    if booking.status == "CONFIRMED":
        raise ConflictError("Booking is already confirmed")
    if booking.status == "CANCELLED":
        raise ConflictError("Booking is cancelled")
    if booking.status not in PAYABLE:
        raise ConflictError(f"Booking in status {booking.status} cannot be paid")

    outcome = _outcome(simulate)
    payment = Payment(
        booking_id=booking.id,
        amount=Decimal(booking.amount),
        status=outcome,
        provider_reference=f"sim_{uuid.uuid4().hex[:16]}",
        idempotency_key=idempotency_key,
    )
    db.add(payment)
    # Single transaction: payment + booking move together so they never diverge.
    transition_booking(booking, "CONFIRMED" if outcome == "SUCCESS" else "FAILED")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Most likely the partial unique index fired: someone already CONFIRMED it.
        raise ConflictError("Booking already has a successful payment")
    db.refresh(payment)
    log_event(
        log,
        "payment_processed",
        booking_id=str(booking.id),
        payment_id=str(payment.id),
        status=outcome,
    )
    return payment, True
