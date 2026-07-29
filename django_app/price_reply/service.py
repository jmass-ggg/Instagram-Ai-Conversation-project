import logging
from datetime import datetime, timezone

from django.utils import timezone as dj_timezone

from .intent import is_price_inquiry
from .meta_client import MetaPrivateReplyClient
from .models import (
    InstagramAccount,
    InstagramPostProductMapping,
    ProcessedComment,
)
from .reply import build_price_reply

logger = logging.getLogger(__name__)


def process_comment_event(event_data: dict) -> ProcessedComment:
    """
    Orchestrate the full comment-to-reply pipeline.

    Steps:
      1. Duplicate check — return existing record immediately if already seen
      2. Resolve InstagramAccount — fail if missing or inactive
      3. Price intent check — mark ignored if not a price inquiry
      4. Resolve post mapping → product — fail if missing, inactive, or cross-business
      5. Compose reply
      6. Send private reply via Meta Graph API
      7. Update ProcessedComment status to sent/failed
    """
    comment_id = event_data["comment_id"]
    instagram_account_id = event_data["instagram_account_id"]
    media_id = event_data["media_id"]
    commenter_id = event_data.get("commenter_id", "")
    comment_text = event_data["comment_text"]
    timestamp = event_data["timestamp"]

    # Normalise timestamp to a timezone-aware datetime for received_at
    if isinstance(timestamp, str):
        received_at = datetime.fromisoformat(timestamp)
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
    elif isinstance(timestamp, datetime):
        received_at = timestamp
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
    else:
        received_at = dj_timezone.now()

    # ── 1. Duplicate check ────────────────────────────────────────────────────
    # We need a placeholder account for the FK before we know the real one.
    # Use get_or_create with a sentinel that we'll update after account lookup.
    # Strategy: attempt to fetch first; only create if it doesn't exist yet.
    try:
        existing = ProcessedComment.objects.get(instagram_comment_id=comment_id)
        logger.info("Duplicate comment %s — returning existing record", comment_id)
        return existing
    except ProcessedComment.DoesNotExist:
        pass

    # ── 2. Resolve InstagramAccount ───────────────────────────────────────────
    try:
        account = InstagramAccount.objects.get(instagram_user_id=instagram_account_id)
    except InstagramAccount.DoesNotExist:
        logger.warning("InstagramAccount not found: %s", instagram_account_id)
        # We can't create a ProcessedComment with a FK to a non-existent account,
        # so we log and return a transient (unsaved) failed stub.
        # Per requirements 7.2: mark failed, return success response.
        return _make_stub_failed_comment(
            comment_id=comment_id,
            media_id=media_id,
            commenter_id=commenter_id,
            comment_text=comment_text,
            received_at=received_at,
            error=f"InstagramAccount not found: {instagram_account_id}",
        )

    if not account.is_active:
        logger.warning("InstagramAccount inactive: %s", instagram_account_id)
        return _make_stub_failed_comment(
            comment_id=comment_id,
            media_id=media_id,
            commenter_id=commenter_id,
            comment_text=comment_text,
            received_at=received_at,
            error=f"InstagramAccount is inactive: {instagram_account_id}",
        )

    if not account.access_token:
        logger.warning("InstagramAccount has no access token: %s", instagram_account_id)
        return _make_stub_failed_comment(
            comment_id=comment_id,
            media_id=media_id,
            commenter_id=commenter_id,
            comment_text=comment_text,
            received_at=received_at,
            error=f"InstagramAccount has no access token: {instagram_account_id}",
        )

    # ── Create the ProcessedComment record now that we have a valid account ───
    record, created = ProcessedComment.objects.get_or_create(
        instagram_comment_id=comment_id,
        defaults={
            "instagram_account": account,
            "instagram_media_id": media_id,
            "commenter_id": commenter_id or "",
            "comment_text": comment_text,
            "status": ProcessedComment.STATUS_RECEIVED,
            "received_at": received_at,
        },
    )
    if not created:
        # Race condition: another worker created it between our initial check and now
        logger.info("Duplicate comment (race) %s — returning existing record", comment_id)
        return record

    # ── 3. Price intent check ─────────────────────────────────────────────────
    if not is_price_inquiry(comment_text):
        record.status = ProcessedComment.STATUS_IGNORED
        record.processed_at = dj_timezone.now()
        record.save(update_fields=["status", "processed_at"])
        logger.info("Comment %s is not a price inquiry — ignored", comment_id)
        return record

    # ── 4. Resolve post mapping → product ────────────────────────────────────
    try:
        mapping = InstagramPostProductMapping.objects.select_related("product__business").get(
            instagram_account=account,
            instagram_media_id=media_id,
        )
    except InstagramPostProductMapping.DoesNotExist:
        record.status = ProcessedComment.STATUS_FAILED
        record.error_message = f"No post mapping found for media_id={media_id}"
        record.processed_at = dj_timezone.now()
        record.save(update_fields=["status", "error_message", "processed_at"])
        logger.warning("No post mapping for media_id=%s account=%s", media_id, instagram_account_id)
        return record

    product = mapping.product

    if not product.is_active:
        record.status = ProcessedComment.STATUS_FAILED
        record.error_message = f"Product {product.pk} is inactive"
        record.processed_at = dj_timezone.now()
        record.save(update_fields=["status", "error_message", "processed_at"])
        logger.warning("Product %s inactive", product.pk)
        return record

    # Cross-business isolation (Requirement 8.5)
    if product.business_id != account.business_id:
        record.status = ProcessedComment.STATUS_FAILED
        record.error_message = (
            f"Product {product.pk} belongs to a different business than account {account.pk}"
        )
        record.processed_at = dj_timezone.now()
        record.save(update_fields=["status", "error_message", "processed_at"])
        logger.warning(
            "Cross-business product isolation: product.business=%s account.business=%s",
            product.business_id,
            account.business_id,
        )
        return record

    # ── 5. Compose reply ──────────────────────────────────────────────────────
    reply_text = build_price_reply(product)

    # ── 6. Send private reply ─────────────────────────────────────────────────
    client = MetaPrivateReplyClient()
    result = client.send_private_reply(
        comment_id=comment_id,
        message=reply_text,
        access_token=account.access_token,
        page_id=account.page_id,
    )

    # ── 7. Update status ──────────────────────────────────────────────────────
    if result.success:
        record.status = ProcessedComment.STATUS_SENT
        record.reply_text = reply_text
    else:
        record.status = ProcessedComment.STATUS_FAILED
        record.error_message = result.error or "Unknown Meta API error"

    record.processed_at = dj_timezone.now()
    record.save(update_fields=["status", "reply_text", "error_message", "processed_at"])

    return record


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_stub_failed_comment(
    *,
    comment_id: str,
    media_id: str,
    commenter_id: str,
    comment_text: str,
    received_at,
    error: str,
) -> ProcessedComment:
    """
    Return an unsaved ProcessedComment stub when we cannot link to a real
    InstagramAccount (account not found / inactive). The record is intentionally
    NOT persisted so the FK constraint is not violated.
    """
    stub = ProcessedComment(
        instagram_comment_id=comment_id,
        instagram_media_id=media_id,
        commenter_id=commenter_id or "",
        comment_text=comment_text,
        status=ProcessedComment.STATUS_FAILED,
        error_message=error,
        received_at=received_at,
    )
    return stub
