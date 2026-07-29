from django.conf import settings

from .models import Product


def build_price_reply(product: Product) -> str:
    """
    Compose the private reply message for a price inquiry.

    Template: Hi! The price of {product_name} is {CURRENCY_SYMBOL}{price:.2f}.
    The currency symbol is read from Django settings (CURRENCY_SYMBOL env var).
    """
    currency_symbol = settings.CURRENCY_SYMBOL
    return f"Hi! The price of {product.name} is {currency_symbol}{product.price:.2f}."
