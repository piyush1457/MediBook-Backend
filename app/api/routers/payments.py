"""Payment + webhook routes. Webhook uses HMAC, not JWT."""

import hashlib
import hmac
import json
import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, optional_idempotency_key
from app.core.config import settings
from app.core.errors import NotFoundError, UnauthorizedError, UnprocessableError
from app.models import Payment, User
from app.schemas import PaymentCreate, PaymentOut, WebhookIn
from app.services import payment_service, webhook_service

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "/",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Pay for a booking",
)
def pay(
    body: PaymentCreate,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    idempotency_key: str | None = Depends(optional_idempotency_key),
) -> Payment:
    payment, created = payment_service.create_payment(
        db, user.id, body.booking_id, body.simulate, idempotency_key
    )
    if not created:
        response.status_code = status.HTTP_200_OK  # idempotent replay
    return payment


@router.get("/{payment_id}", response_model=PaymentOut, summary="Get my payment")
def get_payment(
    payment_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Payment:
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise NotFoundError("Payment not found")
    booking = payment.booking  # lazy load; ownership via booking
    if booking is None or booking.user_id != user.id:
        raise NotFoundError("Payment not found")  # 404, not 403 (no leak)
    return payment


def _verify_signature(raw: bytes, signature: str | None) -> None:
    if not signature:
        raise UnauthorizedError("Missing webhook signature")
    expected = hmac.new(
        settings.WEBHOOK_SECRET.encode(), raw, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise UnauthorizedError("Invalid webhook signature")


@router.post("/webhook/", summary="Provider callback (HMAC signed, idempotent)")
async def webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    raw = await request.body()
    _verify_signature(raw, request.headers.get("X-Signature"))
    try:
        data = json.loads(raw.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        raise UnprocessableError("Malformed webhook payload")
    try:
        body = WebhookIn.model_validate(data)
    except ValidationError as exc:
        raise UnprocessableError(f"Malformed webhook payload: {exc.errors()[0]['msg']}")
    return webhook_service.process_webhook(
        db,
        event_id=body.event_id,
        provider_reference=body.provider_reference,
        booking_id=body.booking_id,
        status=body.status,
        amount=body.amount,
        payload=data,
    )
