"""Bookings: happy path, snapshot pricing, validation, isolation, cancel rules."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal


def _future(days=1):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_create_booking_happy_path_and_price_snapshot(
    client, make_user, auth_headers, seed_offer, db
):
    user = make_user()
    centre, test, offer = seed_offer(price="299.00")
    r = client.post(
        "/api/v1/bookings",
        json={
            "centre_id": str(centre.id),
            "test_id": str(test.id),
            "appointment_at": _future(),
        },
        headers=auth_headers(user),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "PENDING"
    assert Decimal(str(body["amount"])) == Decimal("299.00")

    # Change the offer price afterwards: booking keeps the snapshot.
    offer.price = Decimal("999.00")
    db.add(offer)
    db.commit()
    r2 = client.get(f"/api/v1/bookings/{body['id']}", headers=auth_headers(user))
    assert Decimal(str(r2.json()["amount"])) == Decimal("299.00")


def test_booking_unoffered_test_404(client, make_user, auth_headers, seed_offer, db):
    from app.models import DiagnosticTest

    user = make_user()
    centre, _, _ = seed_offer()
    other = DiagnosticTest(name="NotOffered", description="d")
    db.add(other)
    db.commit()
    db.refresh(other)
    r = client.post(
        "/api/v1/bookings",
        json={
            "centre_id": str(centre.id),
            "test_id": str(other.id),
            "appointment_at": _future(),
        },
        headers=auth_headers(user),
    )
    assert r.status_code == 404


def test_booking_past_date_422(client, make_user, auth_headers, seed_offer):
    user = make_user()
    centre, test, _ = seed_offer()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = client.post(
        "/api/v1/bookings",
        json={
            "centre_id": str(centre.id),
            "test_id": str(test.id),
            "appointment_at": past,
        },
        headers=auth_headers(user),
    )
    assert r.status_code == 422


def test_booking_ownership_isolation_404(client, make_user, auth_headers, seed_offer):
    alice = make_user(email="alice@example.com")
    bob = make_user(email="bob@example.com")
    centre, test, _ = seed_offer()
    r = client.post(
        "/api/v1/bookings",
        json={
            "centre_id": str(centre.id),
            "test_id": str(test.id),
            "appointment_at": _future(),
        },
        headers=auth_headers(alice),
    )
    bid = r.json()["id"]
    # Bob sees 404 (not 403) for Alice's booking; Alice's list excludes Bob's.
    assert (
        client.get(f"/api/v1/bookings/{bid}", headers=auth_headers(bob)).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/bookings/{bid}/cancel", headers=auth_headers(bob)
        ).status_code
        == 404
    )
    assert (
        client.get("/api/v1/bookings", headers=auth_headers(bob)).json()["total"] == 0
    )


def test_cancel_rules(client, make_user, auth_headers, seed_offer):
    user = make_user()
    centre, test, _ = seed_offer()
    h = auth_headers(user)

    def _book():
        return client.post(
            "/api/v1/bookings",
            json={
                "centre_id": str(centre.id),
                "test_id": str(test.id),
                "appointment_at": _future(),
            },
            headers=h,
        ).json()["id"]

    bid = _book()
    assert (
        client.post(f"/api/v1/bookings/{bid}/cancel", headers=h).json()["status"]
        == "CANCELLED"
    )
    # Cancelling a CANCELLED booking is an illegal transition -> 409.
    assert client.post(f"/api/v1/bookings/{bid}/cancel", headers=h).status_code == 409


def test_cancel_confirmed_booking(client, make_user, auth_headers, seed_offer):
    user = make_user()
    centre, test, _ = seed_offer()
    h = auth_headers(user)
    bid = client.post(
        "/api/v1/bookings",
        json={
            "centre_id": str(centre.id),
            "test_id": str(test.id),
            "appointment_at": _future(),
        },
        headers=h,
    ).json()["id"]
    client.post(
        "/api/v1/payments/", json={"booking_id": bid, "simulate": "success"}, headers=h
    )
    r = client.post(f"/api/v1/bookings/{bid}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"


def test_list_filter_by_status(client, make_user, auth_headers, seed_offer):
    user = make_user()
    centre, test, _ = seed_offer()
    h = auth_headers(user)
    for _ in range(2):
        client.post(
            "/api/v1/bookings",
            json={
                "centre_id": str(centre.id),
                "test_id": str(test.id),
                "appointment_at": _future(),
            },
            headers=h,
        )
    assert client.get("/api/v1/bookings?status=PENDING", headers=h).json()["total"] == 2
    assert (
        client.get("/api/v1/bookings?status=CONFIRMED", headers=h).json()["total"] == 0
    )


def test_malformed_and_missing_booking_ids(client, make_user, auth_headers):
    user = make_user()
    h = auth_headers(user)
    assert client.get("/api/v1/bookings/not-a-uuid", headers=h).status_code == 422
    assert client.get(f"/api/v1/bookings/{uuid.uuid4()}", headers=h).status_code == 404


def test_unauthenticated_booking_access(client, seed_offer):
    centre, test, _ = seed_offer()
    assert client.get("/api/v1/bookings").status_code == 401
    assert (
        client.post(
            "/api/v1/bookings",
            json={
                "centre_id": str(centre.id),
                "test_id": str(test.id),
                "appointment_at": _future(),
            },
        ).status_code
        == 401
    )
