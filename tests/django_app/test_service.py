"""
Property-based and unit tests for the Django service layer.

Properties covered:
  Property 6: Duplicate comment idempotence        (Requirements 5.1, 5.2, 5.3)
  Property 7: Non-price comments are ignored       (Requirements 6.4)
  Property 8: Failed resolution leaves status=failed (Requirements 7.2, 7.3, 7.4, 8.2, 8.3)
  Property 9: Cross-business product isolation     (Requirements 8.5)

Unit tests covered:
  Internal endpoint authentication / validation    (Requirements 4.1, 4.2, 4.3)
"""
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.urls import reverse

from hypothesis import given, settings as hyp_settings, HealthCheck
from hypothesis import strategies as st

from price_reply.models import (
    Business,
    InstagramAccount,
    Product,
    InstagramPostProductMapping,
    ProcessedComment,
)
from price_reply.service import process_comment_event
from price_reply.meta_client import MetaReplyResult

User = get_user_model()

# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_user(suffix=""):
    return User.objects.create_user(username=f"testuser{suffix}", password="pw")


def _make_business(user, suffix=""):
    return Business.objects.create(owner=user, name=f"Biz{suffix}")


def _make_account(business, uid="acc-001", active=True, token="tok"):
    return InstagramAccount.objects.create(
        business=business,
        instagram_user_id=uid,
        page_id="page-001",
        access_token=token,
        is_active=active,
    )


def _make_product(business, name="Widget", price="9.99", active=True):
    return Product.objects.create(
        business=business,
        name=name,
        price=Decimal(price),
        is_active=active,
    )


def _make_mapping(account, product, media_id="media-001"):
    return InstagramPostProductMapping.objects.create(
        instagram_account=account,
        instagram_media_id=media_id,
        product=product,
    )


def _base_event(account_id="acc-001", comment_id="cmt-001", media_id="media-001", text="price?"):
    return {
        "instagram_account_id": account_id,
        "comment_id": comment_id,
        "media_id": media_id,
        "comment_text": text,
        "timestamp": "2024-01-01T00:00:00+00:00",
    }


# ── Property 6: Duplicate comment idempotence ──────────────────────────────────

@pytest.mark.django_db
class TestDuplicateIdempotence:
    """
    Feature: instagram-price-reply, Property 6: Duplicate comment idempotence
    Validates: Requirements 5.1, 5.2, 5.3
    """

    def test_processing_same_comment_twice_creates_one_record(self):
        user = _make_user("dup")
        biz = _make_business(user, "dup")
        account = _make_account(biz, uid="acc-dup")
        product = _make_product(biz)
        _make_mapping(account, product, media_id="media-dup")

        event = _base_event(account_id="acc-dup", comment_id="cmt-dup", media_id="media-dup")

        with patch("price_reply.service.MetaPrivateReplyClient") as MockClient:
            MockClient.return_value.send_private_reply.return_value = MetaReplyResult(
                success=True, message_id="msg-1"
            )
            first = process_comment_event(event)
            second = process_comment_event(event)

        # Exactly one DB record
        count = ProcessedComment.objects.filter(instagram_comment_id="cmt-dup").count()
        assert count == 1

        # Both calls return the same comment id
        assert first.instagram_comment_id == second.instagram_comment_id

        # Meta API called only once (first processing)
        assert MockClient.return_value.send_private_reply.call_count == 1

    @given(comment_id=st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_")))
    @hyp_settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
    @pytest.mark.django_db
    def test_duplicate_idempotence_property(self, comment_id):
        """
        Feature: instagram-price-reply, Property 6: Duplicate comment idempotence
        For any comment_id, processing it twice results in exactly one ProcessedComment.
        Validates: Requirements 5.1, 5.2, 5.3
        """
        # Fixed account/media so setup is always idempotent across hypothesis runs
        uid = "acc-prop6-fixed"
        mid = "media-prop6-fixed"

        # Clean up any prior ProcessedComment with this comment_id
        ProcessedComment.objects.filter(instagram_comment_id=comment_id).delete()

        # Ensure shared fixtures exist (idempotent get_or_create)
        user, _ = User.objects.get_or_create(username="prop6user", defaults={"password": "pw"})
        biz, _ = Business.objects.get_or_create(owner=user, defaults={"name": "Prop6Biz"})
        account, _ = InstagramAccount.objects.get_or_create(
            instagram_user_id=uid,
            defaults={"business": biz, "page_id": "pg6", "access_token": "tok6"},
        )
        product, _ = Product.objects.get_or_create(
            business=biz, name="Prop6Product", defaults={"price": Decimal("5.00")}
        )
        InstagramPostProductMapping.objects.get_or_create(
            instagram_media_id=mid,
            defaults={"instagram_account": account, "product": product},
        )

        event = _base_event(account_id=uid, comment_id=comment_id, media_id=mid)

        with patch("price_reply.service.MetaPrivateReplyClient") as MockClient:
            MockClient.return_value.send_private_reply.return_value = MetaReplyResult(
                success=True, message_id="msg-x"
            )
            process_comment_event(event)
            process_comment_event(event)

        count = ProcessedComment.objects.filter(instagram_comment_id=comment_id).count()
        assert count == 1
        assert MockClient.return_value.send_private_reply.call_count == 1


# ── Property 7: Non-price comments are ignored ────────────────────────────────

@pytest.mark.django_db
class TestNonPriceIgnored:
    """
    Feature: instagram-price-reply, Property 7: Non-price comments are ignored, not failed
    Validates: Requirements 6.4
    """

    def test_non_price_comment_status_is_ignored(self):
        user = _make_user("np")
        biz = _make_business(user, "np")
        account = _make_account(biz, uid="acc-np")
        product = _make_product(biz)
        _make_mapping(account, product, media_id="media-np")

        event = _base_event(
            account_id="acc-np",
            comment_id="cmt-np",
            media_id="media-np",
            text="Nice photo!",
        )

        with patch("price_reply.service.MetaPrivateReplyClient") as MockClient:
            result = process_comment_event(event)
            assert MockClient.return_value.send_private_reply.call_count == 0

        assert result.status == ProcessedComment.STATUS_IGNORED

    @given(
        comment_text=st.text(min_size=1, max_size=100).filter(
            lambda t: "price" not in t.lower()
            and "how much" not in t.lower()
            and "cost" not in t.lower()
        )
    )
    @hyp_settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    @pytest.mark.django_db
    def test_non_price_ignored_property(self, comment_text):
        """
        Feature: instagram-price-reply, Property 7: Non-price comments are ignored, not failed
        For any comment_text containing none of the trigger phrases, status is ignored
        and no Meta API call is made.
        Validates: Requirements 6.4
        """
        uid = "acc-prop7"
        mid = "media-prop7"
        cid = f"cmt-prop7-{abs(hash(comment_text)) % 10_000_000}"

        ProcessedComment.objects.filter(instagram_comment_id=cid).delete()
        if not InstagramAccount.objects.filter(instagram_user_id=uid).exists():
            user = _make_user("prop7")
            biz = _make_business(user, "prop7")
            account = _make_account(biz, uid=uid)
            product = _make_product(biz)
            _make_mapping(account, product, media_id=mid)

        event = _base_event(account_id=uid, comment_id=cid, media_id=mid, text=comment_text)

        with patch("price_reply.service.MetaPrivateReplyClient") as MockClient:
            result = process_comment_event(event)
            assert MockClient.return_value.send_private_reply.call_count == 0

        assert result.status == ProcessedComment.STATUS_IGNORED


# ── Property 8: Failed resolution leaves status as failed ─────────────────────

@pytest.mark.django_db
class TestResolutionFailures:
    """
    Feature: instagram-price-reply, Property 8: Failed resolution leaves status as failed
    Validates: Requirements 7.2, 7.3, 7.4, 8.2, 8.3
    """

    def test_unknown_account_returns_failed_stub(self):
        event = _base_event(account_id="no-such-account", comment_id="cmt-no-acc")
        with patch("price_reply.service.MetaPrivateReplyClient") as MockClient:
            result = process_comment_event(event)
            assert MockClient.return_value.send_private_reply.call_count == 0
        assert result.status == ProcessedComment.STATUS_FAILED

    def test_inactive_account_returns_failed(self):
        user = _make_user("ia")
        biz = _make_business(user, "ia")
        account = _make_account(biz, uid="acc-inactive", active=False)

        event = _base_event(account_id="acc-inactive", comment_id="cmt-ia")
        with patch("price_reply.service.MetaPrivateReplyClient") as MockClient:
            result = process_comment_event(event)
            assert MockClient.return_value.send_private_reply.call_count == 0
        assert result.status == ProcessedComment.STATUS_FAILED

    def test_no_access_token_returns_failed(self):
        user = _make_user("nt")
        biz = _make_business(user, "nt")
        account = _make_account(biz, uid="acc-notoken", token="")

        event = _base_event(account_id="acc-notoken", comment_id="cmt-nt")
        with patch("price_reply.service.MetaPrivateReplyClient") as MockClient:
            result = process_comment_event(event)
            assert MockClient.return_value.send_private_reply.call_count == 0
        assert result.status == ProcessedComment.STATUS_FAILED

    def test_no_post_mapping_returns_failed(self):
        user = _make_user("nm")
        biz = _make_business(user, "nm")
        account = _make_account(biz, uid="acc-nm")
        # No mapping created

        event = _base_event(account_id="acc-nm", comment_id="cmt-nm", text="price?")
        with patch("price_reply.service.MetaPrivateReplyClient") as MockClient:
            result = process_comment_event(event)
            assert MockClient.return_value.send_private_reply.call_count == 0
        assert result.status == ProcessedComment.STATUS_FAILED

    def test_inactive_product_returns_failed(self):
        user = _make_user("ip")
        biz = _make_business(user, "ip")
        account = _make_account(biz, uid="acc-ip")
        product = _make_product(biz, active=False)
        _make_mapping(account, product, media_id="media-ip")

        event = _base_event(account_id="acc-ip", comment_id="cmt-ip", media_id="media-ip", text="price?")
        with patch("price_reply.service.MetaPrivateReplyClient") as MockClient:
            result = process_comment_event(event)
            assert MockClient.return_value.send_private_reply.call_count == 0
        assert result.status == ProcessedComment.STATUS_FAILED


# ── Property 9: Cross-business product isolation ──────────────────────────────

@pytest.mark.django_db
class TestCrossBusinessIsolation:
    """
    Feature: instagram-price-reply, Property 9: Cross-business product isolation
    Validates: Requirements 8.5
    """

    def test_product_from_different_business_fails(self):
        user = _make_user("xb")

        # Business A owns the Instagram account
        biz_a = _make_business(user, "xb-a")
        account = _make_account(biz_a, uid="acc-xb")

        # Business B owns the product
        biz_b = _make_business(user, "xb-b")
        product = _make_product(biz_b, name="Other Widget")

        # Mapping links account (biz_a) to product (biz_b) — cross-business!
        _make_mapping(account, product, media_id="media-xb")

        event = _base_event(account_id="acc-xb", comment_id="cmt-xb", media_id="media-xb", text="price?")

        with patch("price_reply.service.MetaPrivateReplyClient") as MockClient:
            result = process_comment_event(event)
            assert MockClient.return_value.send_private_reply.call_count == 0

        assert result.status == ProcessedComment.STATUS_FAILED
        assert ProcessedComment.objects.get(instagram_comment_id="cmt-xb").status == ProcessedComment.STATUS_FAILED


# ── Unit tests: Internal endpoint authentication ───────────────────────────────

@pytest.mark.django_db
class TestInternalEndpointAuth:
    """
    Unit tests for POST /internal/instagram/comments authentication and validation.
    Validates: Requirements 4.1, 4.2, 4.3
    """

    url = "/internal/instagram/comments"

    _valid_payload = {
        "instagram_account_id": "acc-auth",
        "comment_id": "cmt-auth",
        "media_id": "media-auth",
        "comment_text": "price?",
        "timestamp": "2024-01-01T00:00:00Z",
    }

    def _post(self, client, payload=None, secret=None):
        headers = {}
        if secret is not None:
            headers["HTTP_X_INTERNAL_SERVICE_SECRET"] = secret
        return client.post(
            self.url,
            data=payload or self._valid_payload,
            content_type="application/json",
            **headers,
        )

    def test_missing_secret_returns_401(self, client, settings):
        settings.INTERNAL_SERVICE_SECRET = "correct-secret"
        response = self._post(client)
        assert response.status_code == 401

    def test_wrong_secret_returns_401(self, client, settings):
        settings.INTERNAL_SERVICE_SECRET = "correct-secret"
        response = self._post(client, secret="wrong-secret")
        assert response.status_code == 401

    def test_valid_secret_malformed_body_returns_400(self, client, settings):
        settings.INTERNAL_SERVICE_SECRET = "correct-secret"
        response = self._post(client, payload={"bad": "data"}, secret="correct-secret")
        assert response.status_code == 400

    def test_valid_request_returns_200(self, client, settings):
        settings.INTERNAL_SERVICE_SECRET = "correct-secret"

        user = _make_user("endpt")
        biz = _make_business(user, "endpt")
        account = _make_account(biz, uid="acc-auth")
        product = _make_product(biz)
        _make_mapping(account, product, media_id="media-auth")

        with patch("price_reply.service.MetaPrivateReplyClient") as MockClient:
            MockClient.return_value.send_private_reply.return_value = MetaReplyResult(
                success=True, message_id="msg-ok"
            )
            response = self._post(client, secret="correct-secret")

        assert response.status_code == 200
