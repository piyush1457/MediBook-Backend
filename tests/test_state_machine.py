"""Unit tests for the booking state machine (single source of truth)."""

import pytest

from app.core.errors import BookingTransitionError
from app.models import Booking
from app.services.booking_service import ALLOWED_TRANSITIONS, transition_booking


def _booking(status: str) -> Booking:
    return Booking(status=status)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "frm,to",
    [
        ("PENDING", "CONFIRMED"),
        ("PENDING", "FAILED"),
        ("PENDING", "CANCELLED"),
        ("FAILED", "CONFIRMED"),
        ("FAILED", "CANCELLED"),
        ("CONFIRMED", "CANCELLED"),
    ],
)
def test_legal_transitions(frm: str, to: str):
    b = _booking(frm)
    transition_booking(b, to)
    assert b.status == to


@pytest.mark.parametrize(
    "frm,to",
    [
        ("CONFIRMED", "PENDING"),
        ("CONFIRMED", "FAILED"),
        ("CANCELLED", "PENDING"),
        ("CANCELLED", "CONFIRMED"),
        ("FAILED", "PENDING"),
        ("PENDING", "PENDING"),
    ],
)
def test_illegal_transitions_raise(frm: str, to: str):
    with pytest.raises(BookingTransitionError):
        transition_booking(_booking(frm), to)


def test_transition_table_documents_failed_retry():
    assert ALLOWED_TRANSITIONS["FAILED"] == {"CONFIRMED", "CANCELLED"}
    assert ALLOWED_TRANSITIONS["CANCELLED"] == set()
