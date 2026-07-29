# How to Run

## Prerequisites

- Docker and Docker Compose installed
- A Meta Developer account with an Instagram app (for live webhooks)
- An Instagram Professional account linked to a Facebook Page

---

## Quick Start (Local)

### 1. Copy the environment file

```bash
cp .env.example .env
```

Edit `.env` and fill in all the values (see `configuration.md` for what each one means).

### 2. Start all services

```bash
docker-compose up --build
```

This starts three containers:
- `db` — PostgreSQL on port 5432
- `django` — Django app on port 8000 (runs migrations automatically on startup)
- `webhook` — FastAPI service on port 8001

### 3. Seed demo data

Once the containers are running, populate the database with one demo business, account, product, and post mapping:

```bash
docker-compose exec django python manage.py seed_demo_data
```

This reads the Instagram and product values from your `.env` file. Running it a second time is safe — it uses `get_or_create` so nothing is duplicated.

### 4. Expose the webhook endpoint to Meta

Meta needs to reach your FastAPI service over HTTPS. For local development use [ngrok](https://ngrok.com/):

```bash
ngrok http 8001
```

Copy the `https://...ngrok.io` URL — you'll need it for the Meta app configuration.

---

## Running Tests

Run all tests from inside the `instagram-price-reply/` directory:

```bash
python3 -m pytest tests/ -v
```

The test suite does not require Docker or a running database — it uses Django's in-memory test database automatically.

To run just one service's tests:

```bash
# Webhook service tests only
python3 -m pytest tests/webhook_service/ -v

# Django app tests only
python3 -m pytest tests/django_app/ -v
```

---

## Checking Logs

```bash
# All services
docker-compose logs -f

# Just the webhook receiver
docker-compose logs -f webhook

# Just Django
docker-compose logs -f django
```

---

## Stopping Everything

```bash
docker-compose down
```

To also delete the database volume (fresh start):

```bash
docker-compose down -v
```

---

## Manually Triggering a Test Event

You can simulate a Meta webhook POST locally using curl. First get your app secret and compute a signature:

```bash
BODY='{"object":"instagram","entry":[{"id":"ACC_ID","time":1700000000,"changes":[{"field":"comments","value":{"id":"CMT_ID","text":"what is the price?","from":{"id":"USER_ID"},"media":{"id":"MEDIA_ID"}}}]}]}'

SIG=$(echo -n "$BODY" | openssl dgst -sha256 -hmac "YOUR_META_APP_SECRET" | awk '{print "sha256="$2}')

curl -X POST http://localhost:8001/webhooks/meta \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: $SIG" \
  -d "$BODY"
```

Replace `YOUR_META_APP_SECRET`, `ACC_ID`, `CMT_ID`, `USER_ID`, and `MEDIA_ID` with real values from your seeded data.
