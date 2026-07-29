from rest_framework import serializers


class InstagramCommentEventSerializer(serializers.Serializer):
    """
    Validates the normalized Instagram comment event forwarded by the
    FastAPI webhook service.

    Required fields match the InstagramCommentEvent Pydantic model defined
    in webhook_service/app/normalizer.py.
    """

    instagram_account_id = serializers.CharField()
    comment_id = serializers.CharField()
    media_id = serializers.CharField()
    commenter_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    comment_text = serializers.CharField()
    timestamp = serializers.DateTimeField()
