"""
Django forwarding client.

Forwards normalized InstagramCommentEvent objects to the Django internal
endpoint using HTTPX.

Requirements: 3.4, 4.1
"""
import logging

import httpx

from .normalizer import InstagramCommentEvent
from .settings import settings

logger = logging.getLogger(__name__)


async def forward_comment_event(event: InstagramCommentEvent) -> None:
    """
    POST a single normalized comment event to Django's internal endpoint.

    Adds the X-Internal-Service-Secret header for authentication.
    Raises httpx.HTTPError on any transport or HTTP error so the caller
    can decide whether to log and swallow (Requirement 3.5).

    Requirements: 3.4, 4.1
    """
    url = f"{settings.DJANGO_INTERNAL_URL.rstrip('/')}/internal/instagram/comments"
    headers = {
        "Content-Type": "application/json",
        "X-Internal-Service-Secret": settings.INTERNAL_SERVICE_SECRET,
    }
    payload = event.model_dump_json()

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, content=payload, headers=headers)
        response.raise_for_status()
