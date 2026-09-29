"""Auth: signup, duplicate email, login, me, token edge cases."""

import jwt as pyjwt
from datetime import datetime, timedelta, timezone


def test_signup_ok(client):
    r = client.post(
        "/api/v1/auth/signup",
        json={"email": "A@Example.com", "password": "password123", "full_name": "Asha"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "a@example.com"  # lowered
    assert "hashed_password" not in body
    assert body["is_admin"] is False


def test_signup_duplicate_case_insensitive(client):
    client.post(
        "/api/v1/auth/signup",
        json={"email": "dup@example.com", "password": "password123", "full_name": "X"},
    )
    r = client.post(
        "/api/v1/auth/signup",
        json={"email": "DUP@example.com", "password": "password123", "full_name": "Y"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_signup_short_password_rejected(client):
    r = client.post(
        "/api/v1/auth/signup",
        json={"email": "s@example.com", "password": "short", "full_name": "S"},
    )
    assert r.status_code == 422


def test_login_success_and_me(client, make_user):
    make_user(email="login@example.com", password="password123")
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "password123"},
    )
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {r.json()['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "login@example.com"


def test_login_wrong_password_same_error_as_wrong_email(client, make_user):
    make_user(email="real@example.com", password="password123")
    bad_pass = client.post(
        "/api/v1/auth/login",
        json={"email": "real@example.com", "password": "wrongpass1"},
    )
    no_user = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "wrongpass1"},
    )
    assert bad_pass.status_code == 401 and no_user.status_code == 401
    assert bad_pass.json() == no_user.json()  # no user enumeration


def test_me_no_token_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_tampered_token_401(client, make_user, auth_headers):
    user = make_user()
    headers = auth_headers(user)
    token = headers["Authorization"].split()[1]
    bad = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {bad}"}
        ).status_code
        == 401
    )


def test_me_expired_token_401(client, make_user):
    from app.core.config import settings

    user = make_user()
    exp = datetime.now(timezone.utc) - timedelta(minutes=1)
    token = pyjwt.encode(
        {"sub": str(user.id), "exp": int(exp.timestamp())},
        settings.JWT_SECRET,
        algorithm="HS256",
    )
    assert (
        client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )
