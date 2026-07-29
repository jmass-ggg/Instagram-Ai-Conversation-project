"""
Unit tests for the Meta webhook verification endpoint (GET /webhooks/meta).
Requirements: 1.2, 1.3
"""
import pytest
from fastapi.testclient import TestClient

from webhook_service.app.main import app
from webhook_service.app.settings import settings

VALID_TOKEN = "test-verify-token"


@pytest.fixture(autouse=True)
def set_verify_token(monkeypatch):
    """Inject a known META_VERIFY_TOKEN directly into the settings object."""
    monkeypatch.setattr(settings, "META_VERIFY_TOKEN", VALID_TOKEN)


@pytest.fixture
def client():
    return TestClient(app)


def test_valid_token_returns_challenge(client):
    """Requirement 1.2: valid token → HTTP 200 with challenge body."""
    response = client.get(
        "/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VALID_TOKEN,
            "hub.challenge": "abc123",
        },
    )
    assert response.status_code == 200
    assert response.text == "abc123"


def test_invalid_token_returns_403(client):
    """Requirement 1.3: invalid token → HTTP 403."""
    response = client.get(
        "/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "abc123",
        },
    )
    assert response.status_code == 403


def test_missing_verify_token_returns_403(client):
    """Requirement 1.3: missing verify_token defaults to empty string → 403."""
    response = client.get(
        "/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "abc123",
        },
    )
    assert response.status_code == 403


def test_missing_challenge_returns_empty_body_on_valid_token(client):
    """Requirement 1.2: valid token with missing challenge → 200, empty body."""
    response = client.get(
        "/webhooks/meta",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VALID_TOKEN,
        },
    )
    assert response.status_code == 200
    assert response.text == ""
