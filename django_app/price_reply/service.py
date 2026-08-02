import logging
from datetime import datetime, timezone

from django.db import transaction
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
      1. Duplicate / terminal check — skip if already processed to completion
      2. Resolve InstagramAccount — fail if missing or inactive
      3. Atomic create-or-get ProcessedComment
      4. Price intent check — mark ignored if not a price inquiry
      5. Resolve post mapping → product — fail if missing, inactive, or cross-business
      6. Compose reply and persist it BEFORE calling Meta
      7. Send private reply via Meta Graph API
      8. Handle "already replied" as idempotency, not failure
      9. Update ProcessedComment status
    """
    comment_id = event_data["comment_id"]
    instagram_account_id = event_data["instagram_account_id"]
    media_id = event_data["media_id"]
    commenter_id = event_data.get("commenter_id", "")
    comment_text = event_data["comment_text"]
    timestamp = event_data["timestamp"]

    # Normalise timestamp
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

    # ── 1. Check for existing record ──────────────────────────────────────────
    try:
        existing = ProcessedComment.objects.get(instagram_comment_id=comment_id)
        if existing.is_terminal:
            logger.info(
                "Duplicate webhook for comment %s — already terminal (%s), skipping",
                comment_id, existing.status,
            )
            return existing
        # Non-terminal (received/failed) — fall through to reprocess
        logger.info(
            "Comment %s exists with status=%s — will attempt to reprocess",
            comment_id, existing.status,
        )
    except ProcessedComment.DoesNotExist:
        existing = None

    # ── 2. Resolve InstagramAccount ───────────────────────────────────────────
    try:
        account = InstagramAccount.objects.get(instagram_user_id=instagram_account_id)
    except InstagramAccount.DoesNotExist:
        logger.warning("InstagramAccount not found: %s", instagram_account_id)
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

    # ── 3. Atomic create-or-get ───────────────────────────────────────────────
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
        if record.is_terminal:
            logger.info(
                "Duplicate comment (race) %s — already terminal (%s)",
                comment_id, record.status,
            )
            return record
        logger.info("Reprocessing comment %s (status=%s)", comment_id, record.status)

    # ── 4. Price intent check ─────────────────────────────────────────────────
    if not is_price_inquiry(comment_text):
        record.status = ProcessedComment.STATUS_IGNORED
        record.processed_at = dj_timezone.now()
        record.save(update_fields=["status", "processed_at"])
        logger.info("Comment %s is not a price inquiry — ignored", comment_id)
        return record

    # ── 5. Resolve post mapping → product ────────────────────────────────────
    try:
        mapping = InstagramPostProductMapping.objects.select_related(
            "product__business"
        ).get(
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
        return record

    if product.business_id != account.business_id:
        record.status = ProcessedComment.STATUS_FAILED
        record.error_message = (
            f"Product {product.pk} belongs to a different business than account {account.pk}"
        )
        record.processed_at = dj_timezone.now()
        record.save(update_fields=["status", "error_message", "processed_at"])
        return record

    # ── 6. Compose and persist reply text BEFORE calling Meta ─────────────────
    reply_text = build_price_reply(product)
    record.reply_text = reply_text
    record.save(update_fields=["reply_text"])

    # ── 7. Send private reply ─────────────────────────────────────────────────
    client = MetaPrivateReplyClient()
    result = client.send_private_reply(
        comment_id=comment_id,
        message=reply_text,
        access_token=account.access_token,
        page_id=account.page_id,
    )

    # ── 8. Handle result ──────────────────────────────────────────────────────
    now = dj_timezone.now()

    if result.success:
        record.status = ProcessedComment.STATUS_SENT
        record.processed_at = now
        record.save(update_fields=["status", "processed_at"])
        logger.info("Comment %s replied successfully (message_id=%s)", comment_id, result.message_id)
        return record

    # Save structured error diagnostics
    record.error_message = result.error or "Unknown Meta API error"
    record.meta_error_code = result.error_code
    record.meta_error_subcode = result.error_subcode
    record.meta_fbtrace_id = result.fbtrace_id or ""

    if result.already_replied:
        # Meta says this comment already has a reply — reconcile with remote state
        record = _reconcile_already_replied(record, comment_id, reply_text, account, client, now)
    else:
        record.status = ProcessedComment.STATUS_FAILED
        record.processed_at = now
        record.save(update_fields=[
            "status", "error_message", "meta_error_code",
            "meta_error_subcode", "meta_fbtrace_id", "processed_at",
        ])
        logger.error(
            "Comment %s failed (retryable=%s): %s",
            comment_id, result.retryable, result.error,
        )

    return record


def _reconcile_already_replied(
    record: ProcessedComment,
    comment_id: str,
    intended_reply: str,
    account,
    client: MetaPrivateReplyClient,
    now,
) -> ProcessedComment:
    """
    Meta returned 'already has a reply'. Try to verify the remote reply matches
    what we intended. Either way, mark the record as already_replied — never
    post again.
    """
    logger.info(
        "Comment %s already has a remote reply — reconciling local record", comment_id
    )

    # Attempt to retrieve existing replies
    replies = client.get_comment_replies(comment_id, account.access_token)

    matched = False
    if replies:
        account_ig_id = account.instagram_user_id
        for reply in replies:
            from_id = (reply.get("from") or {}).get("id", "")
            reply_message = reply.get("message", "")
            if from_id == account_ig_id and reply_message.strip() == intended_reply.strip():
                matched = True
                break

    if matched:
        logger.info(
            "Comment %s: remote reply matches intended text — marking sent", comment_id
        )
        record.status = ProcessedComment.STATUS_SENT
        record.error_message = "Reply confirmed via reconciliation (already existed remotely)"
    else:
        logger.info(
            "Comment %s: could not verify remote reply — marking already_replied", comment_id
        )
        record.status = ProcessedComment.STATUS_ALREADY_REPLIED

    record.processed_at = now
    record.save(update_fields=[
        "status", "error_message", "meta_error_code",
        "meta_error_subcode", "meta_fbtrace_id", "processed_at",
    ])
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
    InstagramAccount. NOT persisted — FK constraint would be violated.
    """
    return ProcessedComment(
        instagram_comment_id=comment_id,
        instagram_media_id=media_id,
        commenter_id=commenter_id or "",
        comment_text=comment_text,
        status=ProcessedComment.STATUS_FAILED,
        error_message=error,
        received_at=received_at,
    )
