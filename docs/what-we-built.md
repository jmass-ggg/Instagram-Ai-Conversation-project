# What We Built

## Summary

An automated Instagram price-reply bot. When a customer comments on one of your Instagram posts asking about the price, the system detects it and instantly sends them a private message with the price — no manual work needed.

---

## The Two Services

### 1. FastAPI Webhook Service (`webhook_service/`)

This is the public-facing service that Meta (Instagram) talks to directly.

**What it does:**
- Receives HTTP requests from Meta whenever someone comments on your Instagram post
- Verifies every request is genuinely from Meta using HMAC-SHA256 signature checking
- Handles Meta's one-time webhook verification handshake (the `GET /webhooks/meta` challenge)
- Parses the raw Meta payload and extracts comment events
- Forwards clean, normalised comment events to the Django service over an internal HTTP call
- Always returns HTTP 200 to Meta, even if something goes wrong internally (so Meta never retries)

**Key files:**
- `app/main.py` — FastAPI routes (GET and POST `/webhooks/meta`)
- `app/signature.py` — HMAC-SHA256 signature verification
- `app/normalizer.py` — converts raw Meta JSON into `InstagramCommentEvent` objects
- `app/django_client.py` — HTTPX client that forwards events to Django
- `app/settings.py` — loads all config from environment variables

---

### 2. Django App (`django_app/`)

This is the internal service that does all the business logic. It is never exposed to the internet.

**What it does:**
- Receives normalised comment events from the FastAPI service (protected by a shared secret header)
- Checks for duplicate comments so the same comment is never replied to twice
- Detects price intent — only comments containing `price`, `how much`, or `cost` (case-insensitive) trigger a reply
- Resolves which Instagram account the comment was made on
- Looks up which product is mapped to that Instagram post
- Composes a reply in the format: `Hi! The price of {product_name} is {currency}{price}.`
- Sends the reply as a private Instagram message via the Meta Graph API
- Records every comment and its outcome in PostgreSQL

**Key files:**
- `price_reply/service.py` — main orchestration pipeline
- `price_reply/intent.py` — `is_price_inquiry()` function
- `price_reply/reply.py` — `build_price_reply()` function
- `price_reply/meta_client.py` — Meta Graph API private reply client
- `price_reply/models.py` — all database models
- `price_reply/views.py` — internal DRF endpoint
- `price_reply/serializers.py` — request validation
- `management/commands/seed_demo_data.py` — demo data setup command

---

## Database Models

| Model | Purpose |
|---|---|
| `Business` | The merchant entity that owns products and an Instagram account |
| `InstagramAccount` | A connected Instagram Professional account with access token |
| `Product` | An item with a name and price |
| `InstagramPostProductMapping` | Links an Instagram post (media ID) to a Product |
| `ProcessedComment` | Audit log of every comment received and its outcome |

`ProcessedComment.status` values: `received` → `ignored` / `sent` / `failed`

---

## The Full Request Flow

```
Customer comments on Instagram post
        ↓
Meta sends POST /webhooks/meta to FastAPI (port 8001)
        ↓
FastAPI verifies HMAC-SHA256 signature
        ↓
FastAPI extracts comment fields, creates InstagramCommentEvent
        ↓
FastAPI POSTs to Django POST /internal/instagram/comments (port 8000)
        ↓
Django checks: duplicate? → return early
Django checks: price intent? → if no, mark ignored
Django resolves: InstagramAccount active? → if no, mark failed
Django resolves: Post mapping → Product active, same business? → if no, mark failed
Django composes reply text
Django POSTs private reply to Meta Graph API
Django updates ProcessedComment status to sent/failed
```

---

## Test Coverage

27 tests across both services, all passing:

| Test file | What it covers |
|---|---|
| `test_signature.py` | Property tests: HMAC round-trip, tampered body, wrong secret |
| `test_normalizer.py` | Property test: event serialization round-trip |
| `test_verification.py` | Unit tests: webhook GET verification endpoint |
| `test_webhook_post.py` | Unit tests: POST endpoint signing, forwarding, error handling |
| `test_intent.py` | Property test: price intent positive matches |
| `test_service.py` | Property + unit tests: duplicate idempotence, ignored comments, resolution failures, cross-business isolation, endpoint auth |
