import re
import string


_PRICE_PHRASES = ["price", "how much", "cost"]


def is_price_inquiry(comment_text: str) -> bool:
    """
    Return True if comment_text contains any price-related phrase.

    Detection is case-insensitive and ignores leading/trailing whitespace
    and punctuation characters.
    """
    # Strip leading/trailing whitespace
    text = comment_text.strip()

    # Remove punctuation characters
    text = text.translate(str.maketrans("", "", string.punctuation))

    # Normalise to lowercase for case-insensitive comparison
    text = text.lower()

    return any(phrase in text for phrase in _PRICE_PHRASES)
