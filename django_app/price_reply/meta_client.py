import json
import logging
from dataclasses import dataclass, field

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

# Meta error codes that mean "already replied" — treat as idempotency, not failure
_ALREADY_REPLIED_MESSAGES = [
    "already has a reply",
    "already replied",
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
    # Structured error fields for diagnostics
    error_code: int | None = None
    error_subcode: int | None = None
    error_type: str | None = None
    fbtrace_id: str | None = None
    http_status: int | None = None
    # Idempotency flag: Meta says comment already has a reply
    already_replied: bool = False
    # Whether this error is worth retrying
    retryable: bool = True


class MetaPrivateReplyClient:
    """
    Sends private replies via the Meta Graph API private reply endpoint.

    POST https://graph.facebook.com/{GRAPH_API_VERSION}/{page_id}/messages
    """

    def send_private_reply(
        self,
        comment_id: str,
        message: str,
        access_token: str,
        page_id: str,
    ) -> MetaReplyResult:
        """
        Send a private reply to the author of a comment.

        Returns MetaReplyResult with success=True and message_id on success,
        or success=False and structured error details on failure.
        """
        graph_api_version = settings.GRAPH_API_VERSION
        url = f"https://graph.facebook.com/{graph_api_version}/{page_id}/messages"

        payload = {
            "recipient": json.dumps({"comment_id": comment_id}),
            "message": json.dumps({"text": message}),
            "access_token": access_token,
        }

        try:
            response = httpx.post(url, data=payload, timeout=10.0)
            fbtrace_id = response.headers.get("x-fb-trace-id")
            response_data = response.json()

            if response.is_success and "message_id" in response_data:
                return MetaReplyResult(
                    success=True,
                    message_id=response_data["message_id"],
                    http_status=response.status_code,
                )

            # Parse structured error
            error_detail = response_data.get("error", {})
            if not isinstance(error_detail, dict):
                error_detail = {}

            error_msg = error_detail.get("message", f"HTTP {response.status_code}")
            error_code = error_detail.get("code")
            error_subcode = error_detail.get("error_subcode")
            error_type = error_detail.get("type")
            if not fbtrace_id:
                fbtrace_id = error_detail.get("fbtrace_id")

            # Detect "already has a reply" idempotency case
            already_replied = any(
                phrase in error_msg.lower() for phrase in _ALREADY_REPLIED_MESSAGES
            )

            # Determine retryability
            retryable = _is_retryable(response.status_code, error_code, already_replied)

            logger.error(
                "Meta private reply failed: %s (code=%s subcode=%s type=%s fbtrace=%s http=%s)",
                error_msg, error_code, error_subcode, error_type, fbtrace_id, response.status_code,
            )

            return MetaReplyResult(
                success=False,
                error=error_msg,
                error_code=error_code,
                error_subcode=error_subcode,
                error_type=error_type,
                fbtrace_id=fbtrace_id,
                http_status=response.status_code,
                already_replied=already_replied,
                retryable=retryable,
            )

        except httpx.TimeoutException as exc:
            error_msg = f"Timeout sending private reply: {exc}"
            logger.error(error_msg)
            return MetaReplyResult(success=False, error=error_msg, retryable=True)

        except httpx.HTTPError as exc:
            error_msg = f"HTTP error sending private reply: {exc}"
            logger.error(error_msg)
            return MetaReplyResult(success=False, error=error_msg, retryable=True)

        except Exception as exc:
            error_msg = f"Unexpected error sending private reply: {exc}"
            logger.error(error_msg)
            return MetaReplyResult(success=False, error=error_msg, retryable=False)

    def get_comment_replies(
        self,
        comment_id: str,
        access_token: str,
    ) -> list[dict]:
        """
        Retrieve existing replies for a comment from the Meta Graph API.
        Returns a list of reply objects with id, message, from fields.
        Returns empty list on any error.
        """
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
                "Could not fetch comment replies for %s: HTTP %s %s",
                comment_id, response.status_code, response.text[:200],
            )
        except Exception as exc:
            logger.warning("Error fetching comment replies for %s: %s", comment_id, exc)
        return []


def _is_retryable(http_status: int, error_code: int | None, already_replied: bool) -> bool:
    """Return False for errors that should never be retried."""
    if already_replied:
        return False
    if error_code in _NON_RETRYABLE_CODES:
        return False
    if http_status in (400, 401, 403):
        return False
    # 429 and 5xx are retryable
    return True
