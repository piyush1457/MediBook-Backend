# PLAN — EVE Healthcare backend

## Architecture
Single FastAPI service + PostgreSQL 16. Thin routers in `app/api/routers/`,
business rules in `app/services/`, shared cross-cutting code in `app/core/`.
`app/api/deps.py` holds `get_db` / `get_current_user` / `require_admin`.
Domain errors live in `app/core/errors.py` and are mapped to a uniform
`{"error": {"code", "message"}}` shape by handlers registered in `main.py`.

```
Client -> Router (auth/validation only) -> Service (rules + DB tx) -> Models
                                                  |
                                          errors.DomainError -> handler -> JSON
```

No Redis. No background workers: webhook processing is synchronous inside the
request transaction (documented as the thing to move to Celery later).

## Schema
- `users(id UUID, email UNIQUE lowered, hashed_password, full_name, is_admin, created_at, updated_at)`
- `centres(id UUID, name, city INDEX, address, created_at)`
- `diagnostic_tests(id UUID, name UNIQUE, description)`
- `centre_tests(id UUID, centre_id FK, test_id FK, price NUMERIC(10,2) CHECK>=0, UNIQUE(centre_id,test_id))`
- `bookings(id UUID, user_id FK, centre_id FK, test_id FK, centre_test_id FK, appointment_at TIMESTAMPTZ, amount NUMERIC(10,2) CHECK>=0 snapshot, status ENUM str, created_at, updated_at; INDEX(user_id,status))`
- `payments(id UUID, booking_id FK, amount NUMERIC CHECK>=0, status, provider_reference UNIQUE NULLABLE, idempotency_key UNIQUE NULLABLE, created_at, updated_at; PARTIAL UNIQUE(booking_id) WHERE status='SUCCESS')`
- `webhook_events(id UUID, event_id UNIQUE, payload JSON, status, reason NULLABLE, processed_at NULLABLE, created_at)`

WHY notes: price snapshot (price changes must not rewrite history); partial
unique index (DB is the last line of defence against double SUCCESS);
webhook_events (replay/out-of-order safety via DB unique constraint, not check-then-insert).

## Endpoints
- `POST /api/v1/auth/signup` → 201; `POST /api/v1/auth/login` → JWT; `GET /api/v1/auth/me`
- `GET /api/v1/centres?city=&search=&limit=&offset=`; `GET /api/v1/centres/{id}`
- `GET /api/v1/tests?search=&limit=&offset=`; `GET /api/v1/tests/{id}`
- `POST /api/v1/centres`, `POST /api/v1/tests`, `POST /api/v1/centres/{id}/tests` (admin)
- `POST /api/v1/bookings`, `GET /api/v1/bookings?status=`, `GET /api/v1/bookings/{id}`, `POST /api/v1/bookings/{id}/cancel`
- `POST /api/v1/payments/` (+ optional `Idempotency-Key`), `GET /api/v1/payments/{id}`
- `POST /api/v1/payments/webhook/` (HMAC `X-Signature`, no JWT)

## Booking state machine (single source of truth: `transition_booking()`)
PENDING → CONFIRMED | FAILED | CANCELLED; FAILED → CONFIRMED | CANCELLED;
CONFIRMED → CANCELLED; CANCELLED → (terminal). Illegal → `BookingTransitionError` → 409.

## Idempotency / concurrency
- Payments: `Idempotency-Key` lookup before creating; booking row locked with
  `SELECT … FOR UPDATE` (Postgres; no-op on SQLite tests); whole
  payment+booking update in one transaction; partial unique index blocks a
  second SUCCESS even under race.
- Webhook: insert `webhook_events(event_id)` first; `IntegrityError` → duplicate
  (200 `{"status":"duplicate"}`); processing in one tx with booking `FOR UPDATE`;
  upsert payment by `provider_reference`; terminal states never downgraded
  (record IGNORED with reason).

## Test strategy
pytest + FastAPI TestClient. `conftest.py` uses `TEST_DATABASE_URL` Postgres if
set, else SQLite file DB. Per-test truncate (or transaction rollback on Postgres).
Factories for user/centre/test/booking. Threads-based test for concurrent
duplicate webhooks against Postgres (skipped on SQLite). Deterministic payments
via `simulate` field; random path (~80% success) only when omitted.

## Build order
config/db/models/migrations → auth → centres/tests → bookings → payments →
webhook → tests → Docker → README.
