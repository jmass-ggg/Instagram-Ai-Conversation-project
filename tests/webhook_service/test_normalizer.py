"""
Property-based tests for InstagramCommentEvent normalization round-trip.
Feature: instagram-price-reply, Property 2: Event normalization preserves all fields (round-trip)
Requirements: 3.1, 3.3, 15.3
"""
import json
from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from webhook_service.app.normalizer import InstagramCommentEvent


# Strategies for each field
_instagram_id = st.text(min_size=1, max_size=64, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"))
_comment_text = st.text(min_size=1, max_size=500)
_optional_id = st.one_of(st.none(), _instagram_id)

# Datetimes with timezone so round-trip through ISO format is lossless
_aware_datetime = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
    timezones=st.just(timezone.utc),
)


# Feature: instagram-price-reply, Property 2: Event normalization preserves all fields (round-trip)
@given(
    instagram_account_id=_instagram_id,
    comment_id=_instagram_id,
    media_id=_instagram_id,
    commenter_id=_optional_id,
    comment_text=_comment_text,
    timestamp=_aware_datetime,
)
@settings(max_examples=200)
def test_event_normalization_round_trip(
    instagram_account_id: str,
    comment_id: str,
    media_id: str,
    commenter_id: str | None,
    comment_text: str,
    timestamp: datetime,
):
    """
    For any valid InstagramCommentEvent, serializing to JSON then deserializing
    SHALL produce an equivalent object with all fields intact.
    Validates: Requirements 3.1, 3.3, 15.3
    """
    original = InstagramCommentEvent(
        instagram_account_id=instagram_account_id,
        comment_id=comment_id,
        media_id=media_id,
        commenter_id=commenter_id,
        comment_text=comment_text,
        timestamp=timestamp,
    )

    # Serialize to JSON (Pydantic v2 model_dump_json) then deserialize back
    json_str = original.model_dump_json()
    restored = InstagramCommentEvent.model_validate_json(json_str)

    assert restored == original
