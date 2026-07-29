"""
Property-based tests for HMAC-SHA256 webhook signature verification.
Feature: instagram-price-reply, Property 1: Webhook signature round-trip consistency
Requirements: 2.2, 2.3, 2.5
"""
import hashlib
import hmac as hmac_lib

from hypothesis import given, settings
from hypothesis import strategies as st

from webhook_service.app.signature import verify_signature


def _compute_signature(raw_body: bytes, secret: str) -> str:
    """Helper that mirrors the signing logic — computes sha256=<hex>."""
    digest = hmac_lib.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# Feature: instagram-price-reply, Property 1: Webhook signature round-trip consistency
@given(
    raw_body=st.binary(min_size=0, max_size=4096),
    secret=st.text(min_size=1, max_size=128),
)
@settings(max_examples=200)
def test_signature_round_trip_returns_true(raw_body: bytes, secret: str):
    """
    For any raw body and secret, computing the HMAC-SHA256 signature and then
    verifying it with verify_signature SHALL return True.
    Validates: Requirements 2.2, 2.5
    """
    signature = _compute_signature(raw_body, secret)
    assert verify_signature(raw_body, signature, secret) is True


# Feature: instagram-price-reply, Property 1: Webhook signature round-trip consistency (tampered body)
@given(
    raw_body=st.binary(min_size=1, max_size=4096),
    secret=st.text(min_size=1, max_size=128),
    extra_byte=st.integers(min_value=0, max_value=255),
)
@settings(max_examples=200)
def test_tampered_body_returns_false(raw_body: bytes, secret: str, extra_byte: int):
    """
    For any raw body and secret, appending a byte to the body (tampering) causes
    verify_signature to return False.
    Validates: Requirements 2.3, 2.5
    """
    signature = _compute_signature(raw_body, secret)
    tampered_body = raw_body + bytes([extra_byte])
    assert verify_signature(tampered_body, signature, secret) is False


# Feature: instagram-price-reply, Property 1: Webhook signature round-trip consistency (wrong secret)
@given(
    raw_body=st.binary(min_size=0, max_size=4096),
    secret=st.text(min_size=1, max_size=128),
    wrong_secret=st.text(min_size=1, max_size=128),
)
@settings(max_examples=200)
def test_wrong_secret_returns_false(raw_body: bytes, secret: str, wrong_secret: str):
    """
    For any raw body and secret, verifying with a different secret causes
    verify_signature to return False (unless the two secrets happen to be identical).
    Validates: Requirements 2.3, 2.5
    """
    signature = _compute_signature(raw_body, secret)
    if wrong_secret != secret:
        assert verify_signature(raw_body, signature, wrong_secret) is False
