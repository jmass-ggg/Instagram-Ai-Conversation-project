from django.contrib import admin
from .models import (
    Business,
    InstagramAccount,
    Product,
    InstagramPostProductMapping,
    ProcessedComment,
)


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at")
    search_fields = ("name",)


@admin.register(InstagramAccount)
class InstagramAccountAdmin(admin.ModelAdmin):
    list_display = ("username", "instagram_user_id", "business", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("username", "instagram_user_id")
    # Never display access_token in list view
    exclude = ("access_token",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "business", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(InstagramPostProductMapping)
class InstagramPostProductMappingAdmin(admin.ModelAdmin):
    list_display = ("instagram_media_id", "instagram_account", "product", "created_at")
    search_fields = ("instagram_media_id",)


@admin.register(ProcessedComment)
class ProcessedCommentAdmin(admin.ModelAdmin):
    list_display = (
        "instagram_comment_id",
        "instagram_account",
        "status",
        "received_at",
        "processed_at",
    )
    list_filter = ("status",)
    search_fields = ("instagram_comment_id", "commenter_id")
    readonly_fields = ("created_at",)
