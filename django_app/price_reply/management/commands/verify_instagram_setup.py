"""
Management command: verify_instagram_setup

Safe diagnostic that checks:
- Access token validity (via /debug_token)
- Page ID is correct
- Page is connected to an Instagram professional account
- Instagram account ID matches the DB record
- Page is subscribed to the app
- Token contains required scopes
- Token is not expired

Never prints full tokens or secrets.
"""
import httpx
from django.conf import settings
from django.core.management.base import BaseCommand

from price_reply.models import InstagramAccount

REQUIRED_SCOPES = {
    "instagram_basic",
    "instagram_manage_comments",
    "pages_manage_metadata",
    "pages_read_engagement",
    "pages_show_list",
}


def _mask(token: str) -> str:
    """Show only first 10 and last 4 characters."""
    if not token or len(token) < 20:
        return "***"
    return f"{token[:10]}...{token[-4:]}"


class Command(BaseCommand):
    help = "Verify Meta/Instagram configuration without exposing credentials."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix-subscription",
            action="store_true",
            help="Subscribe the Page to the app if not already subscribed.",
        )

    def handle(self, *args, **options):
        account = InstagramAccount.objects.select_related("business").first()
        if not account:
            self.stderr.write(self.style.ERROR("No InstagramAccount found in database. Run seed_demo_data first."))
            return

        token = account.access_token
        page_id = account.page_id
        ig_user_id = account.instagram_user_id
        graph_version = settings.GRAPH_API_VERSION

        self.stdout.write(f"\nInstagram account  : {account.username} (DB id={account.pk})")
        self.stdout.write(f"instagram_user_id  : {ig_user_id}")
        self.stdout.write(f"page_id            : {page_id}")
        self.stdout.write(f"access_token       : {_mask(token)}")
        self.stdout.write(f"Graph API version  : {graph_version}\n")

        ok = True

        # ── 1. Token debug ────────────────────────────────────────────────────
        self.stdout.write("── Token debug ──────────────────────────────────────────")
        try:
            r = httpx.get(
                f"https://graph.facebook.com/{graph_version}/debug_token",
                params={"input_token": token, "access_token": token},
                timeout=10,
            )
            data = r.json().get("data", {})
            if not data:
                self.stdout.write(self.style.ERROR(f"  debug_token error: {r.json()}"))
                ok = False
            else:
                valid = data.get("is_valid", False)
                expires = data.get("expires_at", 0)
                token_type = data.get("type", "unknown")
                app_id = data.get("app_id", "unknown")
                scopes = set(data.get("scopes", []))

                self.stdout.write(f"  valid       : {valid}")
                self.stdout.write(f"  token_type  : {token_type}")
                self.stdout.write(f"  app_id      : {app_id}")
                self.stdout.write(f"  expires_at  : {expires} (0 = never)")

                missing = REQUIRED_SCOPES - scopes
                granted = scopes & REQUIRED_SCOPES
                self.stdout.write(f"  scopes      : {sorted(scopes)}")
                if missing:
                    self.stdout.write(self.style.ERROR(f"  MISSING scopes: {sorted(missing)}"))
                    ok = False
                else:
                    self.stdout.write(self.style.SUCCESS("  All required scopes present"))

                if not valid:
                    self.stdout.write(self.style.ERROR("  Token is NOT valid — regenerate it"))
                    ok = False
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  debug_token request failed: {exc}"))
            ok = False

        # ── 2. Page verification ──────────────────────────────────────────────
        self.stdout.write("\n── Page verification ────────────────────────────────────")
        try:
            r = httpx.get(
                f"https://graph.facebook.com/{graph_version}/{page_id}",
                params={"fields": "id,name,instagram_business_account", "access_token": token},
                timeout=10,
            )
            page_data = r.json()
            if "error" in page_data:
                self.stdout.write(self.style.ERROR(f"  Page lookup failed: {page_data['error']['message']}"))
                ok = False
            else:
                self.stdout.write(f"  page name   : {page_data.get('name')}")
                self.stdout.write(f"  page id     : {page_data.get('id')}")
                ig_biz = page_data.get("instagram_business_account", {})
                remote_ig_id = ig_biz.get("id", "")
                self.stdout.write(f"  IG biz acct : {remote_ig_id}")
                if remote_ig_id == ig_user_id:
                    self.stdout.write(self.style.SUCCESS("  Instagram account ID matches DB record"))
                else:
                    self.stdout.write(self.style.ERROR(
                        f"  MISMATCH: DB has {ig_user_id} but Page linked to {remote_ig_id}"
                    ))
                    ok = False
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Page request failed: {exc}"))
            ok = False

        # ── 3. Page subscription ──────────────────────────────────────────────
        self.stdout.write("\n── Page subscription ────────────────────────────────────")
        try:
            r = httpx.get(
                f"https://graph.facebook.com/{graph_version}/{page_id}/subscribed_apps",
                params={"access_token": token},
                timeout=10,
            )
            sub_data = r.json()
            if "error" in sub_data:
                self.stdout.write(self.style.ERROR(
                    f"  subscribed_apps error: {sub_data['error']['message']}"
                ))
                ok = False
            else:
                apps = sub_data.get("data", [])
                if apps:
                    for app in apps:
                        self.stdout.write(
                            self.style.SUCCESS(f"  Page is subscribed to app: {app.get('name')} (id={app.get('id')})")
                        )
                else:
                    self.stdout.write(self.style.ERROR("  Page is NOT subscribed to any app"))
                    ok = False
                    if options["fix_subscription"]:
                        self._subscribe_page(token, page_id, graph_version)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  subscribed_apps request failed: {exc}"))
            ok = False

        # ── 4. Webhook reminder ───────────────────────────────────────────────
        self.stdout.write("\n── Meta app mode reminder ───────────────────────────────")
        self.stdout.write("  Your app must be in LIVE mode for webhooks from public users.")
        self.stdout.write("  In Development mode, only Admins/Developers/Testers get webhooks.")
        self.stdout.write("  Dashboard: App Settings → Basic → App Mode → switch to Live")

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write("\n── Summary ──────────────────────────────────────────────")
        if ok:
            self.stdout.write(self.style.SUCCESS("All checks passed."))
        else:
            self.stdout.write(self.style.ERROR("One or more checks failed — see above."))

    def _subscribe_page(self, token: str, page_id: str, graph_version: str) -> None:
        self.stdout.write("  Subscribing page to app...")
        try:
            r = httpx.post(
                f"https://graph.facebook.com/{graph_version}/{page_id}/subscribed_apps",
                data={
                    "subscribed_fields": "comments",
                    "access_token": token,
                },
                timeout=10,
            )
            data = r.json()
            if data.get("success"):
                self.stdout.write(self.style.SUCCESS("  Page subscribed successfully."))
            else:
                self.stdout.write(self.style.ERROR(f"  Subscription failed: {data}"))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  Subscription request failed: {exc}"))
