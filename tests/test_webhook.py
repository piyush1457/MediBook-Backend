"""Webhook: HMAC, idempotency, ordering, validation — the most important part."""

import concurrent.futures
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models import Booking, Payment, WebhookEvent
from tests.conftest import sign_webhook, webhook_body


def _book_api(client, headers, centre, test):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    r = client.post(
        "/api/v1/bookings",
        json={
            "centre_id": str(centre.id),
            "test_id": str(test.id),
            "appointment_at": future,
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _post_hook(client, raw: bytes):
    return client.post(
        "/api/v1/payments/webhook/",
        content=raw,
        headers={"Content-Type": "application/json", "X-Signature": sign_webhook(raw)},
    )


def test_valid_success_webhook_confirms(
    client, make_user, auth_headers, seed_offer, db
):
    user = make_user()
    centre, test, _ = seed_offer(price="299.00")
    booking = _book_api(client, auth_headers(user), centre, test)
    raw, _ = webhook_body(
        booking_id=booking["id"],
        status="SUCCESS",
        amount="299.00",
        provider_reference="ref-ok-1",
    )
    r = _post_hook(client, raw)
    assert r.status_code == 200 and r.json()["status"] == "processed"
    db.expire_all()
    assert db.get(Booking, uuid.UUID(booking["id"])).status == "CONFIRMED"


def test_valid_failed_webhook(client, make_user, auth_headers, seed_offer, db):
    user = make_user()
    centre, test, _ = seed_offer(price="299.00")
    booking = _book_api(client, auth_headers(user), centre, test)
    raw, _ = webhook_body(booking_id=booking["id"], status="FAILED", amount="299.00")
    assert _post_hook(client, raw).json()["status"] == "processed"
    db.expire_all()
    assert db.get(Booking, uuid.UUID(booking["id"])).status == "FAILED"


def test_duplicate_event_id_no_reprocessing(
    client, make_user, auth_headers, seed_offer, db
):
    user = make_user()
    centre, test, _ = seed_offer(price="299.00")
    booking = _book_api(client, auth_headers(user), centre, test)
    raw, _ = webhook_body(
        booking_id=booking["id"],
        status="SUCCESS",
        amount="299.00",
        event_id="evt-dup-1",
    )

    def counts():
        db.expire_all()
        pays = db.execute(select(func.count()).select_from(Payment)).scalar_one()
        evts = db.execute(select(func.count()).select_from(WebhookEvent)).scalar_one()
        return pays, evts, db.get(Booking, uuid.UUID(booking["id"])).status

    assert _post_hook(client, raw).json()["status"] == "processed"
    snapshot = counts()
    r = _post_hook(client, raw)
    assert r.status_code == 200 and r.json()["status"] == "duplicate"
    assert counts() == snapshot  # state and row counts unchanged


def test_concurrent_duplicate_deliveries(
    client, make_user, auth_headers, seed_offer, db
):
    """Two identical deliveries racing: one processes, one is a duplicate. No double payment."""
    user = make_user()
    centre, test, _ = seed_offer(price="299.00")
    booking = _book_api(client, auth_headers(user), centre, test)
    raw, _ = webhook_body(
        booking_id=booking["id"],
        status="SUCCESS",
        amount="299.00",
        event_id="evt-race-1",
        provider_reference="ref-race-1",
    )

    def send():
        from fastapi.testclient import TestClient

        from app.api.deps import get_db
        from app.main import create_app
        from tests.conftest import TestingSession

        app = create_app()

        def _override():
            s = TestingSession()
            try:
                yield s
            finally:
                s.close()

        app.dependency_overrides[get_db] = _override
        with TestClient(app) as c:
            return c.post(
                "/api/v1/payments/webhook/",
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": sign_webhook(raw),
                },
            ).json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(r["status"] for r in pool.map(lambda _: send(), range(2)))
    assert results == ["duplicate", "processed"], results
    db.expire_all()
    pays = (
        db.execute(
            select(Payment).where(Payment.booking_id == uuid.UUID(booking["id"]))
        )
        .scalars()
        .all()
    )
    assert len(pays) == 1  # never duplicates
    assert db.get(Booking, uuid.UUID(booking["id"])).status == "CONFIRMED"


def test_bad_signature_401(client, seed_offer):
    raw, _ = webhook_body()
    r = client.post(
        "/api/v1/payments/webhook/",
        content=raw,
        headers={"Content-Type": "application/json", "X-Signature": "deadbeef"},
    )
    assert r.status_code == 401
    assert (
        client.post("/api/v1/payments/webhook/", content=raw).status_code == 401
    )  # missing


def test_out_of_order_failed_after_success_ignored(
    client, make_user, auth_headers, seed_offer, db
):
    user = make_user()
    centre, test, _ = seed_offer(price="299.00")
    booking = _book_api(client, auth_headers(user), centre, test)
    raw_ok, _ = webhook_body(
        booking_id=booking["id"],
        status="SUCCESS",
        amount="299.00",
        event_id="evt-ooo-1",
    )
    assert _post_hook(client, raw_ok).json()["status"] == "processed"
    raw_late, _ = webhook_body(
        booking_id=booking["id"], status="FAILED", amount="299.00", event_id="evt-ooo-2"
    )
    r = _post_hook(client, raw_late)
    assert r.json()["status"] == "ignored"  # must NOT downgrade CONFIRMED
    db.expire_all()
    assert db.get(Booking, uuid.UUID(booking["id"])).status == "CONFIRMED"


def test_unknown_booking_404_but_recorded(client, db):
    raw, payload = webhook_body(
        booking_id=str(uuid.uuid4()), status="SUCCESS", amount="299.00"
    )
    r = _post_hook(client, raw)
    assert r.status_code == 404
    row = db.execute(
        select(WebhookEvent).where(WebhookEvent.event_id == payload["event_id"])
    ).scalar_one()
    assert row.status == "FAILED"  # recorded, not lost


def test_amount_mismatch_ignored(client, make_user, auth_headers, seed_offer, db):
    user = make_user()
    centre, test, _ = seed_offer(price="299.00")
    booking = _book_api(client, auth_headers(user), centre, test)
    raw, payload = webhook_body(
        booking_id=booking["id"], status="SUCCESS", amount="1.00"
    )
    r = _post_hook(client, raw)
    assert r.status_code == 422
    row = db.execute(
        select(WebhookEvent).where(WebhookEvent.event_id == payload["event_id"])
    ).scalar_one()
    assert row.status == "IGNORED"
    db.expire_all()
    assert db.get(Booking, uuid.UUID(booking["id"])).status == "PENDING"  # unchanged


def test_success_for_cancelled_booking_ignored(
    client, make_user, auth_headers, seed_offer, db
):
    user = make_user()
    h = auth_headers(user)
    centre, test, _ = seed_offer(price="299.00")
    booking = _book_api(client, h, centre, test)
    client.post(f"/api/v1/bookings/{booking['id']}/cancel", headers=h)
    raw, _ = webhook_body(booking_id=booking["id"], status="SUCCESS", amount="299.00")
    r = _post_hook(client, raw)
    assert r.json()["status"] == "ignored"  # needs refund, no state change
    db.expire_all()
    assert db.get(Booking, uuid.UUID(booking["id"])).status == "CANCELLED"


def test_malformed_payload_422(client):
    raw = b'{"event_id": 123, "bogus": true}'
    r = client.post(
        "/api/v1/payments/webhook/",
        content=raw,
        headers={"Content-Type": "application/json", "X-Signature": sign_webhook(raw)},
    )
    assert r.status_code == 422
