import hashlib
import hmac


def verify_signature(raw_body: bytes, header_signature: str, secret: str) -> bool:
    """
    Verify the Meta webhook HMAC-SHA256 signature.

    Computes sha256=<hex> over raw_body using secret and compares with
    header_signature using constant-time comparison to prevent timing attacks.

    Requirements: 2.2, 2.5
    """
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", header_signature)
