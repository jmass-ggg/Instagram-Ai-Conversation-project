import json
import logging

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import PlainTextResponse, JSONResponse

from .django_client import forward_comment_event
from .normalizer import extract_comment_events
from .settings import settings
from .signature import verify_signature

logger = logging.getLogger(__name__)

app = FastAPI(title="Instagram Webhook Service")


@app.on_event("startup")
async def startup_event() -> None:
    settings.load()


@app.get("/webhooks/meta", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode", default=""),
    hub_verify_token: str = Query(alias="hub.verify_token", default=""),
    hub_challenge: str = Query(alias="hub.challenge", default=""),
) -> str:
    """
    Meta webhook verification endpoint (Requirements 1.1, 1.2, 1.3).
    Meta sends a GET with hub.mode=subscribe, hub.verify_token, and hub.challenge.
    Return the challenge on success, 403 on token mismatch.
    """
    if hub_verify_token == settings.META_VERIFY_TOKEN:
        return hub_challenge
    raise HTTPException(status_code=403, detail="Forbidden: invalid verify token")


@app.post("/webhooks/meta")
async def receive_webhook(request: Request) -> JSONResponse:
    """
    Receive, verify, normalize, and forward Meta webhook events.

    Requirements: 2.1, 2.3, 2.4, 3.1, 3.4, 3.5, 3.6
    """
    # Read raw body before any parsing (Requirement 2.1)
    raw_body = await request.body()

    # Verify HMAC-SHA256 signature (Requirements 2.2, 2.3, 2.4)
    header_signature = request.headers.get("X-Hub-Signature-256", "")
    if not header_signature:
        raise HTTPException(status_code=403, detail="Forbidden: missing signature header")

    if not verify_signature(raw_body, header_signature, settings.META_APP_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden: invalid signature")

    # Parse payload; log without secrets (Requirement 2.6 / 13.4)
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("Received non-JSON webhook payload")
        return JSONResponse(status_code=200, content={"status": "ok"})

    logger.info("Received webhook payload with %d entries", len(payload.get("entry", [])))

    # Extract comment events (Requirements 3.1, 3.2)
    events = extract_comment_events(payload)

    # Forward each event to Django; log failures but still return 200 (Requirements 3.4, 3.5, 3.6)
    for event in events:
        try:
            await forward_comment_event(event)
        except Exception as exc:
            logger.error(
                "Failed to forward comment event %s to Django: %s",
                event.comment_id,
                exc,
            )

    return JSONResponse(status_code=200, content={"status": "ok"})
