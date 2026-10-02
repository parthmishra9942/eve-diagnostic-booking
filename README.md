# EVE Diagnostic Booking Service

> **Engineered by [Parth Mishra](https://github.com/parthmishra9942)**  
> *Final-Year B.Tech Computer Science & Engineering (AI/ML) @ VIT Bhopal University*  
> **Contact:** [Email](mailto:parthmishra9942@gmail.com) | [LinkedIn](https://linkedin.com/in/parth-mishra-4b7578242) | [GitHub](https://github.com/parthmishra9942)

Backend service for **diagnostic test bookings with simulated payments and an idempotent payment webhook** built for the EVE Healthcare SDE Intern hiring assignment.

[![Python 3.12](https://img.shields.io/badge/Python-3.11%20%7C%203.12-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://docker.com)
[![Pytest](https://img.shields.io/badge/Pytest-Asyncio%20Passed-brightgreen.svg)](tests/)

**Key Highlights:** Clean Layered Architecture · Pessimistic Row Locking (`SELECT ... FOR UPDATE`) · Event Ledger Idempotency Key · Strict State Machine · Redis Cache with Fail-Open · SlowAPI Rate Limiting · Zero Mocking Leaks.

---

## Contents
1. [Quick start](#quick-start) (Docker or local virtualenv)
2. [Architecture](#system-architecture)
3. [Database design / ER diagram](#database-design)
4. [API reference + curl walkthrough](#api-reference)
5. [Idempotency & concurrency deep-dive](#idempotency--concurrency-design-deep-dive)
6. [Edge cases handled](#edge-cases-handled)
7. [Testing](#testing)
8. [Assumptions](#assumptions) · [Future improvements](#what-id-improve-with-more-time)

---

## Quick start

### Option A — Docker Compose (recommended)
```bash
docker-compose up --build
```
| Service    | URL / port                         |
|------------|------------------------------------|
| API        | http://localhost:8000              |
| Swagger UI | http://localhost:8000/docs         |
| ReDoc      | http://localhost:8000/redoc        |
| PostgreSQL | localhost:5432 (`postgres`/`postgres`, db `eve_diagnostics`) |
| Redis      | localhost:6379                     |

The API container runs `alembic upgrade head` on start and bootstraps an admin user
(`admin@example.com` / `Admin12345`, set via `ADMIN_EMAIL` / `ADMIN_PASSWORD` in `docker-compose.yml`).

### Option B — local virtualenv
Requires Python 3.12, PostgreSQL and (optionally) Redis running locally.
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env                 # adjust DATABASE_URL / REDIS_URL if needed
createdb eve_diagnostics             # or any way you create the DB
alembic upgrade head
uvicorn app.main:app --reload
```
Redis is optional: if it is down, the API keeps working (cache misses, in-memory rate limiting) and logs a warning.

### One-Command Database Seeding (Recommended for Evaluation)
To populate realistic diagnostic centres (Apollo, Dr. Lal PathLabs, SRL, Max Healthcare), medical tests (CBC, Lipid Profile, HbA1c, Thyroid, MRI, Chest X-Ray), prices, and sample patient bookings:

```bash
# Via Docker:
docker-compose exec api python -m scripts.seed

# OR locally:
python -m scripts.seed
```

**Pre-Configured Demo Credentials:**
- **Admin User:** `admin@example.com` / `Admin12345` (Full access to manage centres and tests)
- **Staff User:** `staff@example.com` / `Staff12345`
- **Patient User:** `patient@example.com` / `Patient12345` (Pre-loaded with sample bookings)

### Postman Collection
A complete, ready-to-import Postman collection is included in [`docs/eve_diagnostics_postman_collection.json`](docs/eve_diagnostics_postman_collection.json).
Import it into Postman or Thunder Client to test the end-to-end patient booking and webhook lifecycle in seconds.

### Configuration
All settings are environment variables (see [`.env.example`](.env.example) and `app/core/config.py`).
Notable ones: `JWT_SECRET_KEY`, `WEBHOOK_SECRET`, `PAYMENT_SUCCESS_RATE` (default `0.9`),
`WEBHOOK_AUTO_DISPATCH`, `WEBHOOK_DISPATCH_DELAY_SECONDS`, `AUTH_RATE_LIMIT`, `CACHE_TTL_SECONDS`.

---

## System architecture

```mermaid
flowchart LR
    Client([Client / Swagger]) -->|HTTPS + Bearer JWT| MW

    subgraph API["FastAPI application (async)"]
        MW["Middleware<br/>request_id · JSON logs · timing"] --> RL["SlowAPI rate limiter"]
        RL --> R["Routers /api/v1<br/>auth · centres · tests · bookings · payments · webhooks"]
        R --> DEP["Dependencies<br/>JWT auth · RBAC"]
        R --> S["Services<br/>AuthService · CatalogService · BookingService<br/>PaymentService · WebhookService"]
        S --> M["SQLAlchemy 2.0 async models"]
    end

    M --> PG[("PostgreSQL<br/>row locks · unique constraints")]
    R -. "centre list cache (fail-open)" .-> RD[("Redis<br/>cache + rate-limit store")]
    RL -. counters .-> RD

    PAY["POST /payments<br/>simulated gateway"] -->|"BackgroundTask<br/>signed event (retries)"| WH["POST /payments/webhook<br/>idempotent"]
    WH --> S
```

**Layering** (dependencies only point downwards):

```
app/
├── api/        deps.py (auth, RBAC) · v1/ routers — thin HTTP layer, no business logic
├── core/       config · security (JWT, bcrypt, HMAC) · database · cache · rate_limit · logging · exceptions
├── models/     SQLAlchemy ORM: User, Centre, DiagnosticTest, CentreTest, Booking, Payment, WebhookEvent
├── schemas/    Pydantic v2 request/response models + validation rules
├── services/   AuthService · CatalogService · BookingService · PaymentService · WebhookService
└── main.py     app factory, middleware, exception handlers, lifespan
tests/          unit + integration tests          alembic/  migrations
```

### Booking state machine
```mermaid
stateDiagram-v2
    [*] --> PENDING: POST /bookings
    PENDING --> CONFIRMED: webhook SUCCESS
    PENDING --> FAILED: webhook FAILED
    PENDING --> CANCELLED: POST /cancel
    CONFIRMED --> CANCELLED: POST /cancel
    FAILED --> [*]
    CANCELLED --> [*]
```
Only `PENDING` bookings are moved by payment events. `CONFIRMED` never regresses to `FAILED` or is re-confirmed;
`FAILED` and `CANCELLED` are terminal.

### Payment flow
```mermaid
sequenceDiagram
    participant U as User
    participant API as POST /payments
    participant GW as Simulated gateway
    participant WH as POST /payments/webhook
    participant DB as PostgreSQL
    U->>API: booking_id (JWT)
    API->>DB: lock booking (FOR UPDATE), validate owner + state
    API->>GW: simulate (90% success / forced via ?simulate=)
    API->>DB: INSERT payment (txn_id, SUCCESS|FAILED)
    API-->>U: 201 payment
    API--)WH: background task: signed event (HMAC)
    WH->>DB: lock booking, dedupe event_id, apply transition, record event
    U->>DB: GET /bookings/{id} → CONFIRMED | FAILED
```
The webhook is the **single writer of booking state** after a payment, exactly as with a real provider
(the result of `POST /payments` is reported asynchronously; poll `GET /bookings/{id}`).

---

## Database design

```mermaid
erDiagram
    USERS ||--o{ BOOKINGS : makes
    CENTRES ||--o{ CENTRE_TESTS : offers
    DIAGNOSTIC_TESTS ||--o{ CENTRE_TESTS : "offered via"
    CENTRES ||--o{ BOOKINGS : "booked at"
    DIAGNOSTIC_TESTS ||--o{ BOOKINGS : "booked for"
    BOOKINGS ||--o{ PAYMENTS : "paid by"
    BOOKINGS ||--o{ WEBHOOK_EVENTS : "updated by"

    USERS {
        int id PK
        string email UK
        string full_name
        string hashed_password
        enum role "USER|STAFF|ADMIN"
        bool is_active
        timestamptz created_at
    }
    CENTRES {
        int id PK
        string name
        string location
        string contact
        bool is_active
        timestamptz created_at
    }
    DIAGNOSTIC_TESTS {
        int id PK
        string name UK
        text description
        string category
    }
    CENTRE_TESTS {
        int centre_id PK,FK
        int test_id PK,FK
        numeric price "CHECK > 0"
        int turnaround_hours "CHECK > 0"
        timestamptz updated_at
    }
    BOOKINGS {
        int id PK
        int user_id FK
        int centre_id FK
        int test_id FK
        timestamptz appointment_datetime
        numeric amount "price snapshot"
        enum status "PENDING|CONFIRMED|FAILED|CANCELLED"
        timestamptz created_at
        timestamptz updated_at
    }
    PAYMENTS {
        int id PK
        int booking_id FK
        string transaction_id UK
        numeric amount
        enum status "SUCCESS|FAILED"
    }
    WEBHOOK_EVENTS {
        int id PK
        string event_id UK "idempotency key"
        int booking_id FK
        string transaction_id
        enum status
        numeric amount
        enum outcome "APPLIED|IGNORED"
        json payload
        timestamptz processed_at
    }
```

Design notes
* **`centre_tests`** is the many-to-many association (composite PK `(centre_id, test_id)`) carrying the per-centre `price` and `turnaround_hours`.
* **`bookings.amount`** is a **price snapshot** taken at booking time; later price changes never affect existing bookings.
* **Money** is `NUMERIC(10,2)` / `Decimal` end-to-end (never float).
* Enums are `VARCHAR + CHECK` constraints (portable, no native PG enum migrations); datetimes are `timestamptz`, normalised to UTC.
* Indexes on search columns (`centres.name/location`), `bookings(user_id, id)`, `bookings.status`, `payments.booking_id`; uniques on `users.email`, `payments.transaction_id`, `webhook_events.event_id`.
* All FKs are `RESTRICT` (bookings/payments are financial records) except `centre_tests`, which cascades.

---

## API reference

Interactive docs: **`/docs`** (click *Authorize* and paste the JWT). Errors share one envelope:
`{"error": {"code", "message", "request_id", "details"?}}`.

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/auth/signup` | – | Register (always role `USER`) |
| POST | `/api/v1/auth/login` | – | Returns JWT |
| GET | `/api/v1/auth/me` | user | Current profile |
| GET | `/api/v1/centres` | – | Search `name`, `location`; `limit` (1-100), `offset`; Redis-cached |
| POST | `/api/v1/centres` | staff/admin | Create centre |
| GET | `/api/v1/centres/{id}` | – | Centre detail |
| GET | `/api/v1/centres/{id}/tests` | – | Tests offered, with price + turnaround |
| POST | `/api/v1/centres/{id}/tests` | staff/admin | Offer a test at a price |
| PUT | `/api/v1/centres/{id}/tests/{test_id}` | staff/admin | Change price/turnaround |
| GET / POST | `/api/v1/tests` | – / staff | Test catalogue (`category`, `name`, pagination) |
| POST | `/api/v1/bookings` | user | Create booking (price locked, `PENDING`) |
| GET | `/api/v1/bookings` | user | **Own** bookings only (`status`, pagination) |
| GET | `/api/v1/bookings/{id}` | owner | 404 if missing, **403 if not owner** |
| POST | `/api/v1/bookings/{id}/cancel` | owner | Allowed from `PENDING`/`CONFIRMED`, else 409 |
| POST | `/api/v1/payments?simulate=success\|failed\|random` | owner | Simulated payment; default random (90% success) |
| POST | `/api/v1/payments/webhook` | HMAC signature | Idempotent provider callback |
| GET | `/health` | – | DB + cache status |

### curl walkthrough (Docker defaults)
```bash
B=http://localhost:8000/api/v1; J='Content-Type: application/json'

# 1. Admin sets up the catalogue
ADMIN=$(curl -s -X POST $B/auth/login -H "$J" \
  -d '{"email":"admin@example.com","password":"Admin12345"}' | jq -r .access_token)
CENTRE=$(curl -s -X POST $B/centres -H "$J" -H "Authorization: Bearer $ADMIN" \
  -d '{"name":"City Labs","location":"Indore","contact":"+91-731-0000000"}' | jq .id)
TEST=$(curl -s -X POST $B/tests -H "$J" -H "Authorization: Bearer $ADMIN" \
  -d '{"name":"Complete Blood Count","category":"Hematology"}' | jq .id)
curl -s -X POST $B/centres/$CENTRE/tests -H "$J" -H "Authorization: Bearer $ADMIN" \
  -d "{\"test_id\":$TEST,\"price\":499.50,\"turnaround_hours\":12}"

# 2. A patient signs up, logs in and browses
curl -s -X POST $B/auth/signup -H "$J" \
  -d '{"email":"asha@example.com","full_name":"Asha Verma","password":"Passw0rd123"}'
TOKEN=$(curl -s -X POST $B/auth/login -H "$J" \
  -d '{"email":"asha@example.com","password":"Passw0rd123"}' | jq -r .access_token)
curl -s "$B/centres?location=indore&limit=10&offset=0"
curl -s $B/centres/$CENTRE/tests

# 3. Book (appointment must be in the future) → PENDING, amount locked at 499.5
BOOKING=$(curl -s -X POST $B/bookings -H "$J" -H "Authorization: Bearer $TOKEN" \
  -d "{\"centre_id\":$CENTRE,\"test_id\":$TEST,\"appointment_datetime\":\"2027-01-15T10:00:00Z\"}" | jq .id)

# 4. Pay (force success for the demo; omit ?simulate for a random 90% outcome)
curl -s -X POST "$B/payments?simulate=success" -H "$J" -H "Authorization: Bearer $TOKEN" \
  -d "{\"booking_id\":$BOOKING}"
sleep 1; curl -s $B/bookings/$BOOKING -H "Authorization: Bearer $TOKEN"     # → CONFIRMED

# 5. Cancel / list
curl -s -X POST $B/bookings/$BOOKING/cancel -H "Authorization: Bearer $TOKEN"
curl -s "$B/bookings?status=CANCELLED" -H "Authorization: Bearer $TOKEN"
```

### Calling the webhook manually
The signature is `HMAC-SHA256(WEBHOOK_SECRET, "event_id|booking_id|transaction_id|status|amount_2dp")` (hex).
```bash
SECRET=dev-only-webhook-secret   # WEBHOOK_SECRET from docker-compose.yml
EVENT=evt_manual_1; STATUS=SUCCESS; AMOUNT=499.50; TXN=<transaction_id from POST /payments>
SIG=$(printf '%s' "$EVENT|$BOOKING|$TXN|$STATUS|$AMOUNT" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
curl -s -X POST $B/payments/webhook -H "$J" -d "{
  \"event_id\":\"$EVENT\",\"booking_id\":$BOOKING,\"transaction_id\":\"$TXN\",
  \"status\":\"$STATUS\",\"amount\":$AMOUNT,\"signature\":\"$SIG\"}"
# first delivery : {"status":"processed", "booking_status":"CONFIRMED", "outcome":"APPLIED", ...}
# any replay     : {"status":"already_processed","booking_id":..., ...}   (HTTP 200)
```
(For a booking already settled by the automatic background webhook, a fresh `event_id` returns `processed` with `outcome: "IGNORED"`; replaying the auto-dispatched event `evt_<transaction_id>` returns `already_processed`.
To drive webhooks entirely by hand, start the API with `WEBHOOK_AUTO_DISPATCH=false`.)

---

## Idempotency & concurrency design deep-dive

Payment providers deliver webhooks **at least once**: retries, network timeouts and duplicate deliveries are normal, and
deliveries for the same booking can arrive **concurrently**. The processor in `app/services/webhook_service.py`
is designed so that *N deliveries of the same event produce exactly the effect of one*.

### Three independent layers

**1. Event de-duplication — `UNIQUE(webhook_events.event_id)`**
Every processed event is recorded in `webhook_events` *in the same transaction* as the state change. The unique constraint
is the ultimate arbiter: whatever happens at the application level, the database can never hold two rows for one `event_id`.
Replays answer `200 {"status":"already_processed", ...}` and **do not re-run business logic** (no state change, no new payment/event rows).

**2. Pessimistic row lock — `SELECT … FROM bookings WHERE id=:id FOR UPDATE`** (`with_for_update()`)
Without a lock, two concurrent identical deliveries both pass the "have I seen this event?" check, both apply the
transition, and one of them fails late (or worse, both succeed against different snapshots). With the lock:

```
T1: BEGIN; check event (none); LOCK booking ── holds lock ──► apply → INSERT event → COMMIT
T2: BEGIN; check event (none); LOCK booking ──── waits ──────────────────────────► lock acquired
                                                         re-check event → FOUND → return already_processed
```
The crucial detail is the **re-check after acquiring the lock** (PostgreSQL's default `READ COMMITTED` gives each
statement a fresh snapshot, so T2 sees T1's committed event). T2 never touches booking state.
The same lock is taken by `cancel` and by `POST /payments`, so a cancellation racing a webhook is serialised too.

**3. State-transition guard (monotonic state machine)**
Even a *different* event for the same booking can't corrupt state. Only `PENDING` bookings are moved:

| Booking is | Event `SUCCESS` | Event `FAILED` |
|---|---|---|
| `PENDING` | → `CONFIRMED` | → `FAILED` |
| `CONFIRMED` | ignored (no re-confirm) | ignored (**no regression**) |
| `FAILED` / `CANCELLED` | ignored | ignored |

Ignored events are still recorded (`outcome = IGNORED`) so they stay idempotent and auditable.

### Defence in depth / safety nets
* **Unique-violation fallback:** if a duplicate slips past both checks (e.g. the same `event_id` replayed against a different booking id, so the row locks differ), the `INSERT` hits the constraint, the transaction rolls back untouched and the handler returns `already_processed`.
* **Validation before consumption:** bad signature (401), unknown booking (404), unknown `transaction_id` for that booking (404) and amount mismatch (400) are rejected *before* the event id is stored, so a legitimate later retry of a corrected delivery is not blocked.
* **Authenticity:** HMAC-SHA256 signature, constant-time comparison (`hmac.compare_digest`).
* **Retries are safe:** the simulated provider dispatch retries transient failures with exponential backoff precisely because processing is idempotent; business rejections are not retried.
* **Verified by tests:** `tests/test_webhook_idempotency.py` fires **15 concurrent identical webhooks** and asserts exactly one `processed`, 14 byte-identical `already_processed` responses and exactly 1 `webhook_events` row / 1 payment / 1 booking. The suite passes on both SQLite and real PostgreSQL (`TEST_DATABASE_URL`).

---

## Edge cases handled

| Case | Behaviour |
|---|---|
| Invalid email / weak password (<8 chars, no letter or digit) | `422` with field-level messages |
| Duplicate signup | `409` |
| Missing / invalid / expired JWT | `401` + `WWW-Authenticate: Bearer` |
| Role escalation via signup payload | ignored — signup always creates `USER` |
| Staff-only endpoint as normal user | `403` |
| Appointment in the past (or now) | `422` "appointment_datetime: must be strictly in the future" |
| Centre does not offer the test | `400` |
| Unknown centre / test / booking id | `404` |
| Reading/cancelling/paying someone else's booking | `403` (listing only ever returns own bookings) |
| Cancel from `FAILED`/`CANCELLED` | `409` |
| Pay for non-`PENDING` booking, or after a successful payment | `409` |
| Failed payment | booking → `FAILED`; payment row kept |
| Duplicate / concurrent / late webhooks | idempotent, state never regresses (see above) |
| Price changed after booking | booking keeps its locked `amount` |
| Redis unreachable | requests succeed (cache miss + circuit breaker; rate limiter falls back to memory) |
| Unhandled exception | `500` generic envelope, full traceback only in structured logs |
| Brute force / abuse | SlowAPI limits on auth + payments → `429` |

---

## Testing
```bash
pip install -r requirements-dev.txt
pytest -q                                   # SQLite (temp file), Redis intentionally unreachable
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/eve_test pytest -q   # real row locks
```
42 tests covering auth, catalogue + search/pagination + RBAC, caching and Redis-down fallback, the full booking lifecycle,
authorization isolation, price locking, payments (success/failure/retry/guards), signature verification, rate limiting and the
idempotency/concurrency scenarios above.

## Structured logging
Every request emits one JSON line with `request_id` (honours an incoming `X-Request-ID`, echoed in the response), `method`,
`endpoint` (route template), `status_code` and `duration_ms`; business events (booking created, webhook processed/duplicate/ignored)
carry the same `request_id` via a context variable.
```json
{"timestamp": "...", "level": "INFO", "logger": "app.request", "message": "request completed", "request_id": "39bcb…", "method": "POST", "endpoint": "/api/v1/payments/webhook", "status_code": 200, "duration_ms": 6.4}
```

---

## Assumptions
* A booking is a single test at a single centre; one payment settles it. A failed payment moves the booking to terminal `FAILED` (the user books again); retrying a payment is only possible while the booking is still `PENDING`.
* The simulated gateway reports its result **asynchronously** via the signed webhook; `POST /payments` returns the gateway outcome and the booking status updates moments later.
* `?simulate=success|failed` is a testing aid (disable with `ALLOW_PAYMENT_SIMULATION_OVERRIDE=false`).
* Roles: `USER`, `STAFF`, `ADMIN`. Staff/admin create catalogue data; the first admin is bootstrapped from env vars. Admins are *not* granted access to other users' bookings (the spec requires strict ownership).
* Naive datetimes are interpreted as UTC. Currency is a single implicit currency (INR in the examples).
* Webhook signing uses a shared secret and an HMAC over the key fields (a real provider would define its own scheme, typically with a timestamp to prevent replay).
* A `SUCCESS` webhook arriving after a booking was cancelled is recorded as `IGNORED`; in production that would trigger a refund workflow (out of scope).

## What I'd improve with more time
* **Transactional Outbox:** write "booking confirmed / payment settled" events to an `outbox` table in the same transaction and publish them with a relay worker — no dual-write problem.
* **Kafka (or SQS/RabbitMQ)** for domain events (notifications, lab-order creation, analytics) and to decouple webhook *receipt* (persist + ack fast) from *processing* with a consumer + DLQ.
* **Celery/Arq workers** for webhook retries with persisted attempts, appointment reminders, and expiring stale `PENDING` bookings (auto-cancel after N minutes).
* Slot management (capacity per centre/time window, double-booking prevention with exclusion constraints), refunds, and a real payment provider integration with timestamped signatures and replay windows.
* Refresh tokens + token revocation, email verification, per-account login lockout; secrets from a vault.
* Observability: OpenTelemetry traces, Prometheus metrics, correlation of logs across the webhook dispatch.
* Keyset pagination for large tables, read replicas for catalogue reads, and cache invalidation by tag.
* CI (lint, type-check, tests against Postgres service), `pre-commit`, and load tests for the webhook path.
