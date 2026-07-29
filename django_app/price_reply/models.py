from django.db import models
from django.conf import settings


class Business(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="businesses",
    )
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class InstagramAccount(models.Model):
    business = models.OneToOneField(
        Business,
        on_delete=models.CASCADE,
        related_name="instagram_account",
    )
    instagram_user_id = models.CharField(max_length=255, unique=True)
    # Facebook Page ID linked to the IG account — required by the private reply API
    page_id = models.CharField(max_length=255, blank=True)
    username = models.CharField(max_length=255, blank=True)
    access_token = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.username or self.instagram_user_id


class Product(models.Model):
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="products",
    )
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class InstagramPostProductMapping(models.Model):
    instagram_account = models.ForeignKey(
        InstagramAccount,
        on_delete=models.CASCADE,
        related_name="post_mappings",
    )
    instagram_media_id = models.CharField(max_length=255, unique=True)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="instagram_mappings",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.instagram_media_id} → {self.product}"


class ProcessedComment(models.Model):
    STATUS_RECEIVED = "received"
    STATUS_IGNORED = "ignored"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_RECEIVED, "Received"),
        (STATUS_IGNORED, "Ignored"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
    ]

    instagram_account = models.ForeignKey(
        InstagramAccount,
        on_delete=models.CASCADE,
        related_name="processed_comments",
    )
    instagram_comment_id = models.CharField(max_length=255, unique=True)
    instagram_media_id = models.CharField(max_length=255)
    commenter_id = models.CharField(max_length=255, blank=True)
    comment_text = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_RECEIVED,
    )
    reply_text = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    received_at = models.DateTimeField()
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comment {self.instagram_comment_id} [{self.status}]"
