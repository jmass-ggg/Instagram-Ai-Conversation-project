import json
import logging
from dataclasses import dataclass, field

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class MetaReplyResult:
    success: bool
    message_id: str | None = None
    error: str | None = None


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
        or success=False and error on failure.
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
            response_data = response.json()

            if response.is_success and "message_id" in response_data:
                return MetaReplyResult(
                    success=True,
                    message_id=response_data["message_id"],
                )

            # API returned a non-2xx or missing message_id
            error_detail = response_data.get("error", {})
            if isinstance(error_detail, dict):
                error_msg = error_detail.get("message", f"HTTP {response.status_code}")
            else:
                error_msg = str(error_detail) or f"HTTP {response.status_code}"

            logger.error("Meta private reply failed: %s", error_msg)
            return MetaReplyResult(success=False, error=error_msg)

        except httpx.HTTPError as exc:
            error_msg = f"HTTP error sending private reply: {exc}"
            logger.error(error_msg)
            return MetaReplyResult(success=False, error=error_msg)
        except Exception as exc:
            error_msg = f"Unexpected error sending private reply: {exc}"
            logger.error(error_msg)
            return MetaReplyResult(success=False, error=error_msg)
