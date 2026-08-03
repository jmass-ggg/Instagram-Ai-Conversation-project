import logging
from datetime import datetime, timezone

from django.utils import timezone as dj_timezone

from .intent import is_price_inquiry
from .meta_client import MetaCommentReplyClient
from .models import (
    InstagramAccount,
    InstagramPostProductMapping,
    ProcessedComment,
)
from .reply import build_price_reply

logger = logging.getLogger(__name__)

_COMMENT_TEXT_MAX_LOG = 80  # characters — safe truncation for logging


def process_comment_event(event_data: dict) -> ProcessedComment:
    """
    Orchestrate the full comment-to-public-reply pipeline.

    Steps:
      1. Duplicate / terminal check — skip if already processed
      2. Resolve InstagramAccount by instagram_account_id (NOT commenter_id)
      3. Atomic create-or-get ProcessedComment
      4. Price intent check
      5. Resolve post mapping → product
      6. Compose and persist reply text BEFORE calling Meta
      7. Send PRIVATE DM via /{page_id}/messages with recipient comment_id
      8. Handle "already replied" as idempotency
      9. Save final status
    """
    comment_id = event_data["comment_id"]
    instagram_account_id = event_data["instagram_account_id"]
    media_id = event_data["media_id"]
    # commenter_id is stored for records but NEVER used to filter/gate processing
    commenter_id = event_data.get("commenter_id", "") or ""
    comment_text = event_data["comment_text"]
    timestamp = event_data["timestamp"]

    # Safe log — never log tokens or secrets
    logger.info(
        "Processing comment event: account=%s comment=%s media=%s text=%.80r",
        instagram_account_id, comment_id, media_id,
        comment_text[:_COMMENT_TEXT_MAX_LOG],
    )

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

    # ── 1. Check for existing terminal record ─────────────────────────────────
    try:
        existing = ProcessedComment.objects.get(instagram_comment_id=comment_id)
        if existing.is_terminal:
            logger.info(
                "Duplicate webhook for comment %s — terminal status=%s, skipping",
                comment_id, existing.status,
            )
            return existing
        logger.info(
            "Comment %s exists with non-terminal status=%s — reprocessing",
            comment_id, existing.status,
        )
    except ProcessedComment.DoesNotExist:
        existing = None

    # ── 2. Resolve InstagramAccount by account ID (not commenter ID) ──────────
    # The commenter can be ANY public Instagram user — no filtering on commenter_id
    try:
        account = InstagramAccount.objects.get(instagram_user_id=instagram_account_id)
    except InstagramAccount.DoesNotExist:
        logger.warning(
            "InstagramAccount not found for instagram_account_id=%s (comment=%s)",
            instagram_account_id, comment_id,
        )
        return _make_stub_failed_comment(
            comment_id=comment_id,
            media_id=media_id,
            commenter_id=commenter_id,
            comment_text=comment_text,
            received_at=received_at,
            error=f"InstagramAccount not found: {instagram_account_id}",
        )

    if not account.is_active:
        logger.warning("InstagramAccount %s is inactive", instagram_account_id)
        return _make_stub_failed_comment(
            comment_id=comment_id,
            media_id=media_id,
            commenter_id=commenter_id,
            comment_text=comment_text,
            received_at=received_at,
            error=f"InstagramAccount is inactive: {instagram_account_id}",
        )

    if not account.access_token:
        logger.warning("InstagramAccount %s has no access token", instagram_account_id)
        return _make_stub_failed_comment(
            comment_id=comment_id,
            media_id=media_id,
            commenter_id=commenter_id,
            comment_text=comment_text,
            received_at=received_at,
            error=f"InstagramAccount has no access token: {instagram_account_id}",
        )

    # ── 3. Atomic create-or-get ProcessedComment ──────────────────────────────
    record, created = ProcessedComment.objects.get_or_create(
        instagram_comment_id=comment_id,
        defaults={
            "instagram_account": account,
            "instagram_media_id": media_id,
            "commenter_id": commenter_id,
            "comment_text": comment_text,
            "status": ProcessedComment.STATUS_RECEIVED,
            "received_at": received_at,
        },
    )
    if not created:
        if record.is_terminal:
            logger.info(
                "Race-condition duplicate: comment %s terminal=%s", comment_id, record.status
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
        ).get(instagram_account=account, instagram_media_id=media_id)
    except InstagramPostProductMapping.DoesNotExist:
        _save_failed(record, f"No post mapping for media_id={media_id}")
        logger.warning(
            "No post mapping: media=%s account=%s comment=%s",
            media_id, instagram_account_id, comment_id,
        )
        return record

    product = mapping.product

    if not product.is_active:
        _save_failed(record, f"Product {product.pk} is inactive")
        return record

    if product.business_id != account.business_id:
        _save_failed(
            record,
            f"Product {product.pk} belongs to a different business than account {account.pk}",
        )
        return record

    # ── 6. Compose and persist reply BEFORE calling Meta ─────────────────────
    reply_text = build_price_reply(product)
    record.reply_text = reply_text
    record.save(update_fields=["reply_text"])

    # ── 7. Send PRIVATE DM to commenter ──────────────────────────────────────
    client = MetaCommentReplyClient()
    result = client.send_private_dm(
        comment_id=comment_id,
        message=reply_text,
        access_token=account.access_token,
        page_id=account.page_id,
    )

    now = dj_timezone.now()

    # ── 8. Handle result ──────────────────────────────────────────────────────
    if result.success:
        record.status = ProcessedComment.STATUS_SENT
        record.processed_at = now
        record.save(update_fields=["status", "processed_at"])
        logger.info(
            "Public reply posted: comment=%s reply_id=%s status=sent",
            comment_id, result.message_id,
        )
        return record

    # Capture structured diagnostics — never log the token
    record.error_message = result.error or "Unknown Meta API error"
    record.meta_error_code = result.error_code
    record.meta_error_subcode = result.error_subcode
    record.meta_fbtrace_id = result.fbtrace_id or ""

    logger.error(
        "Meta reply failed: comment=%s http=%s code=%s subcode=%s fbtrace=%s msg=%s",
        comment_id,
        result.http_status,
        result.error_code,
        result.error_subcode,
        result.fbtrace_id,
        result.error,
    )

    if result.already_replied:
        record = _reconcile_already_replied(record, comment_id, reply_text, account, client, now)
    else:
        record.status = ProcessedComment.STATUS_FAILED
        record.processed_at = now
        record.save(update_fields=[
            "status", "error_message", "meta_error_code",
            "meta_error_subcode", "meta_fbtrace_id", "processed_at",
        ])

    return record


def _reconcile_already_replied(
    record: ProcessedComment,
    comment_id: str,
    intended_reply: str,
    account,
    client: MetaCommentReplyClient,
    now,
) -> ProcessedComment:
    """Meta returned 'already has a reply' — reconcile rather than fail."""
    replies = client.get_comment_replies(comment_id, account.access_token)
    matched = any(
        (reply.get("from") or {}).get("id", "") == account.instagram_user_id
        and reply.get("message", "").strip() == intended_reply.strip()
        for reply in replies
    )
    if matched:
        record.status = ProcessedComment.STATUS_SENT
        record.error_message = "Confirmed via reconciliation — reply already existed"
        logger.info("Comment %s reconciled — remote reply matches intended text", comment_id)
    else:
        record.status = ProcessedComment.STATUS_ALREADY_REPLIED
        logger.info("Comment %s marked already_replied — could not verify remote reply", comment_id)

    record.processed_at = now
    record.save(update_fields=[
        "status", "error_message", "meta_error_code",
        "meta_error_subcode", "meta_fbtrace_id", "processed_at",
    ])
    return record


def _save_failed(record: ProcessedComment, error: str) -> None:
    record.status = ProcessedComment.STATUS_FAILED
    record.error_message = error
    record.processed_at = dj_timezone.now()
    record.save(update_fields=["status", "error_message", "processed_at"])


def _make_stub_failed_comment(
    *,
    comment_id: str,
    media_id: str,
    commenter_id: str,
    comment_text: str,
    received_at,
    error: str,
) -> ProcessedComment:
    """Unsaved stub returned when no valid InstagramAccount exists."""
    return ProcessedComment(
        instagram_comment_id=comment_id,
        instagram_media_id=media_id,
        commenter_id=commenter_id,
        comment_text=comment_text,
        status=ProcessedComment.STATUS_FAILED,
        error_message=error,
        received_at=received_at,
    )
