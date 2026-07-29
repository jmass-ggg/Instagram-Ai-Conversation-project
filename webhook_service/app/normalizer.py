"""
Webhook event normalization.

Converts raw Meta webhook payloads into clean InstagramCommentEvent objects.
Requirements: 3.1, 3.2, 3.3
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class InstagramCommentEvent(BaseModel):
    """
    Normalized representation of a single Instagram comment event.
    Requirement 3.3
    """

    instagram_account_id: str
    comment_id: str
    media_id: str
    commenter_id: str | None = None
    comment_text: str
    timestamp: datetime


def extract_comment_events(payload: dict[str, Any]) -> list[InstagramCommentEvent]:
    """
    Extract comment events from a raw Meta webhook payload.

    Iterates over every entry → changes item and keeps only those whose
    `field` is "comments". All other fields (message-read, delivery,
    account updates, deleted comments, unsupported types) are silently
    ignored per Requirements 3.1, 3.2.
    """
    events: list[InstagramCommentEvent] = []

    for entry in payload.get("entry", []):
        instagram_account_id: str = str(entry.get("id", ""))

        for change in entry.get("changes", []):
            # Only process comment fields; ignore everything else (Requirement 3.2)
            if change.get("field") != "comments":
                continue

            value: dict[str, Any] = change.get("value", {})

            # Deleted comments have no "text" field — skip them (Requirement 3.2)
            comment_text = value.get("text")
            if comment_text is None:
                continue

            comment_id: str = str(value.get("id", ""))
            media_id: str = str(value.get("media", {}).get("id", ""))

            # commenter_id is optional (Requirement 3.3)
            from_info = value.get("from", {})
            commenter_id: str | None = str(from_info["id"]) if from_info.get("id") else None

            # timestamp may be an ISO string or a unix int (defensive parsing)
            raw_ts = value.get("timestamp") or entry.get("time")
            if isinstance(raw_ts, int):
                timestamp = datetime.utcfromtimestamp(raw_ts)
            else:
                timestamp = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))

            events.append(
                InstagramCommentEvent(
                    instagram_account_id=instagram_account_id,
                    comment_id=comment_id,
                    media_id=media_id,
                    commenter_id=commenter_id,
                    comment_text=comment_text,
                    timestamp=timestamp,
                )
            )

    return events
