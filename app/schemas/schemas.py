"""Pydantic v2 request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ---------- Auth ----------


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    is_admin: bool


# ---------- Centres & tests ----------


class CentreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    city: str = Field(min_length=1, max_length=120)
    address: str = Field(default="", max_length=2000)


class CentreTestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    test_id: uuid.UUID
    test_name: str
    price: Decimal


class CentreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    city: str
    address: str


class CentreDetailOut(CentreOut):
    tests: list[CentreTestOut] = []


class DiagnosticTestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)


class DiagnosticTestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str


class CentreOfferOut(BaseModel):
    centre_id: uuid.UUID
    centre_name: str
    city: str
    price: Decimal


class DiagnosticTestDetailOut(DiagnosticTestOut):
    centres: list[CentreOfferOut] = []


class AttachTestIn(BaseModel):
    test_id: uuid.UUID
    price: Decimal = Field(gt=0, le=99999999.99)


# ---------- Bookings ----------

BookingStatus = Literal["PENDING", "CONFIRMED", "FAILED", "CANCELLED"]


class BookingCreate(BaseModel):
    centre_id: uuid.UUID
    test_id: uuid.UUID
    appointment_at: datetime


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    centre_id: uuid.UUID
    test_id: uuid.UUID
    appointment_at: datetime
    amount: Decimal
    status: str
    created_at: datetime


# ---------- Payments ----------


class PaymentCreate(BaseModel):
    booking_id: uuid.UUID
    simulate: Literal["success", "failure"] | None = None


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    booking_id: uuid.UUID
    amount: Decimal
    status: str
    provider_reference: str | None = None


class WebhookIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=255)
    provider_reference: str = Field(min_length=1, max_length=255)
    booking_id: uuid.UUID
    status: Literal["SUCCESS", "FAILED"]
    amount: Decimal = Field(ge=0)
    timestamp: datetime
