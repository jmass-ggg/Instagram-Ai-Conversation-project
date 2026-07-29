# Instagram Comment → Private Price Reply

Automatically replies to Instagram comments asking about price with a private
message containing the product's price from your database.

## Architecture

- **FastAPI webhook service** (`webhook_service/`, port 8001) — receives and
  verifies Meta webhooks, normalizes comment events, forwards them to Django.
- **Django app** (`django_app/`, port 8000) — business logic, database access,
  and Meta Graph API private reply calls.
- **PostgreSQL** (`db`, port 5432) — shared database.

## Quick start

```bash
cp .env.example .env
# Edit .env with your real values
docker-compose up --build
```

Seed demo data after containers are running:

```bash
docker-compose exec django python manage.py migrate
docker-compose exec django python manage.py seed_demo_data
```

## Environment variables

See `.env.example` for the full list of required variables.

## Running tests

```bash
# Django tests
docker-compose exec django pytest

# FastAPI tests
docker-compose exec webhook pytest
```
