# Configuration

All configuration is done through environment variables. Copy `.env.example` to `.env` and fill in each value before running the system.

---

## Meta / Instagram Credentials

### `META_APP_SECRET`
**Required.** The App Secret from your Meta app dashboard.

Where to find it: Meta for Developers → Your App → App Settings → Basic → App Secret

This is used to verify that incoming webhooks genuinely come from Meta (HMAC-SHA256 signature check). Never share or commit this value.

---

### `META_VERIFY_TOKEN`
**Required.** A string you choose yourself — any random value works (e.g. a UUID).

Where to set it: Meta for Developers → Your App → Webhooks → Edit → Verify Token

This value must match exactly what you enter in the Meta dashboard when setting up the webhook. Meta sends it back during the verification handshake.

Example: `my-random-verify-token-abc123`

---

### `INSTAGRAM_ACCESS_TOKEN`
**Required for live use.** The Page Access Token for the Facebook Page linked to your Instagram Professional account.

Where to get it: Meta for Developers → Tools → Graph API Explorer → select your Page → generate a long-lived page access token. Make sure it has `instagram_manage_comments` and `pages_messaging` permissions.

---

### `INSTAGRAM_PAGE_ID`
**Required.** The numeric ID of the Facebook Page linked to your Instagram account.

Where to find it: Your Facebook Page → About → Page Transparency → Page ID. Or via Graph API: `GET /me?fields=id,name` with your page access token.

---

### `INSTAGRAM_USER_ID`
**Required for seed command.** The numeric Instagram User ID of your Professional account.

Where to find it: Graph API Explorer → `GET /me?fields=id` with your Instagram User access token, or from Meta's Business Suite.

---

### `INSTAGRAM_USERNAME`
**Optional.** Your Instagram handle (e.g. `myshop`). Used only for the seed command to label the account record.

---

### `INSTAGRAM_MEDIA_ID`
**Required for seed command.** The numeric ID of the Instagram post you want to map to the demo product.

Where to find it: Graph API Explorer → `GET /{instagram-user-id}/media` → copy the `id` of the post you want.

---

## Internal Service Secret

### `INTERNAL_SERVICE_SECRET`
**Required.** A secret string shared between the FastAPI webhook service and the Django app. It is sent as the `X-Internal-Service-Secret` header on every internal request.

Generate a strong random value:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

This prevents anything other than the FastAPI service from calling Django's internal endpoint.

---

## Django Settings

### `DJANGO_SECRET_KEY`
**Required.** Django's cryptographic signing key. Generate a strong random value:
```bash
python3 -c "import secrets; print(secrets.token_hex(50))"
```

### `DEBUG`
Set to `true` for local development, `false` in production. Default: `true`.

### `DATABASE_URL`
**Required.** PostgreSQL connection string.

Format: `postgres://USER:PASSWORD@HOST:PORT/DBNAME`

Default when using Docker Compose: `postgres://app:secret@db:5432/instagram_price_reply`

### `POSTGRES_USER` / `POSTGRES_PASSWORD`
Credentials for the PostgreSQL container. These are used by Docker Compose to create the database and must match what you put in `DATABASE_URL`.

---

## Business Settings

### `CURRENCY_SYMBOL`
The currency symbol prepended to prices in reply messages. Default: `$`.

Examples: `$`, `€`, `£`, `₺`, `AED `

The reply format is: `Hi! The price of Widget is $49.99.`

### `GRAPH_API_VERSION`
The Meta Graph API version to use when sending private replies. Default: `v19.0`.

Check the latest stable version at: https://developers.facebook.com/docs/graph-api/changelog

---

## Demo / Seed Data

These are only used by the `seed_demo_data` management command.

### `DEMO_PRODUCT_NAME`
The name of the demo product created by the seed command. Example: `Awesome Widget`

### `DEMO_PRODUCT_PRICE`
The price of the demo product as a decimal number. Example: `49.99`

---

## Meta App Dashboard Setup (Step by Step)

1. Go to [developers.facebook.com](https://developers.facebook.com) and create or open your app
2. Add the **Instagram** product to your app
3. Under **Webhooks**, click **Add Callback URL**:
   - Callback URL: `https://YOUR_DOMAIN/webhooks/meta` (must be HTTPS)
   - Verify Token: the value you set as `META_VERIFY_TOKEN` in your `.env`
4. Click **Verify and Save** — Meta will send a GET request; the FastAPI service handles this automatically
5. Subscribe to the **comments** field under the Instagram object
6. Make sure your Instagram account is added as a test account under **Roles → Instagram Testers** (for development mode)

---

## Service URL

### `DJANGO_INTERNAL_URL`
The base URL the FastAPI service uses to reach Django internally. Inside Docker Compose this is `http://django:8000`. Only change this if you are running the services outside of Docker.
