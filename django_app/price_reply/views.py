import logging

from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from .serializers import InstagramCommentEventSerializer
from .service import process_comment_event

logger = logging.getLogger(__name__)


@api_view(["POST"])
def instagram_comment(request: Request) -> Response:
    """
    POST /internal/instagram/comments

    Accepts a normalized InstagramCommentEvent from the FastAPI webhook service,
    runs the full comment-to-reply pipeline, and returns HTTP 200.

    Authentication: X-Internal-Service-Secret header (shared secret).
    """
    # ── Authentication ────────────────────────────────────────────────────────
    provided_secret = request.headers.get("X-Internal-Service-Secret", "")
    expected_secret = settings.INTERNAL_SERVICE_SECRET

    if not provided_secret or provided_secret != expected_secret:
        logger.warning("instagram_comment: invalid or missing internal service secret")
        return Response({"detail": "Unauthorized"}, status=401)

    # ── Validation ────────────────────────────────────────────────────────────
    serializer = InstagramCommentEventSerializer(data=request.data)
    if not serializer.is_valid():
        logger.warning("instagram_comment: invalid payload: %s", serializer.errors)
        return Response({"detail": "Bad Request", "errors": serializer.errors}, status=400)

    # ── Processing ────────────────────────────────────────────────────────────
    process_comment_event(serializer.validated_data)

    return Response({"detail": "ok"}, status=200)
