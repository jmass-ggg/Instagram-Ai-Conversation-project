"""
Property-based tests for price intent detection.
Feature: instagram-price-reply, Property 3: Price intent detection — positive matches
Requirements: 6.2
"""
import string

from hypothesis import given, settings
from hypothesis import strategies as st

from price_reply.intent import is_price_inquiry


_TRIGGER_PHRASES = ["price", "how much", "cost"]

# Strategy: pick a trigger phrase, randomly change its case, then wrap it in
# arbitrary surrounding text (which itself must not be empty so the phrase is
# always present inside a larger string).
_trigger_phrase_strategy = st.sampled_from(_TRIGGER_PHRASES)


def _random_case(phrase: str) -> str:
    """Return the phrase with each character independently upper- or lower-cased."""
    return phrase  # Hypothesis will vary this through text strategies below


@st.composite
def strings_containing_trigger(draw) -> str:
    """
    Composite strategy: a string that contains at least one trigger phrase in an
    arbitrary case, surrounded by arbitrary non-empty text on either side.
    """
    phrase = draw(_trigger_phrase_strategy)

    # Vary the case of each character in the phrase
    cased_chars = [
        draw(st.sampled_from([c.upper(), c.lower()])) for c in phrase
    ]
    cased_phrase = "".join(cased_chars)

    prefix = draw(st.text(min_size=0, max_size=30))
    suffix = draw(st.text(min_size=0, max_size=30))

    return prefix + cased_phrase + suffix


# Feature: instagram-price-reply, Property 3: Price intent detection — positive matches
@given(text=strings_containing_trigger())
@settings(max_examples=200)
def test_price_intent_positive_matches(text: str):
    """
    For any string containing price/how much/cost in any mix of case with any
    surrounding characters, is_price_inquiry SHALL return True.
    Validates: Requirements 6.2
    """
    assert is_price_inquiry(text) is True
