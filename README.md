# EVE Healthcare — backend

Service for diagnostic test bookings with simulated payments and an idempotent
payment-provider webhook. Small, clean, and well-tested by design: thin routers,
all business rules in `services/`, one uniform error shape.

## 1. Overview and tech choices

| Choice | Why |
|---|---|
| FastAPI | Typed, auto Swagger at `/docs`, TestClient for tests |
| SQLAlchemy 2.0 (typed `Mapped`) | Explicit models, DB constraints where races live |
| Alembic | One committed initial migration (`0001_initial`) |
| Pydantic v2 + pydantic-settings | Request validation (`EmailStr`, `Decimal`) and env-only config |
| PostgreSQL 16 (Docker) | Real FKs, partial unique index, `SELECT … FOR UPDATE` |
| PyJWT + passlib[bcrypt] | Small, standard auth; identical login errors (no user enumeration) |
| pytest + httpx/TestClient | Tests hit the real HTTP layer; Postgres when `TEST_DATABASE_URL` is set, else file SQLite with identical behaviour |
| No Redis / no workers | Deliberately skipped — webhook processing is synchronous in the request transaction (see §9 for the Celery path) |

Layout: `app/main.py` (factory, handlers, request-id logging) · `app/core/`
(config, JWT/hash, JSON logging, domain errors) · `app/db/` · `app/models/`
· `app/schemas/` · `app/api/` (deps + thin routers) · `app/services/`
(`booking_service`, `payment_service`, `webhook_service`).

## 2. Run locally

### Docker path (recommended)

```bash
cp .env.example .env   # then set real secrets
docker compose up --build
# API: http://localhost:8000  Swagger: http://localhost:8000/docs
```

The `api` container runs `alembic upgrade head && python scripts/seed.py` on boot,
so the DB is migrated and seeded automatically.

### Non-Docker path

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# point at local Postgres:
# DATABASE_URL=postgresql+psycopg2://eve:evepass@localhost:5432/eve
alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --reload
```

### Running tests

```bash
pytest tests/ -q                       # SQLite (identical behaviour)
TEST_DATABASE_URL=postgresql+psycopg2://eve:evepass@localhost:5432/eve pytest tests/ -q
```

## 3. Env variables

| Var | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | yes | `…@localhost:5432/eve` | SQLAlchemy URL (app + alembic + seed) |
| `TEST_DATABASE_URL` | no | `""` → SQLite | Real-Postgres test run when set |
| `JWT_SECRET` | yes | `change-me…` | HMAC key for access tokens |
| `JWT_ALGORITHM` | no | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | `60` | Token lifetime |
| `WEBHOOK_SECRET` | yes | `change-me…` | HMAC-SHA256 key for `X-Signature` webhook verification |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_NAME` | yes (seed) | `admin@eve.local` / … | Admin user created by `seed.py` |
| `API_PREFIX` | no | `/api/v1` | Route prefix |
| `LOG_LEVEL` | no | `INFO` | Logging level |

No secrets are committed (`.env.example` holds placeholders only).

## 4. API endpoints

Base: `http://localhost:8000/api/v1`. Errors always look like
`{"error": {"code": "...", "message": "..."}}`.

| Method & path | Auth | Description |
|---|---|---|
| `POST /auth/signup` | – | Register (201; email unique case-insensitive, password ≥ 8) |
| `POST /auth/login` | – | `{access_token, token_type}`; same error for bad email/password |
| `GET /auth/me` | JWT | Current user |
| `GET /centres?city=&search=&limit=&offset=` | – | Paginated centres |
| `GET /centres/{id}` | – | Centre + tests with prices |
| `GET /tests?search=&limit=&offset=` | – | Paginated tests |
| `GET /tests/{id}` | – | Test + offering centres with prices |
| `POST /centres` | admin | Create centre |
| `POST /tests` | admin | Create test |
| `POST /centres/{id}/tests` | admin | Offer test at centre with price |
| `POST /bookings` | JWT | Book `{centre_id, test_id, appointment_at}` → PENDING |
| `GET /bookings?status=&limit=&offset=` | JWT | My bookings only |
| `GET /bookings/{id}` | JWT | My booking (others' → 404) |
| `POST /bookings/{id}/cancel` | JWT | Cancel mine (PENDING/CONFIRMED only) |
| `POST /payments/` | JWT | Pay; `{"booking_id", "simulate": "success"/"failure"/null}` + optional `Idempotency-Key` |
| `GET /payments/{id}` | JWT | My payment (others' → 404) |
| `POST /payments/webhook/` | HMAC | Provider callback, no JWT (§7) |
| `GET /health` | – | Health check |

### Walkthrough (curl)

```bash
B=http://localhost:8000/api/v1
# signup + login
curl -s -X POST $B/auth/signup -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"password123","full_name":"Demo"}'
TOKEN=$(curl -s -X POST $B/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"password123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
# centres -> pick ids
curl -s "$B/centres?limit=2" | python -m json.tool
CID=$(curl -s "$B/centres?limit=10" | python -c "import sys,json;d=json.load(sys.stdin);print(d['items'][0]['id'])")
DETAIL=$(curl -s $B/centres/$CID); echo $DETAIL | python -m json.tool
TID=$(echo $DETAIL | python -c "import sys,json;print(json.load(sys.stdin)['tests'][0]['test_id'])")
# book (amount is snapshotted server-side; client never sends a price)
BID=$(curl -s -X POST $B/bookings -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"centre_id\":\"$CID\",\"test_id\":\"$TID\",\"appointment_at\":\"2030-01-01T10:00:00Z\"}" | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
# pay (forced failure to demo retry, then success)
curl -s -X POST $B/payments/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"booking_id\":\"$BID\",\"simulate\":\"failure\"}"
curl -s -X POST $B/payments/ -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"booking_id\":\"$BID\",\"simulate\":\"success\"}"
# webhook with HMAC signature (or use scripts/send_webhook.py)
python - <<'EOF'
import hashlib, hmac, json, urllib.request
secret = "change-me-webhook-secret"  # $WEBHOOK_SECRET
payload = {"event_id":"evt-demo-1","provider_reference":"demo-ref-1",
           "booking_id":"$BID","status":"SUCCESS","amount":"349.00",
           "timestamp":"2026-01-01T00:00:00+00:00"}
raw = json.dumps(payload).encode()
sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
req = urllib.request.Request("http://localhost:8000/api/v1/payments/webhook/",
    data=raw, headers={"Content-Type":"application/json","X-Signature":sig})
print(urllib.request.urlopen(req).read().decode())
EOF
```

`scripts/send_webhook.py` does the same thing from the CLI:
`python scripts/send_webhook.py --booking-id <uuid> --status SUCCESS --amount 349.00`.

## 5. Database schema

Tables: `users`, `centres`, `diagnostic_tests`, `centre_tests` (join + price),
`bookings` (price snapshot + status), `payments`, `webhook_events`.

```mermaid
erDiagram
    users ||--o{ bookings : "books"
    centres ||--o{ centre_tests : "offers via"
    diagnostic_tests ||--o{ centre_tests : "offered via"
    centre_tests ||--o{ bookings : "priced by"
    bookings ||--o{ payments : "paid by"
    bookings ||--o{ webhook_events : "notified (logical)"
    users { uuid id PK; string email UK; string hashed_password; string full_name; bool is_admin }
    centres { uuid id PK; string name; string city; string address }
    diagnostic_tests { uuid id PK; string name UK; string description }
    centre_tests { uuid id PK; uuid centre_id FK; uuid test_id FK; numeric price }
    bookings { uuid id PK; uuid user_id FK; uuid centre_id FK; uuid test_id FK; uuid centre_test_id FK; timestamptz appointment_at; numeric amount; string status }
    payments { uuid id PK; uuid booking_id FK; numeric amount; string status; string provider_reference UK; string idempotency_key UK }
    webhook_events { uuid id PK; string event_id UK; json payload; string status; string reason }
```

Key constraints / indexes and WHY:

- `centre_tests UNIQUE(centre_id, test_id)` — a price is per (centre, test) pair.
- `bookings.amount` is a **snapshot** of `centre_tests.price` at booking time, never
  client-supplied — later price edits must not rewrite history (tested).
- Partial unique index `UNIQUE(booking_id) WHERE status='SUCCESS'` on payments —
  the DB itself forbids a second SUCCESS payment even if two requests race past
  the service-layer check (plus `sqlite_where` so SQLite tests behave the same).
- `webhook_events.event_id UNIQUE` — duplicate/out-of-order deliveries are decided
  by the unique constraint (insert-first), never check-then-insert.
- `CHECK (amount >= 0)` / `CHECK (price >= 0)` — money is `Numeric(10,2)`/`Decimal`
  everywhere, never float.
- Indexes on FKs, `centres(city)`, names for search, and `bookings(user_id, status)`
  for the list endpoint. All timestamps timezone-aware UTC.

## 6. Booking state machine + flows

Single source of truth: `ALLOWED_TRANSITIONS` in `app/services/booking_service.py`
(`transition_booking()`); illegal moves raise `BookingTransitionError` → HTTP 409.

```mermaid
stateDiagram-v2
    [*] --> PENDING : POST /bookings
    PENDING --> CONFIRMED : payment/webhook SUCCESS
    PENDING --> FAILED : payment/webhook FAILED
    PENDING --> CANCELLED : owner cancels
    FAILED --> CONFIRMED : retry payment SUCCESS
    FAILED --> CANCELLED : owner cancels
    CONFIRMED --> CANCELLED : owner cancels (no refund — out of scope)
    CANCELLED --> [*]
```

Payment/webhook flow:

```mermaid
flowchart TD
    A[POST /bookings → PENDING] --> B[POST /payments/]
    B -->|lock booking FOR UPDATE, one tx| C{outcome?}
    C -->|SUCCESS| D[booking CONFIRMED]
    C -->|FAILED| E[booking FAILED → retry allowed]
    F[POST /payments/webhook/ + HMAC] --> G{event_id known?}
    G -->|yes| H[200 duplicate, no reprocessing]
    G -->|no| I[lock booking, upsert payment by provider_reference]
    I --> J{terminal/conflict?}
    J -->|CONFIRMED + late FAILED| K[IGNORED, no downgrade]
    J -->|CANCELLED + SUCCESS| L[IGNORED needs-refund, no state change]
    J -->|else| M[apply transition, PROCESSED]
```

## 7. Idempotency and concurrency

- **Payments (`Idempotency-Key`)**: the key is stored unique on `payments`. Same key
  + same user replays the original row with HTTP 200 and creates nothing new
  (different outcome requested later still returns the *original* result — tested).
- **Double-payment guard, two layers**: (1) service locks the booking row
  (`SELECT … FOR UPDATE` on Postgres) and applies payment + booking transition in
  **one transaction**; (2) the partial unique index rejects a second SUCCESS row
  even under a true race (`IntegrityError` → 409).
- **Webhook**: insert `webhook_events(event_id)` **first**; a unique violation means
  duplicate → `200 {"status":"duplicate"}` with zero reprocessing. Two concurrent
  identical deliveries therefore collapse to one `PROCESSED` + one `duplicate`
  (covered by a threaded test against real Postgres). Processing itself holds the
  booking lock and upserts the payment by `provider_reference`, so redelivery with
  the same reference converges instead of duplicating. Terminal states are never
  downgraded: late FAILED after CONFIRMED → IGNORED; SUCCESS for CANCELLED →
  IGNORED/needs-refund with a warning log. Unknown booking → 404 but still
  recorded; amount mismatch → 422 + IGNORED. Accepted/duplicate/ignored events
  always return 2xx so the provider stops retrying.
- **Signature**: `hmac.compare_digest(HMAC_SHA256(raw_body), X-Signature)`; the raw
  bytes (not re-serialized JSON) are signed. Bad/missing signature → 401, no JWT.

## 8. Assumptions

- Single currency (INR); amounts are `Decimal`, no FX.
- No refunds: cancelling a CONFIRMED booking just marks CANCELLED.
- Privacy over precision: other users' bookings/payments return **404, not 403**,
  so IDs can't be probed for existence.
- One appointment per slot is **not** enforced (no capacity model) — capacity/slots
  are listed under §9.
- Email uniqueness is case-insensitive (stored lowercased).
- `simulate: null` on payments means random ~80% success (production-like); tests
  always force the outcome.
- Rate limiting on `/auth/login` was skipped as an optional bonus (see §9).

## 9. What I would improve with more time

- Celery + Redis webhook queue with retries/backoff and a dead-letter queue;
  outbox pattern for payment→booking side effects.
- Slot capacity/availability per centre (unique slot holds, overbooking guard).
- Refunds (Razorpay/Stripe reversal) instead of plain CANCELLED.
- Redis caching for centre/test listings; slowapi rate limiting on login; refresh
  tokens + rotation.
- Observability: OpenTelemetry traces, Prometheus metrics, alerting on webhook
  IGNORED/FAILED rates.
- CI (lint → migrate → pytest on Postgres service → build) and stricter PII
  redaction tests for logs.
