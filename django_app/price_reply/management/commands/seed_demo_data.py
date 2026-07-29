import os
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from price_reply.models import (
    Business,
    InstagramAccount,
    InstagramPostProductMapping,
    Product,
)

User = get_user_model()


class Command(BaseCommand):
    help = "Seed demo data for local development and testing."

    def handle(self, *args, **options):
        # ── User ──────────────────────────────────────────────────────────────
        user, created = User.objects.get_or_create(
            username="demo_admin",
            defaults={"email": "demo@example.com"},
        )
        if created:
            user.set_password("demo_password")
            user.save()
            self.stdout.write(self.style.SUCCESS("Created user: demo_admin"))
        else:
            self.stdout.write("User already exists: demo_admin")

        # ── Business ──────────────────────────────────────────────────────────
        business, created = Business.objects.get_or_create(
            owner=user,
            defaults={"name": "Demo Business"},
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created business: {business.name}"))
        else:
            self.stdout.write(f"Business already exists: {business.name}")

        # ── Instagram Account ─────────────────────────────────────────────────
        instagram_user_id = os.environ.get("INSTAGRAM_USER_ID", "")
        instagram_username = os.environ.get("INSTAGRAM_USERNAME", "demo_instagram")
        instagram_access_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
        instagram_page_id = os.environ.get("INSTAGRAM_PAGE_ID", "")

        ig_account, created = InstagramAccount.objects.get_or_create(
            instagram_user_id=instagram_user_id,
            defaults={
                "business": business,
                "username": instagram_username,
                "access_token": instagram_access_token,
                "page_id": instagram_page_id,
                "is_active": True,
            },
        )
        if created:
            self.stdout.write(
                self.style.SUCCESS(f"Created Instagram account: {ig_account.username}")
            )
        else:
            self.stdout.write(f"Instagram account already exists: {ig_account.username}")

        # ── Product ───────────────────────────────────────────────────────────
        product_name = os.environ.get("DEMO_PRODUCT_NAME", "Demo Product")
        product_price = Decimal(os.environ.get("DEMO_PRODUCT_PRICE", "9.99"))

        product, created = Product.objects.get_or_create(
            business=business,
            name=product_name,
            defaults={
                "price": product_price,
                "is_active": True,
            },
        )
        if created:
            self.stdout.write(
                self.style.SUCCESS(f"Created product: {product.name} @ {product.price}")
            )
        else:
            self.stdout.write(f"Product already exists: {product.name}")

        # ── Post → Product Mapping ────────────────────────────────────────────
        instagram_media_id = os.environ.get("INSTAGRAM_MEDIA_ID", "")

        mapping, created = InstagramPostProductMapping.objects.get_or_create(
            instagram_media_id=instagram_media_id,
            defaults={
                "instagram_account": ig_account,
                "product": product,
            },
        )
        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created post mapping: media {mapping.instagram_media_id} → {mapping.product}"
                )
            )
        else:
            self.stdout.write(
                f"Post mapping already exists for media ID: {mapping.instagram_media_id}"
            )

        self.stdout.write(self.style.SUCCESS("\nSeed complete."))
