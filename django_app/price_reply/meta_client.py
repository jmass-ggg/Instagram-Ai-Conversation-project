import logging
from dataclasses import dataclass

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

# Meta error messages that mean "already replied" — treat as idempotency
_ALREADY_REPLIED_MESSAGES = [
    "already has a reply",
    "already replied",
    "duplicate reply",
]

# Non-retryable Meta error codes
_NON_RETRYABLE_CODES = {
    3,    # App capability
    10,   # Permission denied
    100,  # Invalid parameter / object doesn't exist
    190,  # Invalid/expired token
    200,  # Permission error
    -1,   # Already has a reply
}


@dataclass
class MetaReplyResult:
    success: bool
    message_id: str | None = None
    error: str | None = None
    error_code: int | None = None
    error_subcode: int | None = None
    error_type: str | None = None
    fbtrace_id: str | None = None
    http_status: int | None = None
    already_replied: bool = False
    retryable: bool = True


class MetaCommentReplyClient:
    """
    Handles both private DM replies and public comment replies via Meta Graph API.
    """

    def send_private_dm(
        self,
        comment_id: str,
        message: str,
        access_token: str,
        page_id: str,
    ) -> MetaReplyResult:
        """
        Send a PRIVATE DM to the commenter's Instagram inbox.

        Uses POST /{GRAPH_API_VERSION}/{page_id}/messages
        with recipient: {"comment_id": "<comment_id>"}

        Requires: instagram_manage_messages + pages_messaging permissions.
        The reply lands in the commenter's DM inbox, not under the comment.
        """
        import json as _json
        graph_api_version = settings.GRAPH_API_VERSION
        url = f"https://graph.facebook.com/{graph_api_version}/{page_id}/messages"

        try:
            response = httpx.post(
                url,
                data={
                    "recipient": _json.dumps({"comment_id": comment_id}),
                    "message": _json.dumps({"text": message}),
                    "access_token": access_token,
                },
                timeout=10.0,
            )
            fbtrace_id = response.headers.get("x-fb-trace-id")
            response_data = response.json()

            if response.is_success and "message_id" in response_data:
                logger.info(
                    "Private DM sent for comment %s — message_id=%s",
                    comment_id, response_data["message_id"],
                )
                return MetaReplyResult(
                    success=True,
                    message_id=response_data["message_id"],
                    http_status=response.status_code,
                )

            return self._parse_error(response_data, response.status_code, fbtrace_id, comment_id)

        except httpx.TimeoutException as exc:
            logger.error("Timeout sending DM for comment %s: %s", comment_id, exc)
            return MetaReplyResult(success=False, error=f"Timeout: {exc}", retryable=True)
        except httpx.HTTPError as exc:
            logger.error("HTTP error sending DM for comment %s: %s", comment_id, exc)
            return MetaReplyResult(success=False, error=f"HTTP error: {exc}", retryable=True)
        except Exception as exc:
            logger.error("Unexpected error sending DM for comment %s: %s", comment_id, exc)
            return MetaReplyResult(success=False, error=f"Unexpected: {exc}", retryable=False)

    def post_comment_reply(
        self,
        comment_id: str,
        message: str,
        access_token: str,
    ) -> MetaReplyResult:
        """
        Post a PUBLIC reply beneath the comment.

        Uses POST /{GRAPH_API_VERSION}/{comment_id}/replies
        Requires: instagram_manage_comments permission.
        """
        graph_api_version = settings.GRAPH_API_VERSION
        url = f"https://graph.facebook.com/{graph_api_version}/{comment_id}/replies"

        try:
            response = httpx.post(
                url,
                data={"message": message, "access_token": access_token},
                timeout=10.0,
            )
            fbtrace_id = response.headers.get("x-fb-trace-id")
            response_data = response.json()

            if response.is_success and "id" in response_data:
                logger.info(
                    "Public reply posted to comment %s — reply_id=%s",
                    comment_id, response_data["id"],
                )
                return MetaReplyResult(
                    success=True,
                    message_id=response_data["id"],
                    http_status=response.status_code,
                )

            return self._parse_error(response_data, response.status_code, fbtrace_id, comment_id)

        except httpx.TimeoutException as exc:
            logger.error("Timeout posting reply to comment %s: %s", comment_id, exc)
            return MetaReplyResult(success=False, error=f"Timeout: {exc}", retryable=True)
        except httpx.HTTPError as exc:
            logger.error("HTTP error posting reply to comment %s: %s", comment_id, exc)
            return MetaReplyResult(success=False, error=f"HTTP error: {exc}", retryable=True)
        except Exception as exc:
            logger.error("Unexpected error posting reply to comment %s: %s", comment_id, exc)
            return MetaReplyResult(success=False, error=f"Unexpected: {exc}", retryable=False)

    def _parse_error(self, response_data, http_status, fbtrace_id, comment_id) -> MetaReplyResult:
        error_detail = response_data.get("error", {})
        if not isinstance(error_detail, dict):
            error_detail = {}
        error_msg = error_detail.get("message", f"HTTP {http_status}")
        error_code = error_detail.get("code")
        error_subcode = error_detail.get("error_subcode")
        error_type = error_detail.get("type")
        if not fbtrace_id:
            fbtrace_id = error_detail.get("fbtrace_id")
        already_replied = any(p in error_msg.lower() for p in _ALREADY_REPLIED_MESSAGES)
        retryable = _is_retryable(http_status, error_code, already_replied)
        logger.error(
            "Meta API failed for comment %s: %s (http=%s code=%s subcode=%s fbtrace=%s)",
            comment_id, error_msg, http_status, error_code, error_subcode, fbtrace_id,
        )
        return MetaReplyResult(
            success=False, error=error_msg, error_code=error_code,
            error_subcode=error_subcode, error_type=error_type,
            fbtrace_id=fbtrace_id, http_status=http_status,
            already_replied=already_replied, retryable=retryable,
        )

    def get_comment_replies(
        self,
        comment_id: str,
        access_token: str,
    ) -> list[dict]:
        """Retrieve existing replies for reconciliation. Returns [] on error."""
        graph_api_version = settings.GRAPH_API_VERSION
        url = f"https://graph.facebook.com/{graph_api_version}/{comment_id}/replies"
        try:
            response = httpx.get(
                url,
                params={"fields": "id,message,from", "access_token": access_token},
                timeout=10.0,
            )
            if response.is_success:
                return response.json().get("data", [])
            logger.warning(
                "Could not fetch replies for comment %s: HTTP %s",
                comment_id, response.status_code,
            )
        except Exception as exc:
            logger.warning("Error fetching replies for comment %s: %s", comment_id, exc)
        return []


# Keep old name as alias so existing tests importing MetaPrivateReplyClient still work
MetaPrivateReplyClient = MetaCommentReplyClient


def _is_retryable(http_status: int, error_code: int | None, already_replied: bool) -> bool:
    if already_replied:
        return False
    if error_code in _NON_RETRYABLE_CODES:
        return False
    if http_status in (400, 401, 403):
        return False
    return True
