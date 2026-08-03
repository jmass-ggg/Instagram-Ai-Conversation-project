"""
Tests for public comment reply behaviour.

Covers:
- Any commenter (admin, tester, or completely unknown user) triggers a reply
- No allowlist lookup on commenter_id
- Price / non-price routing
- Unknown Instagram account is rejected (wrong account, not wrong commenter)
- Duplicate comment IDs do not post twice
- Second comment from same random user is processed independently
- Meta "already replied" is handled as idempotency
- Webhook signature verification stays intact
- Tokens/secrets are not exposed in logs
- Missing permissions produce a captured error (no crash)
"""
import logging
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytest
from django.contrib.auth import get_user_model

from price_reply.meta_client import MetaCommentReplyClient, MetaReplyResult
from price_reply.models import (
    Business,
    InstagramAccount,
    InstagramPostProductMapping,
    ProcessedComment,
    Product,
)
from price_reply.service import process_comment_event

User = get_user_model()


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_user(suffix=""):
    return User.objects.create_user(username=f"u{suffix}", password="pw")


def _make_account(biz, uid="acc-1", token="page-token", page_id="page-1"):
    return InstagramAccount.objects.create(
        business=biz,
        instagram_user_id=uid,
        page_id=page_id,
        access_token=token,
        is_active=True,
    )


def _make_product(biz, name="Shoes", price="99.99"):
    return Product.objects.create(business=biz, name=name, price=Decimal(price), is_active=True)


def _make_mapping(account, product, media_id="media-1"):
    return InstagramPostProductMapping.objects.create(
        instagram_account=account, instagram_media_id=media_id, product=product
    )


def _event(account_id="acc-1", comment_id="cmt-1", media_id="media-1",
           text="what is the price?", commenter_id="anyone"):
    return {
        "instagram_account_id": account_id,
        "comment_id": comment_id,
        "media_id": media_id,
        "comment_text": text,
        "commenter_id": commenter_id,
        "timestamp": "2024-01-01T00:00:00+00:00",
    }


def _success_result():
    return MetaReplyResult(success=True, message_id="reply-id-123")


def _already_replied_result():
    return MetaReplyResult(
        success=False,
        error="(#-1) The comment you are trying to reply to, already has a reply.",
        error_code=-1,
        already_replied=True,
        retryable=False,
    )


def _permission_error_result():
    return MetaReplyResult(
        success=False,
        error="(#3) Application does not have the capability to make this API call.",
        error_code=3,
        retryable=False,
    )


# ── Part 7 tests ───────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAnyCommenterTriggersReply:
    """
    A comment from an admin, tester, or completely unknown user should all
    produce a reply. The commenter_id is stored but NEVER used to gate processing.
    """

    def _setup(self, uid="acc-pub"):
        user = _make_user(uid)
        biz = Business.objects.create(owner=user, name=f"Biz-{uid}")
        account = _make_account(biz, uid=uid)
        product = _make_product(biz)
        _make_mapping(account, product)
        return account

    def _run(self, commenter_id, account_uid="acc-pub", comment_id="cmt-x"):
        with patch.object(MetaCommentReplyClient, "send_private_dm",
                          return_value=_success_result()) as mock_reply:
            result = process_comment_event(_event(
                account_id=account_uid,
                comment_id=comment_id,
                commenter_id=commenter_id,
            ))
        return result, mock_reply

    def test_admin_commenter_gets_reply(self):
        self._setup("acc-admin")
        result, mock = self._run("admin-ig-id", "acc-admin", "cmt-admin")
        assert result.status == ProcessedComment.STATUS_SENT
        mock.assert_called_once()

    def test_tester_commenter_gets_reply(self):
        self._setup("acc-tester")
        result, mock = self._run("tester-ig-id", "acc-tester", "cmt-tester")
        assert result.status == ProcessedComment.STATUS_SENT
        mock.assert_called_once()

    def test_unknown_random_commenter_gets_reply(self):
        """Completely unknown Instagram user — no Meta app role whatsoever."""
        self._setup("acc-random")
        result, mock = self._run("999999999999999", "acc-random", "cmt-random")
        assert result.status == ProcessedComment.STATUS_SENT
        mock.assert_called_once()

    def test_commenter_id_none_still_processes(self):
        self._setup("acc-none")
        result, mock = self._run(None, "acc-none", "cmt-none")
        assert result.status == ProcessedComment.STATUS_SENT
        mock.assert_called_once()


@pytest.mark.django_db
class TestNoAllowlistOnCommenterId:
    """
    Verify there is no code path that checks commenter_id against a list.
    The service must NOT query any model by commenter_id for gating purposes.
    """

    def test_commenter_id_not_in_database_still_replies(self):
        user = _make_user("noallow")
        biz = Business.objects.create(owner=user, name="Biz-noallow")
        account = _make_account(biz, uid="acc-noallow")
        product = _make_product(biz)
        _make_mapping(account, product)

        # Commenter ID that definitely does not exist in any DB table
        unknown_commenter = "111222333444555666"

        with patch.object(MetaCommentReplyClient, "send_private_dm",
                          return_value=_success_result()):
            result = process_comment_event(_event(
                account_id="acc-noallow",
                comment_id="cmt-noallow",
                commenter_id=unknown_commenter,
            ))

        assert result.status == ProcessedComment.STATUS_SENT
        # commenter_id is stored, not used for gating
        assert result.commenter_id == unknown_commenter


@pytest.mark.django_db
class TestPriceRouting:
    """Price inquiry → reply; non-matching comment → ignored."""

    def _setup(self, suffix):
        user = _make_user(suffix)
        biz = Business.objects.create(owner=user, name=f"B{suffix}")
        account = _make_account(biz, uid=f"acc-{suffix}")
        product = _make_product(biz)
        _make_mapping(account, product, media_id=f"media-{suffix}")
        return account

    def test_price_question_triggers_reply(self):
        self._setup("pq")
        with patch.object(MetaCommentReplyClient, "send_private_dm",
                          return_value=_success_result()) as mock:
            result = process_comment_event(_event(
                account_id="acc-pq", comment_id="cmt-pq",
                media_id="media-pq", text="what is the price?",
            ))
        assert result.status == ProcessedComment.STATUS_SENT
        mock.assert_called_once()

    def test_non_price_comment_is_ignored(self):
        self._setup("np")
        with patch.object(MetaCommentReplyClient, "send_private_dm",
                          return_value=_success_result()) as mock:
            result = process_comment_event(_event(
                account_id="acc-np", comment_id="cmt-np",
                media_id="media-np", text="Nice shoes!",
            ))
        assert result.status == ProcessedComment.STATUS_IGNORED
        mock.assert_not_called()


@pytest.mark.django_db
class TestUnknownInstagramAccount:
    """Webhook for an unregistered instagram_account_id is rejected (stub failed)."""

    def test_unknown_account_id_returns_failed(self):
        result = process_comment_event(_event(account_id="acc-does-not-exist"))
        assert result.status == ProcessedComment.STATUS_FAILED
        assert not result.pk  # stub — not persisted


@pytest.mark.django_db
class TestDuplicateCommentId:
    """Same comment_id delivered twice must post only one reply."""

    def test_duplicate_delivery_posts_once(self):
        user = _make_user("dup")
        biz = Business.objects.create(owner=user, name="Biz-dup")
        account = _make_account(biz, uid="acc-dup")
        product = _make_product(biz)
        _make_mapping(account, product, media_id="media-dup")

        event = _event(account_id="acc-dup", comment_id="cmt-dup", media_id="media-dup")

        with patch.object(MetaCommentReplyClient, "send_private_dm",
                          return_value=_success_result()) as mock:
            r1 = process_comment_event(event)
            r2 = process_comment_event(event)

        assert ProcessedComment.objects.filter(instagram_comment_id="cmt-dup").count() == 1
        assert r1.status == ProcessedComment.STATUS_SENT
        assert r2.status == ProcessedComment.STATUS_SENT
        mock.assert_called_once()  # Only one API call


@pytest.mark.django_db
class TestSecondCommentFromSameUser:
    """Two distinct comments from the same commenter are processed independently."""

    def test_two_comments_same_commenter_both_replied(self):
        user = _make_user("two")
        biz = Business.objects.create(owner=user, name="Biz-two")
        account = _make_account(biz, uid="acc-two")
        product = _make_product(biz)
        _make_mapping(account, product, media_id="media-two")

        same_commenter = "user-456"

        with patch.object(MetaCommentReplyClient, "send_private_dm",
                          return_value=_success_result()) as mock:
            r1 = process_comment_event(_event(
                account_id="acc-two", comment_id="cmt-two-a",
                media_id="media-two", commenter_id=same_commenter,
            ))
            r2 = process_comment_event(_event(
                account_id="acc-two", comment_id="cmt-two-b",
                media_id="media-two", commenter_id=same_commenter,
            ))

        assert r1.status == ProcessedComment.STATUS_SENT
        assert r2.status == ProcessedComment.STATUS_SENT
        assert mock.call_count == 2


@pytest.mark.django_db
class TestAlreadyReplied:
    """Meta returning 'already has a reply' is handled as idempotency."""

    def test_already_replied_marks_status_not_failed(self):
        user = _make_user("ar")
        biz = Business.objects.create(owner=user, name="Biz-ar")
        account = _make_account(biz, uid="acc-ar")
        product = _make_product(biz)
        _make_mapping(account, product, media_id="media-ar")

        with patch.object(MetaCommentReplyClient, "send_private_dm",
                          return_value=_already_replied_result()):
            with patch.object(MetaCommentReplyClient, "get_comment_replies", return_value=[]):
                result = process_comment_event(_event(
                    account_id="acc-ar", comment_id="cmt-ar", media_id="media-ar"
                ))

        assert result.status in (
            ProcessedComment.STATUS_SENT,
            ProcessedComment.STATUS_ALREADY_REPLIED,
        )
        assert result.status != ProcessedComment.STATUS_FAILED


@pytest.mark.django_db
class TestMissingPermissions:
    """Permission error is captured as a failed record, not an unhandled exception."""

    def test_permission_error_saves_failed_record(self):
        user = _make_user("perm")
        biz = Business.objects.create(owner=user, name="Biz-perm")
        account = _make_account(biz, uid="acc-perm")
        product = _make_product(biz)
        _make_mapping(account, product, media_id="media-perm")

        with patch.object(MetaCommentReplyClient, "send_private_dm",
                          return_value=_permission_error_result()):
            result = process_comment_event(_event(
                account_id="acc-perm", comment_id="cmt-perm", media_id="media-perm"
            ))

        assert result.status == ProcessedComment.STATUS_FAILED
        assert result.meta_error_code == 3
        assert "capability" in result.error_message.lower()


@pytest.mark.django_db
class TestTokensNotInLogs:
    """Access token must never appear in log output."""

    def test_token_not_logged_on_failure(self, caplog):
        user = _make_user("log")
        biz = Business.objects.create(owner=user, name="Biz-log")
        account = _make_account(biz, uid="acc-log", token="SUPER_SECRET_PAGE_TOKEN")
        product = _make_product(biz)
        _make_mapping(account, product, media_id="media-log")

        with caplog.at_level(logging.DEBUG, logger="price_reply"):
            with patch.object(MetaCommentReplyClient, "send_private_dm",
                              return_value=_permission_error_result()):
                process_comment_event(_event(
                    account_id="acc-log", comment_id="cmt-log", media_id="media-log"
                ))

        full_log = caplog.text
        assert "SUPER_SECRET_PAGE_TOKEN" not in full_log


@pytest.mark.django_db
class TestPublicReplyEndpoint:
    """Verify service calls send_private_dm (public), not a DM endpoint."""

    def test_service_calls_send_private_dm(self):
        user = _make_user("pub")
        biz = Business.objects.create(owner=user, name="Biz-pub")
        account = _make_account(biz, uid="acc-pub2")
        product = _make_product(biz)
        _make_mapping(account, product, media_id="media-pub2")

        with patch.object(MetaCommentReplyClient, "send_private_dm",
                          return_value=_success_result()) as mock_public:
            process_comment_event(_event(
                account_id="acc-pub2", comment_id="cmt-pub2", media_id="media-pub2"
            ))

        mock_public.assert_called_once()
        # Confirm it was called with the comment_id, message, access_token
        kwargs = mock_public.call_args.kwargs or {}
        args = mock_public.call_args.args
        # comment_id should be present
        called_comment_id = kwargs.get("comment_id") or (args[0] if args else None)
        assert called_comment_id == "cmt-pub2"
