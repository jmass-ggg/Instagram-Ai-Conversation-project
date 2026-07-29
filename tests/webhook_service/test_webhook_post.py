"""
Unit tests for the POST /webhooks/meta endpoint.
Requirements: 2.3, 2.4, 3.5, 3.6
"""
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from webhook_service.app.main import app
from webhook_service.app.settings import settings

# ── Constants ────────────────────────────────────────────────────────────────

APP_SECRET = "test-app-secret"

FIXTURE_PATH = (
    Path(__file__).parent.parent / "fixtures" / "instagram_comment_webhook.json"
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sign(body: bytes, secret: str = APP_SECRET) -> str:
    """Compute the sha256=<hex> signature Meta would send."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    """Inject known secrets into the settings singleton."""
    monkeypatch.setattr(settings, "META_APP_SECRET", APP_SECRET)
    monkeypatch.setattr(settings, "META_VERIFY_TOKEN", "test-verify-token")
    monkeypatch.setattr(settings, "DJANGO_INTERNAL_URL", "http://django:8000")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fixture_payload() -> bytes:
    return FIXTURE_PATH.read_bytes()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_valid_signed_payload_is_processed_and_forwarded(client, fixture_payload):
    """
    Requirement 2.3, 3.4: A correctly-signed payload must be accepted (HTTP 200)
    and each extracted comment event forwarded to Django.
    """
    signature = _sign(fixture_payload)

    with patch(
        "webhook_service.app.main.forward_comment_event",
        new_callable=AsyncMock,
    ) as mock_forward:
        response = client.post(
            "/webhooks/meta",
            content=fixture_payload,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    # The fixture contains exactly one comment entry — forward must be called once
    mock_forward.assert_called_once()


def test_missing_signature_header_returns_403(client, fixture_payload):
    """
    Requirement 2.4: Absent X-Hub-Signature-256 header must be rejected with 403.
    """
    response = client.post(
        "/webhooks/meta",
        content=fixture_payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 403


def test_invalid_signature_returns_403(client, fixture_payload):
    """
    Requirement 2.3: A tampered or wrong signature must be rejected with 403.
    """
    response = client.post(
        "/webhooks/meta",
        content=fixture_payload,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=deadbeefdeadbeefdeadbeef",
        },
    )
    assert response.status_code == 403


def test_django_forwarding_failure_still_returns_200(client, fixture_payload):
    """
    Requirement 3.5, 3.6: If Django forwarding raises an exception the endpoint
    must still return HTTP 200 to Meta (so Meta does not retry).
    """
    signature = _sign(fixture_payload)

    with patch(
        "webhook_service.app.main.forward_comment_event",
        new_callable=AsyncMock,
        side_effect=Exception("connection refused"),
    ):
        response = client.post(
            "/webhooks/meta",
            content=fixture_payload,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
