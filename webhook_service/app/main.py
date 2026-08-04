import json
import logging

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import PlainTextResponse, JSONResponse, HTMLResponse

from .django_client import forward_comment_event
from .normalizer import extract_comment_events
from .settings import settings
from .signature import verify_signature

logger = logging.getLogger(__name__)

app = FastAPI(title="Instagram Webhook Service")

# ── Legal pages (required for Meta app Live mode) ─────────────────────────────

@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Privacy Policy – Instagram Price Reply Bot</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; line-height: 1.7; }
    h1 { color: #1a1a1a; border-bottom: 2px solid #e0e0e0; padding-bottom: 10px; }
    h2 { color: #333; margin-top: 30px; }
    a { color: #0066cc; }
  </style>
</head>
<body>
  <h1>Privacy Policy</h1>
  <p><strong>Last updated: August 4, 2026</strong></p>

  <p>This Privacy Policy explains how the Instagram Price Reply Bot ("the Service", "we", "us") collects, uses, and protects information when you interact with it through Instagram comments.</p>

  <h2>1. What Information We Collect</h2>
  <p>When you comment on an Instagram post associated with this Service, we may collect:</p>
  <ul>
    <li>Your Instagram user ID and username</li>
    <li>The text content of your comment</li>
    <li>The Instagram post (media) ID you commented on</li>
    <li>The timestamp of your comment</li>
  </ul>

  <h2>2. How We Use Your Information</h2>
  <p>We use the collected information solely to:</p>
  <ul>
    <li>Detect whether your comment is asking about product pricing</li>
    <li>Send you a private Instagram message with the requested price information</li>
    <li>Maintain an internal audit log to prevent duplicate replies</li>
  </ul>
  <p>We do not sell, rent, or share your information with any third parties for marketing purposes.</p>

  <h2>3. Data Retention</h2>
  <p>Comment data is retained in our internal database for operational purposes (duplicate detection and audit logging). We do not retain data longer than necessary for the operation of this Service.</p>

  <h2>4. Meta Platform Data</h2>
  <p>This Service uses the Meta Graph API to send private replies. By interacting with Instagram posts connected to this Service, you acknowledge that Meta's own <a href="https://www.facebook.com/privacy/policy/" target="_blank">Privacy Policy</a> also applies to your data on their platform.</p>

  <h2>5. Data Security</h2>
  <p>We implement industry-standard security measures including encrypted communication (HTTPS), HMAC-SHA256 signature verification for all incoming webhook events, and internal service authentication to protect your data.</p>

  <h2>6. Your Rights</h2>
  <p>You have the right to request deletion of your data. To do so, please submit a data deletion request via our <a href="/data-deletion">Data Deletion page</a> or contact us directly.</p>

  <h2>7. Contact Us</h2>
  <p>If you have any questions about this Privacy Policy, please contact us at:<br>
  <a href="mailto:jamesgurung690@gmail.com">jamesgurung690@gmail.com</a></p>
</body>
</html>"""


@app.get("/terms", response_class=HTMLResponse)
async def terms_of_service() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Terms of Service – Instagram Price Reply Bot</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; line-height: 1.7; }
    h1 { color: #1a1a1a; border-bottom: 2px solid #e0e0e0; padding-bottom: 10px; }
    h2 { color: #333; margin-top: 30px; }
    a { color: #0066cc; }
  </style>
</head>
<body>
  <h1>Terms of Service</h1>
  <p><strong>Last updated: August 4, 2026</strong></p>

  <p>By interacting with Instagram posts connected to the Instagram Price Reply Bot ("the Service"), you agree to these Terms of Service.</p>

  <h2>1. Description of Service</h2>
  <p>The Service is an automated Instagram comment response system. When you comment on a connected Instagram post asking about product pricing, the Service automatically sends you a private Instagram message containing the product price.</p>

  <h2>2. Acceptable Use</h2>
  <p>You agree to use the Service only for its intended purpose of obtaining product pricing information. You must not:</p>
  <ul>
    <li>Attempt to manipulate or abuse the automated reply system</li>
    <li>Use the Service to send spam or unsolicited messages</li>
    <li>Attempt to gain unauthorized access to any part of the Service</li>
    <li>Violate any applicable laws or Meta's Platform Terms</li>
  </ul>

  <h2>3. Automated Interactions</h2>
  <p>You acknowledge that replies sent through this Service are automated. The Service detects price-related keywords in comments ("price", "how much", "cost") and responds accordingly. The Service does not provide human customer support.</p>

  <h2>4. Accuracy of Information</h2>
  <p>We strive to keep product pricing information accurate and up to date. However, prices are subject to change without notice. The Service makes no guarantee that prices displayed are current at the time of the automated reply.</p>

  <h2>5. Limitation of Liability</h2>
  <p>The Service is provided "as is" without warranties of any kind. We are not liable for any damages arising from your use of or inability to use the Service.</p>

  <h2>6. Changes to Terms</h2>
  <p>We reserve the right to modify these Terms at any time. Continued interaction with the Service after changes constitutes acceptance of the updated Terms.</p>

  <h2>7. Contact</h2>
  <p>For questions about these Terms, contact us at:<br>
  <a href="mailto:jamesgurung690@gmail.com">jamesgurung690@gmail.com</a></p>
</body>
</html>"""


@app.get("/data-deletion", response_class=HTMLResponse)
async def data_deletion() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Data Deletion – Instagram Price Reply Bot</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; color: #333; line-height: 1.7; }
    h1 { color: #1a1a1a; border-bottom: 2px solid #e0e0e0; padding-bottom: 10px; }
    h2 { color: #333; margin-top: 30px; }
    .steps { background: #f5f5f5; padding: 20px; border-radius: 8px; }
    .steps ol { margin: 0; padding-left: 20px; }
    .steps li { margin-bottom: 10px; }
    a { color: #0066cc; }
    .highlight { background: #e8f4fd; border-left: 4px solid #0066cc; padding: 15px; margin: 20px 0; border-radius: 0 8px 8px 0; }
  </style>
</head>
<body>
  <h1>Data Deletion Instructions</h1>
  <p><strong>Last updated: August 4, 2026</strong></p>

  <p>This page explains what data the Instagram Price Reply Bot stores about you and how to request its deletion.</p>

  <h2>What Data We Store</h2>
  <p>When you comment on an Instagram post connected to this Service, we may store:</p>
  <ul>
    <li>Your Instagram user ID</li>
    <li>Your comment text</li>
    <li>The Instagram post ID you commented on</li>
    <li>The timestamp of your comment</li>
    <li>The automated reply we sent (if any)</li>
  </ul>

  <h2>How to Request Data Deletion</h2>
  <div class="steps">
    <ol>
      <li>Send an email to <a href="mailto:jamesgurung690@gmail.com">jamesgurung690@gmail.com</a></li>
      <li>Use the subject line: <strong>"Data Deletion Request"</strong></li>
      <li>Include your Instagram username or user ID so we can locate your records</li>
      <li>We will process your request within <strong>30 days</strong> and confirm deletion via email</li>
    </ol>
  </div>

  <div class="highlight">
    <strong>Quick request:</strong> Email <a href="mailto:jamesgurung690@gmail.com?subject=Data Deletion Request">jamesgurung690@gmail.com</a> with your Instagram username to delete your data.
  </div>

  <h2>Revoking App Access via Facebook</h2>
  <p>You can also revoke this app's access to your Instagram data directly through Facebook:</p>
  <ol>
    <li>Go to <a href="https://www.facebook.com/settings?tab=applications" target="_blank">Facebook Settings → Apps and Websites</a></li>
    <li>Find and remove the connected app</li>
    <li>This will revoke all permissions and stop any future data collection</li>
  </ol>

  <h2>Contact</h2>
  <p>For any questions about your data, contact us at:<br>
  <a href="mailto:jamesgurung690@gmail.com">jamesgurung690@gmail.com</a></p>
</body>
</html>"""


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

    logger.info("RAW PAYLOAD: %s", json.dumps(payload))

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
