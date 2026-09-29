"""Payments: forced outcomes, retry, 409s, idempotency key."""

from sqlalchemy import func, select

from app.models import Payment


def _book(client, headers, centre, test, future):
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
    return r.json()["id"]


def _future():
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


def test_forced_success_confirms_booking(
    client, make_user, auth_headers, seed_offer, db
):
    user = make_user()
    h = auth_headers(user)
    centre, test, _ = seed_offer()
    bid = _book(client, h, centre, test, _future())
    r = client.post(
        "/api/v1/payments/", json={"booking_id": bid, "simulate": "success"}, headers=h
    )
    assert r.status_code == 201
    assert r.json()["status"] == "SUCCESS"
    b = client.get(f"/api/v1/bookings/{bid}", headers=h).json()
    assert b["status"] == "CONFIRMED"


def test_forced_failure_marks_failed_and_retry_succeeds(
    client, make_user, auth_headers, seed_offer
):
    user = make_user()
    h = auth_headers(user)
    centre, test, _ = seed_offer()
    bid = _book(client, h, centre, test, _future())
    assert (
        client.post(
            "/api/v1/payments/",
            json={"booking_id": bid, "simulate": "failure"},
            headers=h,
        ).json()["status"]
        == "FAILED"
    )
    assert client.get(f"/api/v1/bookings/{bid}", headers=h).json()["status"] == "FAILED"
    r = client.post(
        "/api/v1/payments/", json={"booking_id": bid, "simulate": "success"}, headers=h
    )
    assert r.json()["status"] == "SUCCESS"
    assert (
        client.get(f"/api/v1/bookings/{bid}", headers=h).json()["status"] == "CONFIRMED"
    )


def test_pay_confirmed_or_cancelled_409(client, make_user, auth_headers, seed_offer):
    user = make_user()
    h = auth_headers(user)
    centre, test, _ = seed_offer()
    bid = _book(client, h, centre, test, _future())
    client.post(
        "/api/v1/payments/", json={"booking_id": bid, "simulate": "success"}, headers=h
    )
    assert (
        client.post(
            "/api/v1/payments/",
            json={"booking_id": bid, "simulate": "success"},
            headers=h,
        ).status_code
        == 409
    )

    bid2 = _book(client, h, centre, test, _future())
    client.post(f"/api/v1/bookings/{bid2}/cancel", headers=h)
    assert (
        client.post(
            "/api/v1/payments/",
            json={"booking_id": bid2, "simulate": "success"},
            headers=h,
        ).status_code
        == 409
    )


def test_idempotency_key_replays_without_new_row(
    client, make_user, auth_headers, seed_offer, db
):
    user = make_user()
    h = auth_headers(user)
    centre, test, _ = seed_offer()
    bid = _book(client, h, centre, test, _future())
    headers = {**h, "Idempotency-Key": "key-123"}
    first = client.post(
        "/api/v1/payments/",
        json={"booking_id": bid, "simulate": "failure"},
        headers=headers,
    )
    assert first.status_code == 201
    before = db.execute(select(func.count()).select_from(Payment)).scalar_one()
    second = client.post(
        "/api/v1/payments/",
        json={"booking_id": bid, "simulate": "success"},
        headers=headers,
    )
    assert second.status_code == 200  # replay, not a new payment
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "FAILED"  # original result preserved
    after = db.execute(select(func.count()).select_from(Payment)).scalar_one()
    assert before == after


def test_payment_ownership_and_unauth(client, make_user, auth_headers, seed_offer):
    alice = make_user(email="alice2@example.com")
    bob = make_user(email="bob2@example.com")
    centre, test, _ = seed_offer()
    bid = _book(client, auth_headers(alice), centre, test, _future())
    pay_id = client.post(
        "/api/v1/payments/",
        json={"booking_id": bid, "simulate": "success"},
        headers=auth_headers(alice),
    ).json()["id"]
    assert (
        client.get(f"/api/v1/payments/{pay_id}", headers=auth_headers(bob)).status_code
        == 404
    )
    assert client.get(f"/api/v1/payments/{pay_id}").status_code == 401
    # Bob cannot pay for Alice's booking either.
    assert (
        client.post(
            "/api/v1/payments/",
            json={"booking_id": bid, "simulate": "success"},
            headers=auth_headers(bob),
        ).status_code
        == 404
    )
