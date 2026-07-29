import sys
import os

# Ensure the instagram-price-reply directory is on sys.path so that
# `webhook_service` and `django_app` can be imported directly.
_root = os.path.dirname(__file__)
sys.path.insert(0, _root)
# Also add django_app so Django project packages (config, price_reply) are importable
sys.path.insert(0, os.path.join(_root, "django_app"))
