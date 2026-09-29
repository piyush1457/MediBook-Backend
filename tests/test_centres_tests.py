"""Centres/tests: listing, pagination, filtering, admin-only writes."""

import uuid


def _signup_and_headers(client, email, admin=False):
    r = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password123", "full_name": "N"},
    )
    assert r.status_code == 201
    return r


def test_centre_list_pagination_and_city_filter(
    client, db, seed_offer, make_user, auth_headers
):
    seed_offer()
    for i in range(3):
        from app.models import Centre

        db.add(
            Centre(name=f"Pag {i}", city="Mumbai" if i < 2 else "Delhi", address="a")
        )
    db.commit()
    r = client.get("/api/v1/centres?limit=2&offset=0")
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 2 and body["offset"] == 0
    assert body["total"] >= 4 and len(body["items"]) == 2

    r = client.get("/api/v1/centres?city=mumbai")  # case-insensitive
    assert all(i["city"] == "Mumbai" for i in r.json()["items"])

    r = client.get("/api/v1/centres?search=pAG")
    assert r.json()["total"] >= 3


def test_centre_detail_includes_tests_with_prices(client, seed_offer):
    centre, test, offer = seed_offer(price="499.00")
    r = client.get(f"/api/v1/centres/{centre.id}")
    assert r.status_code == 200
    assert r.json()["tests"][0]["price"] in ("499.00", 499.0, "499")
    assert r.json()["tests"][0]["test_id"] == str(test.id)


def test_test_detail_lists_centres(client, seed_offer):
    centre, test, offer = seed_offer(price="299.00")
    r = client.get(f"/api/v1/tests/{test.id}")
    assert r.status_code == 200
    assert r.json()["centres"][0]["centre_id"] == str(centre.id)


def test_admin_can_create_but_user_gets_403(client, make_user, auth_headers, db):
    admin = make_user(email="adm@example.com", is_admin=True)
    user = make_user(email="u@example.com")
    r = client.post(
        "/api/v1/centres",
        json={"name": "N", "city": "C", "address": "A"},
        headers=auth_headers(user),
    )
    assert r.status_code == 403
    r = client.post(
        "/api/v1/centres",
        json={"name": "N", "city": "C", "address": "A"},
        headers=auth_headers(admin),
    )
    assert r.status_code == 201
    r = client.post(
        "/api/v1/tests",
        json={"name": "T", "description": "d"},
        headers=auth_headers(user),
    )
    assert r.status_code == 403


def test_admin_attach_test_and_duplicate_409(
    client, make_user, auth_headers, seed_offer, db
):
    from app.models import DiagnosticTest

    admin = make_user(email="adm2@example.com", is_admin=True)
    centre, _, _ = seed_offer()
    t = DiagnosticTest(name="Extra", description="d")
    db.add(t)
    db.commit()
    db.refresh(t)
    url = f"/api/v1/centres/{centre.id}/tests"
    r = client.post(
        url, json={"test_id": str(t.id), "price": "100.00"}, headers=auth_headers(admin)
    )
    assert r.status_code == 201, r.text
    r = client.post(
        url, json={"test_id": str(t.id), "price": "100.00"}, headers=auth_headers(admin)
    )
    assert r.status_code == 409


def test_centre_not_found_404(client):
    assert client.get(f"/api/v1/centres/{uuid.uuid4()}").status_code == 404
