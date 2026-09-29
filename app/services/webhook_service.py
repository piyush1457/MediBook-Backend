"""Idempotent webhook processing. DB unique constraint wins races, not check-then-insert."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, UnprocessableError
from app.core.logging import get_logger, log_event
from app.models import Payment, WebhookEvent
from app.services.booking_service import lock_booking, transition_booking

log = get_logger("app.webhook")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_event_row(db: Session, event_id: str, payload: dict) -> WebhookEvent | None:
    """Insert first; on unique violation return None (= duplicate, do NOT reprocess)."""
    row = WebhookEvent(event_id=event_id, payload=payload, status="RECEIVED")
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    db.refresh(row)
    return row


def mark_event(
    db: Session, row: WebhookEvent, status: str, reason: str | None = None
) -> None:
    row.status = status
    row.reason = reason
    row.processed_at = _utcnow()
    db.commit()


def process_webhook(
    db: Session,
    event_id: str,
    provider_reference: str,
    booking_id: uuid.UUID,
    status: str,
    amount: Decimal,
    payload: dict,
) -> dict:
    """Apply a provider callback. Always safe to call twice; terminal states never downgrade."""
    row = record_event_row(db, event_id, payload)
    if row is None:
        log_event(log, "webhook_duplicate", event_id=event_id)
        return {"status": "duplicate"}

    booking = lock_booking(db, booking_id)
    if booking is None:
        mark_event(db, row, "FAILED", reason="unknown booking_id")
        raise NotFoundError("Booking not found")
    if Decimal(str(amount)) != Decimal(str(booking.amount)):
        mark_event(db, row, "IGNORED", reason="amount mismatch")
        raise UnprocessableError("Webhook amount does not match booking amount")

    if booking.status == "CANCELLED":
        # Money arrived for a cancelled booking: needs a refund, never re-confirm.
        mark_event(db, row, "IGNORED", reason="booking cancelled; needs refund")
        log.warning(
            f"webhook for CANCELLED booking booking_id={booking.id} event_id={event_id}"
        )
        return {"status": "ignored", "reason": "booking cancelled; needs refund"}
    if booking.status == "CONFIRMED" and status == "FAILED":
        # Out-of-order FAILED after SUCCESS must not downgrade.
        mark_event(db, row, "IGNORED", reason="late FAILED after CONFIRMED")
        log_event(
            log, "webhook_out_of_order", booking_id=str(booking.id), event_id=event_id
        )
        return {"status": "ignored", "reason": "late FAILED after CONFIRMED"}

    existing_pay = db.execute(
        select(Payment).where(Payment.provider_reference == provider_reference)
    ).scalar_one_or_none()
    target = "CONFIRMED" if status == "SUCCESS" else "FAILED"
    if existing_pay is not None:
        # Same provider_reference redelivered with final state: converge booking, no dup.
        if booking.status != target:
            try:
                transition_booking(booking, target)
                db.commit()
            except Exception:
                db.rollback()
                mark_event(
                    db, row, "IGNORED", reason=f"booking already {booking.status}"
                )
                return {
                    "status": "ignored",
                    "reason": f"booking already {booking.status}",
                }
        mark_event(db, row, "PROCESSED", reason="provider_reference already known")
        return {"status": "processed"}

    payment = Payment(
        booking_id=booking.id,
        amount=Decimal(booking.amount),
        status=status,
        provider_reference=provider_reference,
    )
    db.add(payment)
    try:
        transition_booking(booking, target)
        db.commit()
    except IntegrityError:
        db.rollback()
        mark_event(db, row, "IGNORED", reason="conflicting SUCCESS already recorded")
        return {"status": "ignored", "reason": "conflicting SUCCESS already recorded"}
    except Exception as exc:
        db.rollback()
        mark_event(db, row, "IGNORED", reason=str(exc))
        return {"status": "ignored", "reason": str(exc)}

    mark_event(db, row, "PROCESSED")
    log_event(
        log,
        "webhook_processed",
        booking_id=str(booking.id),
        event_id=event_id,
        status=status,
    )
    return {"status": "processed"}
