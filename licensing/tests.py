import json
import shutil
import unittest
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import tenancy
from .checker import LicenseState
from .models import License

User = get_user_model()


def make_license(**kw):
    defaults = dict(business_name="کافه تست", mode=License.SELF, plan="1m")
    defaults.update(kw)
    lic = License(**defaults)
    lic.save()
    lic.extend(defaults["plan"], 0)
    return lic


class LicenseModelTests(TestCase):
    def test_plans_set_expiry(self):
        for plan, days in [("1m", 30), ("3m", 91), ("6m", 183), ("1y", 365), ("2y", 730)]:
            lic = make_license(plan=plan, business_name=plan)
            self.assertAlmostEqual((lic.expires_at - timezone.now()).days, days, delta=1)
            self.assertTrue(lic.is_valid)

    def test_forever_never_expires(self):
        lic = make_license(plan="forever")
        self.assertIsNone(lic.expires_at)
        self.assertTrue(lic.is_valid)
        self.assertIsNone(lic.days_left)

    def test_renew_extends_from_current_expiry(self):
        lic = make_license(plan="1m")
        before = lic.expires_at
        lic.extend("1m", 100)
        self.assertEqual(lic.expires_at, before + timedelta(days=30))
        self.assertEqual(lic.price_paid, 100)

    def test_renew_after_expiry_starts_from_now(self):
        lic = make_license(plan="1m")
        License.objects.filter(pk=lic.pk).update(expires_at=timezone.now() - timedelta(days=10))
        lic.refresh_from_db()
        self.assertEqual(lic.state, "expired")
        lic.extend("1m")
        self.assertAlmostEqual((lic.expires_at - timezone.now()).days, 30, delta=1)
        self.assertTrue(lic.is_valid)

    def test_cancel_and_reactivate(self):
        lic = make_license()
        lic.cancel("non payment")
        self.assertEqual(lic.state, "cancelled")
        self.assertFalse(lic.is_valid)
        lic.reactivate()
        self.assertTrue(lic.is_valid)

    def test_forever_survives_finite_renewal(self):
        lic = make_license(plan="forever")
        lic.extend("1m")
        self.assertIsNone(lic.expires_at)


class VerifyApiTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(DEPLOYMENT_MODE="platform", PLATFORM_DOMAIN="example.test", ALLOWED_HOSTS=["*"])
    def test_verify_states(self):
        lic = make_license()
        url = reverse("developer:dashboard").replace("developer/", "api/license/verify/")
        post = lambda key: self.client.post(url, json.dumps({"key": key, "host": "cafe.ir"}), content_type="application/json", HTTP_HOST="example.test").json()
        self.assertTrue(post(lic.key)["valid"])
        self.assertEqual(post("CFR-NOPE")["status"], "unknown")
        lic.cancel("x")
        out = post(lic.key)
        self.assertFalse(out["valid"])
        self.assertEqual(out["status"], "cancelled")
        lic.refresh_from_db()
        self.assertEqual(lic.last_check_host, "cafe.ir")


class StandaloneEnforcementTests(TestCase):
    """A customer's own deployment asks the developer's server and locks when told to."""

    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user("boss", password="pw-12345-x", is_staff=True)
        self.client.force_login(self.staff)

    def _remote(self, **resp):
        return mock.patch("licensing.checker._remote_fetch", return_value=resp)

    @override_settings(LICENSE_ENFORCE=True, LICENSE_KEY="K", LICENSE_SERVER_URL="https://dev.example")
    def test_valid_remote_allows_panel(self):
        with self._remote(valid=True, status="active", plan="1y", business="x", expires_at=None, days_left=None):
            self.assertEqual(self.client.get(reverse("vendor:dashboard")).status_code, 200)

    @override_settings(LICENSE_ENFORCE=True, LICENSE_KEY="K", LICENSE_SERVER_URL="https://dev.example")
    def test_cancelled_remote_blocks_panel_and_orders(self):
        with self._remote(valid=False, status="cancelled"):
            r = self.client.get(reverse("vendor:dashboard"))
            self.assertEqual(r.status_code, 402)
            self.assertContains(r, "لغو شده", status_code=402)
            r = self.client.post(reverse("create_order"), "{}", content_type="application/json")
            self.assertEqual(r.status_code, 402)

    @override_settings(LICENSE_ENFORCE=True, LICENSE_KEY="K", LICENSE_SERVER_URL="https://dev.example", LICENSE_GRACE_HOURS=72)
    def test_offline_grace_then_lock(self):
        with self._remote(valid=True, status="active"):
            self.assertEqual(self.client.get(reverse("vendor:dashboard")).status_code, 200)
        cache.delete("lic:remote:fresh")
        with mock.patch("licensing.checker._remote_fetch", side_effect=OSError("down")):
            self.assertEqual(self.client.get(reverse("vendor:dashboard")).status_code, 200)  # within grace
            cache.delete("lic:remote:fresh")
            cache.set("lic:remote:lastgood", (timezone.now() - timedelta(hours=100), LicenseState(True)), None)
            self.assertEqual(self.client.get(reverse("vendor:dashboard")).status_code, 402)

    @override_settings(LICENSE_ENFORCE=True, LICENSE_KEY="", LICENSE_SERVER_URL="")
    def test_enforced_without_key_is_locked(self):
        self.assertEqual(self.client.get(reverse("vendor:dashboard")).status_code, 402)

    def test_not_enforced_by_default(self):
        self.assertEqual(self.client.get(reverse("vendor:dashboard")).status_code, 200)

    REMOTE = dict(LICENSE_ENFORCE=True, LICENSE_KEY="K", LICENSE_SERVER_URL="https://dev.example")

    @override_settings(**REMOTE)
    def test_menu_qr_and_public_pages_redirect_to_the_contact_page_when_locked(self):
        from management.models import Table, Venue
        v = Venue.load()
        v.name, v.phone = "کافه تست", "021-1234"
        v.save()
        t = Table.objects.create(number="1")
        with self._remote(valid=False, status="cancelled"):
            for url in (reverse("public_menu", args=[t.qr_slug]), reverse("order_track", args=["abc"]), "/",
                        reverse("products_list"), reverse("about")):
                r = self.client.get(url)
                self.assertEqual((r.status_code, r["Location"]), (302, "/license/unavailable/"), url)
            page = self.client.get("/license/unavailable/")
            self.assertEqual(page.status_code, 503)
            self.assertContains(page, "021-1234", status_code=503)
            self.assertContains(page, "کافه تست", status_code=503)
            self.assertNotContains(page, "cart-bar", status_code=503)
            # API callers get a clear refusal that names the redirect target
            r = self.client.post(reverse("quote"), "{}", content_type="application/json")
            self.assertEqual(r.status_code, 402)
            self.assertEqual(r.json()["redirect"], "/license/unavailable/")
            # the owner can still reach the sign-in page
            self.assertEqual(Client().get(reverse("login")).status_code, 200)

    @override_settings(**REMOTE)
    def test_menu_works_normally_when_the_license_is_valid(self):
        from management.models import Table
        t = Table.objects.create(number="1")
        with self._remote(valid=True, status="active"):
            r = self.client.get(reverse("public_menu", args=[t.qr_slug]))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, 'id="cart-bar"')

    def test_unavailable_page_bounces_home_when_nothing_is_wrong(self):
        r = self.client.get("/license/unavailable/")
        self.assertEqual((r.status_code, r["Location"]), (302, "/"))

    @override_settings(**REMOTE)
    def test_a_no_is_remembered_briefly_and_a_yes_for_longer(self):
        from . import checker

        class Spy:
            def __init__(self):
                self.calls = []

            def get(self, *a, **k):
                return cache.get(*a, **k)

            def set(self, key, value, timeout=None):
                self.calls.append((key, value, timeout))
                cache.set(key, value, timeout)

            def delete(self, *a):
                cache.delete(*a)

        spy = Spy()
        with mock.patch.object(checker, "cache", spy):
            with self._remote(valid=False, status="cancelled"):
                checker.remote_state("h")
            cache.delete("lic:remote:fresh")
            with self._remote(valid=True, status="active"):
                checker.remote_state("h")
        ttl = {value.valid: timeout for key, value, timeout in spy.calls if key == "lic:remote:fresh"}
        self.assertEqual(ttl, {False: checker.INVALID_TTL, True: checker.VALID_TTL})
        self.assertLessEqual(checker.INVALID_TTL, 20)  # a renewal must not wait minutes
        self.assertGreater(checker.VALID_TTL, checker.INVALID_TTL)

    @override_settings(**REMOTE)
    def test_check_again_button_picks_up_a_renewal_immediately(self):
        with self._remote(valid=False, status="cancelled"):
            blocked = self.client.get(reverse("vendor:dashboard"))
            self.assertEqual(blocked.status_code, 402)
            self.assertContains(blocked, reverse("license_recheck"), status_code=402)  # the button is on the page
        with self._remote(valid=True, status="active"):
            # inside the short window the "no" is still remembered ...
            self.assertEqual(self.client.get(reverse("vendor:dashboard")).status_code, 402)
            # ... until the owner presses "check again"
            r = self.client.post(reverse("license_recheck"), {"next": "/vendor/"})
            self.assertEqual((r.status_code, r["Location"]), (302, "/vendor/"))
            self.assertEqual(self.client.get(reverse("vendor:dashboard")).status_code, 200)

    def test_check_again_ignores_foreign_redirect_targets(self):
        r = self.client.post(reverse("license_recheck"), {"next": "https://evil.example/"})
        self.assertEqual(r["Location"], "/vendor/")
        self.assertEqual(self.client.get(reverse("license_recheck")).status_code, 405)


class PlatformTenancyTests(unittest.TestCase):
    """Tenant databases are created at runtime, which Django's TestCase forbids; so this class uses
    plain unittest and cleans up after itself."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="cfr-tenants-"))

    @classmethod
    def tearDownClass(cls):
        for slug in ("alpha", "beta"):
            tenancy.close_tenant_connection(slug)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self._ovs = [
            override_settings(DEPLOYMENT_MODE="platform", PLATFORM_DOMAIN="example.test", ALLOWED_HOSTS=["*"], TENANT_DB_DIR=self.tmp),
        ]
        for o in self._ovs:
            o.enable()
        self.client = Client()
        self.dev = User.objects.create_superuser("dev", "d@x.com", "dev-pass-12345")

    def tearDown(self):
        for o in self._ovs:
            o.disable()
        License.objects.all().delete()
        User.objects.all().delete()
        cache.clear()

    def assertStatus(self, resp, code, msg=""):
        self.assertEqual(resp.status_code, code, msg)

    def create(self, slug, name, plan="1m", price=490000):
        self.client.force_login(self.dev)
        r = self.client.post(reverse("developer:create"), {
            "business_name": name, "contact_name": "", "phone": "", "email": "o@x.com", "mode": "hosted",
            "slug": slug, "domain": "", "plan": plan, "price_paid": price, "notes": ""}, HTTP_HOST="example.test")
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["form"].errors)
        return License.objects.get(slug=slug), self.client.session["flash_creds"]

    def host(self, slug):
        return f"{slug}.example.test"

    def test_provisioning_creates_isolated_tenant_with_owner_login(self):
        lic, creds = self.create("alpha", "کافه آلفا")
        self.assertTrue(tenancy.tenant_db_exists("alpha"))
        self.assertEqual(creds["username"], "owner")
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": "owner", "password": creds["password"]}, HTTP_HOST=self.host("alpha"))
        self.assertEqual((r.status_code, r["Location"]), (302, reverse("vendor:dashboard")))
        self.assertEqual(self.client.get(reverse("vendor:dashboard"), HTTP_HOST=self.host("alpha")).status_code, 200)

    def test_data_is_isolated_between_tenants_and_platform(self):
        _, ca = self.create("alpha", "کافه آلفا")
        self.client.force_login(self.dev)
        _, cb = self.create("beta", "کافه بتا")
        from management.models import Item, Venue
        with tenancy.use_tenant("alpha"):
            Item.objects.create(name="فقط-آلفا", drink_type="cakes", price_cents=1)
        with tenancy.use_tenant("beta"):
            self.assertEqual(Item.objects.count(), 0)
        self.assertEqual(Item.objects.count(), 0)  # platform database untouched
        self.client.logout()
        # the owner of alpha cannot sign in on beta
        r = self.client.post(reverse("login"), {"username": "owner", "password": ca["password"]}, HTTP_HOST=self.host("beta"))
        self.assertEqual(r.status_code, 200)
        # venue branding is per tenant (cache keys must not collide)
        self.assertEqual(self.client.get("/", HTTP_HOST=self.host("alpha")).context["venue"].name, "کافه آلفا")
        self.assertEqual(self.client.get("/", HTTP_HOST=self.host("beta")).context["venue"].name, "کافه بتا")

    def test_cancel_locks_whole_panel_then_reactivate_unlocks(self):
        lic, creds = self.create("alpha", "کافه آلفا")
        self.client.logout()
        self.client.post(reverse("login"), {"username": "owner", "password": creds["password"]}, HTTP_HOST=self.host("alpha"))
        self.assertEqual(self.client.get(reverse("vendor:orders"), HTTP_HOST=self.host("alpha")).status_code, 200)

        owner_client = self.client
        dev_client = Client()
        dev_client.force_login(self.dev)
        dev_client.post(reverse("developer:cancel", args=[lic.pk]), {"reason": "تست"}, HTTP_HOST="example.test")

        for path in (reverse("vendor:dashboard"), reverse("vendor:items"), reverse("vendor:board")):
            r = owner_client.get(path, HTTP_HOST=self.host("alpha"))
            self.assertEqual(r.status_code, 402, path)
        r = owner_client.post(reverse("create_order"), "{}", content_type="application/json", HTTP_HOST=self.host("alpha"))
        self.assertEqual(r.status_code, 402)
        # customers get the "contact the coffee shop" page instead of the site, menu and QR codes
        for url in ("/", "/management/t/anything/", "/users/products/"):
            r = Client().get(url, HTTP_HOST=self.host("alpha"))
            self.assertEqual((r.status_code, r["Location"]), (302, "/license/unavailable/"), url)
        self.assertEqual(Client().get("/license/unavailable/", HTTP_HOST=self.host("alpha")).status_code, 503)

        dev_client.post(reverse("developer:reactivate", args=[lic.pk]), HTTP_HOST="example.test")
        self.assertEqual(owner_client.get(reverse("vendor:dashboard"), HTTP_HOST=self.host("alpha")).status_code, 200)

    def test_expired_license_locks_panel(self):
        lic, creds = self.create("alpha", "کافه آلفا")
        self.client.logout()
        self.client.post(reverse("login"), {"username": "owner", "password": creds["password"]}, HTTP_HOST=self.host("alpha"))
        License.objects.filter(pk=lic.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        cache.clear()
        self.assertEqual(self.client.get(reverse("vendor:dashboard"), HTTP_HOST=self.host("alpha")).status_code, 402)

    def test_developer_panel_access_rules(self):
        lic, _ = self.create("alpha", "کافه آلفا")
        self.client.logout()
        # anonymous -> login redirect; owner (staff, not superuser) -> refused; tenant host -> 404
        r = self.client.get(reverse("developer:dashboard"), HTTP_HOST="example.test")
        self.assertEqual(r.status_code, 302)
        staff = User.objects.create_user("st", password="pw-12345-x", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("developer:list"), HTTP_HOST="example.test").status_code, 302)
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(reverse("developer:list"), HTTP_HOST="example.test").status_code, 200)
        self.assertEqual(self.client.get(reverse("developer:dashboard"), HTTP_HOST=self.host("alpha")).status_code, 404)
        self.assertEqual(self.client.get(reverse("developer:detail", args=[lic.pk]), HTTP_HOST="example.test").status_code, 200)

    def test_unknown_subdomain_and_reserved_names(self):
        self.assertEqual(self.client.get("/", HTTP_HOST="ghost.example.test").status_code, 404)
        self.assertEqual(self.client.get("/", HTTP_HOST="www.example.test").status_code, 200)
        self.assertEqual(self.client.get("/", HTTP_HOST="example.test").status_code, 200)
        self.client.force_login(self.dev)
        r = self.client.post(reverse("developer:create"), {
            "business_name": "x", "mode": "hosted", "slug": "admin", "plan": "1m", "price_paid": 0}, HTTP_HOST="example.test")
        self.assertEqual(r.status_code, 200)  # reserved slug rejected, form re-rendered
        self.assertFalse(License.objects.filter(slug="admin").exists())

    def test_self_hosted_customer_gets_key_not_tenant(self):
        self.client.force_login(self.dev)
        r = self.client.post(reverse("developer:create"), {
            "business_name": "نصب مستقل", "mode": "self", "slug": "", "domain": "menu.cafe.ir", "plan": "forever", "price_paid": 1}, HTTP_HOST="example.test")
        self.assertEqual(r.status_code, 302)
        lic = License.objects.get(business_name="نصب مستقل")
        self.assertIsNone(lic.slug)
        self.assertIsNone(lic.expires_at)
        r = self.client.get(reverse("developer:detail", args=[lic.pk]), HTTP_HOST="example.test")
        body = r.content.decode()
        self.assertIn(lic.key, body)
        self.assertIn("LICENSE_SERVER_URL", body)

    def test_dashboard_revenue(self):
        self.create("alpha", "کافه آلفا", price=1000000)
        r = self.client.get(reverse("developer:dashboard"), HTTP_HOST="example.test")
        self.assertEqual(r.context["stats"]["revenue_month"], 1000000)
        self.assertEqual(r.context["stats"]["active"], 1)

    # ------------------------------------------------------------------ passwords
    def test_developer_chooses_vendor_username_and_password(self):
        self.client.force_login(self.dev)
        r = self.client.post(reverse("developer:create"), {
            "business_name": "کافه رمزدار", "mode": "hosted", "slug": "alpha", "plan": "1m", "price_paid": 0,
            "owner_username": "mina", "owner_password": "Chosen-Pass-77"}, HTTP_HOST="example.test")
        self.assertEqual(r.status_code, 302)
        c = Client()
        r = c.post(reverse("login"), {"username": "mina", "password": "Chosen-Pass-77"}, HTTP_HOST=self.host("alpha"))
        self.assertEqual((r.status_code, r["Location"]), (302, reverse("vendor:dashboard")))

    def test_developer_can_change_vendor_password_later(self):
        lic, creds = self.create("alpha", "کافه آلفا")
        r = self.client.post(reverse("developer:set_password", args=[lic.pk]), {"password": "Brand-New-Pass-9"}, HTTP_HOST="example.test")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.session["flash_creds"]["password"], "Brand-New-Pass-9")
        old = Client().post(reverse("login"), {"username": "owner", "password": creds["password"]}, HTTP_HOST=self.host("alpha"))
        self.assertEqual(old.status_code, 200)  # old password no longer works
        new = Client().post(reverse("login"), {"username": "owner", "password": "Brand-New-Pass-9"}, HTTP_HOST=self.host("alpha"))
        self.assertEqual(new.status_code, 302)

    def test_short_password_rejected(self):
        lic, creds = self.create("alpha", "کافه آلفا")
        self.client.post(reverse("developer:set_password", args=[lic.pk]), {"password": "short"}, HTTP_HOST="example.test")
        ok = Client().post(reverse("login"), {"username": "owner", "password": creds["password"]}, HTTP_HOST=self.host("alpha"))
        self.assertEqual(ok.status_code, 302)  # unchanged

    # ------------------------------------------------------------------ trash / purge
    def test_trash_restore_and_purge(self):
        lic, creds = self.create("alpha", "کافه آلفا")
        db_file = tenancy.db_path("alpha")
        self.assertTrue(db_file.exists())

        self.client.post(reverse("developer:trash", args=[lic.pk]), HTTP_HOST="example.test")
        lic.refresh_from_db()
        self.assertTrue(lic.in_trash)
        self.assertEqual(Client().get("/", HTTP_HOST=self.host("alpha")).status_code, 404)  # site gone while trashed
        self.assertNotIn(lic, list(self.client.get(reverse("developer:list"), HTTP_HOST="example.test").context["page"]))
        self.assertIn(lic, list(self.client.get(reverse("developer:list") + "?trash=1", HTTP_HOST="example.test").context["page"]))

        # purge is refused until the business name is typed exactly
        self.client.post(reverse("developer:purge", args=[lic.pk]), {"confirm": "wrong"}, HTTP_HOST="example.test")
        self.assertTrue(License.objects.filter(pk=lic.pk).exists())
        self.assertTrue(db_file.exists())

        self.client.post(reverse("developer:restore", args=[lic.pk]), HTTP_HOST="example.test")
        cache.clear()
        self.assertEqual(Client().get("/", HTTP_HOST=self.host("alpha")).status_code, 200)

        # purge only works from the trash
        self.client.post(reverse("developer:purge", args=[lic.pk]), {"confirm": lic.business_name}, HTTP_HOST="example.test")
        self.assertTrue(License.objects.filter(pk=lic.pk).exists())

        self.client.post(reverse("developer:trash", args=[lic.pk]), HTTP_HOST="example.test")
        self.client.post(reverse("developer:purge", args=[lic.pk]), {"confirm": lic.business_name}, HTTP_HOST="example.test")
        self.assertFalse(License.objects.filter(pk=lic.pk).exists())
        self.assertFalse(db_file.exists())

    def test_trashed_customer_cannot_be_edited_or_renewed(self):
        lic, _ = self.create("alpha", "کافه آلفا")
        self.client.post(reverse("developer:trash", args=[lic.pk]), HTTP_HOST="example.test")
        r = self.client.post(reverse("developer:renew", args=[lic.pk]), {"plan": "1y", "price": 5}, HTTP_HOST="example.test")
        self.assertEqual(r.status_code, 404)

    def test_self_hosted_trashed_license_stops_verifying(self):
        self.client.force_login(self.dev)
        lic = make_license()
        url = "/api/license/verify/"
        ok = self.client.post(url, json.dumps({"key": lic.key}), content_type="application/json", HTTP_HOST="example.test").json()
        self.assertTrue(ok["valid"])
        self.client.post(reverse("developer:trash", args=[lic.pk]), HTTP_HOST="example.test")
        gone = self.client.post(url, json.dumps({"key": lic.key}), content_type="application/json", HTTP_HOST="example.test").json()
        self.assertFalse(gone["valid"])
        self.assertEqual(gone["status"], "deleted")

    # ------------------------------------------------------------------ prices
    def test_developer_edits_prices_and_they_apply_everywhere(self):
        self.client.force_login(self.dev)
        form = {"1m": 111000, "3m": 222000, "6m": 333000, "1y": 444000, "2y": 555000, "forever": 999000}
        r = self.client.post(reverse("developer:prices"), form, HTTP_HOST="example.test")
        self.assertEqual(r.status_code, 302)
        landing = self.client.get("/", HTTP_HOST="example.test")
        prices = {p["code"]: p["price"] for p in landing.context["plans"]}
        self.assertEqual(prices["1y"], 444000)
        self.assertEqual(prices["forever"], 999000)
        create = self.client.get(reverse("developer:create"), HTTP_HOST="example.test")
        self.assertEqual(create.context["form"].initial["price_paid"], 111000)

    def test_invalid_prices_rejected(self):
        self.client.force_login(self.dev)
        r = self.client.post(reverse("developer:prices"), {"1m": -5, "3m": "x"}, HTTP_HOST="example.test")
        self.assertEqual(r.status_code, 200)

    # ------------------------------------------------------------------ backups
    def test_backup_contains_every_database_and_photos(self):
        import sqlite3
        import tarfile
        import time
        from . import backup
        self.create("alpha", "کافه آلفا")
        self.create("beta", "کافه بتا")
        out = self.tmp / "bk"
        media = self.tmp / "media"
        (media / "alpha" / "images").mkdir(parents=True)
        (media / "alpha" / "images" / "a.png").write_bytes(b"png")
        with override_settings(BACKUP_DIR=str(out), MEDIA_ROOT=str(media), BACKUP_KEEP=2):
            path, count = backup.create_backup()
            self.assertGreaterEqual(count, 2)  # both customers (the in-memory test main DB has no file to copy)
            extract = self.tmp / "extract"
            with tarfile.open(path) as tar:
                names = tar.getnames()
                self.assertIn("data/tenants/alpha.sqlite3", names)
                self.assertIn("data/tenants/beta.sqlite3", names)
                self.assertIn("media/alpha/images/a.png", names)
                tar.extractall(extract, filter="data")
            con = sqlite3.connect(str(extract / "data" / "tenants" / "alpha.sqlite3"))
            try:
                self.assertEqual(con.execute("select name from management_venue").fetchone()[0], "کافه آلفا")
                self.assertEqual(con.execute("pragma integrity_check").fetchone()[0], "ok")
            finally:
                con.close()
            for _ in range(3):  # retention keeps only BACKUP_KEEP archives
                time.sleep(1.1)
                backup.create_backup()
            self.assertEqual(len(backup.list_backups()), 2)
        for d in (out, media, self.tmp / "extract"):
            shutil.rmtree(d, ignore_errors=True)

    def test_backup_pages_download_and_traversal_guard(self):
        out = self.tmp / "bk2"
        with override_settings(BACKUP_DIR=str(out)):
            self.client.force_login(self.dev)
            r = self.client.post(reverse("developer:backup_now"), HTTP_HOST="example.test")
            self.assertEqual(r.status_code, 302)
            page = self.client.get(reverse("developer:backups"), HTTP_HOST="example.test")
            self.assertEqual(len(page.context["items"]), 1)
            name = page.context["items"][0]["name"]
            dl = self.client.get(reverse("developer:backup_download", args=[name]), HTTP_HOST="example.test")
            self.assertEqual(dl.status_code, 200)
            dl.close()
            self.assertEqual(self.client.get("/developer/backups/..%2Fsecret/", HTTP_HOST="example.test").status_code, 404)
            self.assertEqual(self.client.get(reverse("developer:backup_download", args=["evil.txt"]), HTTP_HOST="example.test").status_code, 404)
            staff = User.objects.create_user("st2", password="pw-12345-x", is_staff=True)
            c = Client()
            c.force_login(staff)
            self.assertEqual(c.get(reverse("developer:backups"), HTTP_HOST="example.test").status_code, 302)
        shutil.rmtree(out, ignore_errors=True)

    # ------------------------------------------------------------------ login flow
    def test_developer_lands_on_developer_panel_after_login(self):
        r = Client().post(reverse("login"), {"username": "dev", "password": "dev-pass-12345"}, HTTP_HOST="example.test")
        self.assertEqual((r.status_code, r["Location"]), (302, reverse("developer:dashboard")))

    def test_vendor_sidebar_links_to_developer_panel_for_superuser(self):
        self.client.force_login(self.dev)
        html = self.client.get(reverse("vendor:dashboard"), HTTP_HOST="example.test").content.decode()
        self.assertIn(reverse("developer:dashboard"), html)


    # ------------------------------------------------------------------ customer's own domain
    def attach_domain(self, lic, domain):
        r = self.client.post(reverse("developer:set_domain", args=[lic.pk]), {"domain": domain}, HTTP_HOST="example.test")
        self.assertEqual(r.status_code, 302)
        lic.refresh_from_db()
        cache.clear()

    def test_customer_site_answers_on_their_own_domain_and_on_the_subdomain(self):
        lic, creds = self.create("alpha", "کافه آلفا")
        self.attach_domain(lic, "menu.alpha-cafe.ir")
        self.assertEqual(lic.domain, "menu.alpha-cafe.ir")
        own = Client().get("/", HTTP_HOST="menu.alpha-cafe.ir")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.context["venue"].name, "کافه آلفا")  # their data, not the platform's
        self.assertEqual(Client().get("/", HTTP_HOST=self.host("alpha")).status_code, 200)
        # sign in and use the panel through the custom domain
        c = Client()
        r = c.post(reverse("login"), {"username": "owner", "password": creds["password"]}, HTTP_HOST="menu.alpha-cafe.ir")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(c.get(reverse("vendor:dashboard"), HTTP_HOST="menu.alpha-cafe.ir").status_code, 200)

    def test_domain_is_case_insensitive_and_accepts_pasted_urls(self):
        lic, _ = self.create("alpha", "کافه آلفا")
        self.attach_domain(lic, "HTTPS://Menu.Alpha-Cafe.IR/some/path")
        self.assertEqual(lic.domain, "menu.alpha-cafe.ir")
        self.assertEqual(Client().get("/", HTTP_HOST="MENU.alpha-cafe.ir").status_code, 200)

    def test_unregistered_hosts_are_refused(self):
        self.assertEqual(Client().get("/", HTTP_HOST="random-site.com").status_code, 404)
        self.assertEqual(Client().get("/developer/", HTTP_HOST="random-site.com").status_code, 404)
        self.assertEqual(Client().get("/healthz", HTTP_HOST="127.0.0.1").status_code, 200)  # health checks still work

    def test_cancelling_locks_the_custom_domain_too_and_removing_it_stops_routing(self):
        lic, creds = self.create("alpha", "کافه آلفا")
        self.attach_domain(lic, "menu.alpha-cafe.ir")
        c = Client()
        c.post(reverse("login"), {"username": "owner", "password": creds["password"]}, HTTP_HOST="menu.alpha-cafe.ir")
        self.client.post(reverse("developer:cancel", args=[lic.pk]), {"reason": "t"}, HTTP_HOST="example.test")
        self.assertEqual(c.get(reverse("vendor:dashboard"), HTTP_HOST="menu.alpha-cafe.ir").status_code, 402)
        self.client.post(reverse("developer:reactivate", args=[lic.pk]), HTTP_HOST="example.test")
        self.attach_domain(lic, "")
        self.assertEqual(Client().get("/", HTTP_HOST="menu.alpha-cafe.ir").status_code, 404)
        self.assertEqual(Client().get("/", HTTP_HOST=self.host("alpha")).status_code, 200)

    def test_trashed_customers_domain_stops_working(self):
        lic, _ = self.create("alpha", "کافه آلفا")
        self.attach_domain(lic, "menu.alpha-cafe.ir")
        self.client.post(reverse("developer:trash", args=[lic.pk]), HTTP_HOST="example.test")
        cache.clear()
        self.assertEqual(Client().get("/", HTTP_HOST="menu.alpha-cafe.ir").status_code, 404)

    def test_invalid_duplicate_and_platform_domains_are_rejected(self):
        a, _ = self.create("alpha", "کافه آلفا")
        b, _ = self.create("beta", "کافه بتا")
        self.attach_domain(a, "menu.alpha-cafe.ir")
        for bad in ("not a domain", "nodots", "x.example.test", "example.test", "-bad-.com", "menu.alpha-cafe.ir"):
            self.client.post(reverse("developer:set_domain", args=[b.pk]), {"domain": bad}, HTTP_HOST="example.test")
            b.refresh_from_db()
            self.assertEqual(b.domain, "", bad)

    def test_creating_a_customer_with_a_custom_domain_and_detail_instructions(self):
        self.client.force_login(self.dev)
        r = self.client.post(reverse("developer:create"), {
            "business_name": "کافه دامنه‌دار", "mode": "hosted", "slug": "alpha", "domain": "Menu.Dar.ir",
            "plan": "1m", "price_paid": 0}, HTTP_HOST="example.test")
        self.assertEqual(r.status_code, 302)
        lic = License.objects.get(slug="alpha")
        self.assertEqual(lic.domain, "menu.dar.ir")
        # credentials shown to the developer use the sub-domain, which has a certificate from day one
        self.assertEqual(self.client.session["flash_creds"]["url"], "https://alpha.example.test")
        page = self.client.get(reverse("developer:detail", args=[lic.pk]), HTTP_HOST="example.test").content.decode()
        self.assertIn("make add-domain DOMAIN=menu.dar.ir", page)



    # ------------------------------------------------------------------ old domain keeps working after a domain change
    def test_old_platform_domain_alias_serves_sales_page_tenants_and_license_api(self):
        lic, creds = self.create("alpha", "کافه آلفا")
        with override_settings(PLATFORM_DOMAIN="newname.test", PLATFORM_ALIAS_DOMAINS=["example.test"]):
            cache.clear()
            # customers' addresses work on the NEW domain and, through the alias, on the OLD one
            for host in ("alpha.newname.test", "alpha.example.test"):
                r = Client().get("/", HTTP_HOST=host)
                self.assertEqual(r.status_code, 200, host)
                self.assertEqual(r.context["venue"].name, "کافه آلفا", host)
            # the root of either domain is the platform (sales page / developer panel)
            self.assertEqual(Client().get("/", HTTP_HOST="newname.test").status_code, 200)
            self.assertEqual(Client().get("/", HTTP_HOST="example.test").status_code, 200)
            # self-hosted installs keep verifying against the old address
            self_lic = make_license()
            r = Client().post("/api/license/verify/", json.dumps({"key": self_lic.key}),
                              content_type="application/json", HTTP_HOST="example.test")
            self.assertTrue(r.json()["valid"])
            # the owner can still sign in on either address
            for host in ("alpha.newname.test", "alpha.example.test"):
                c = Client()
                r = c.post(reverse("login"), {"username": "owner", "password": creds["password"]}, HTTP_HOST=host)
                self.assertEqual(r.status_code, 302, host)
        # without the alias the old sub-domain is gone
        with override_settings(PLATFORM_DOMAIN="newname.test", PLATFORM_ALIAS_DOMAINS=[]):
            cache.clear()
            self.assertEqual(Client().get("/", HTTP_HOST="alpha.example.test").status_code, 404)

    def test_domain_errors_say_why(self):
        a, _ = self.create("alpha", "کافه آلفا")
        b, _ = self.create("beta", "کافه بتا")
        self.attach_domain(a, "menu.alpha-cafe.ir")

        def error_for(lic, domain):
            from .forms import DomainForm
            f = DomainForm({"domain": domain}, instance=lic)
            self.assertFalse(f.is_valid(), domain)
            return " ".join(f.errors["domain"])

        # held by another customer: the message names them
        self.assertIn("کافه آلفا", error_for(b, "menu.alpha-cafe.ir"))
        # held by a customer in the trash: says so
        self.client.post(reverse("developer:trash", args=[a.pk]), HTTP_HOST="example.test")
        msg = error_for(b, "menu.alpha-cafe.ir")
        self.assertIn("کافه آلفا", msg)
        self.assertIn("سطل زباله", msg)
        # a leftover platform alias is explained, with the command that fixes it
        with override_settings(PLATFORM_ALIAS_DOMAINS=["old-platform.ir"]):
            msg = error_for(b, "old-platform.ir")
            self.assertIn("PLATFORM_ALIAS_DOMAINS", msg)
            self.assertIn("DROP_OLD=1", msg)
            self.assertIn("PLATFORM_ALIAS_DOMAINS", error_for(b, "shop.old-platform.ir"))


# ---------------------------------------------------------------------------
# Off-server backup copies
# ---------------------------------------------------------------------------
class OffServerBackupTests(TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp(prefix="cfr-bk-"))
        self._ov = override_settings(BACKUP_DIR=str(self.out), BACKUP_REMOTE="backup@vault.example.com:/srv/cofferant",
                                     BACKUP_REMOTE_PORT=2222, BACKUP_REMOTE_KEEP=3, BACKUP_SSH_KEY="/tmp/key")
        self._ov.enable()

    def tearDown(self):
        self._ov.disable()
        shutil.rmtree(self.out, ignore_errors=True)

    def test_every_backup_is_copied_with_scp_and_old_copies_are_pruned_remotely(self):
        from . import backup
        with mock.patch("licensing.backup.subprocess.run") as run:
            path, _ = backup.create_backup()
        calls = [c.args[0] for c in run.call_args_list]
        self.assertEqual([c[0] for c in calls], ["ssh", "scp", "ssh"])
        self.assertIn("backup@vault.example.com", calls[0])
        self.assertIn("mkdir -p /srv/cofferant", calls[0][-1])
        self.assertEqual(calls[1][-2:], [str(path), "backup@vault.example.com:/srv/cofferant/"])
        self.assertIn("2222", calls[1])
        self.assertIn("-P", calls[1])
        self.assertIn("tail -n +4", calls[2][-1])  # keep = 3 -> delete from the 4th newest on
        status = backup.read_remote_status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["file"], path.name)

    def test_remote_failure_never_loses_the_local_backup(self):
        import subprocess
        from . import backup
        err = subprocess.CalledProcessError(255, "ssh", stderr="Permission denied (publickey).")
        with mock.patch("licensing.backup.subprocess.run", side_effect=err):
            path, count = backup.create_backup()
        self.assertTrue(path.exists())
        status = backup.read_remote_status()
        self.assertFalse(status["ok"])
        self.assertIn("Permission denied", status["detail"])

    def test_timeout_and_missing_ssh_are_reported_not_raised(self):
        import subprocess
        from . import backup
        for exc in (subprocess.TimeoutExpired("scp", 1), FileNotFoundError("ssh")):
            with mock.patch("licensing.backup.subprocess.run", side_effect=exc):
                self.assertFalse(backup.push_remote(test=True)["ok"])

    def test_bad_remote_setting_is_rejected_without_running_anything(self):
        from . import backup
        for bad in ("no-colon", "user@host", "user@host:relative/path", "user@host:/p; rm -rf /", "x y@h:/p"):
            with override_settings(BACKUP_REMOTE=bad), mock.patch("licensing.backup.subprocess.run") as run:
                status = backup.push_remote(test=True)
                run.assert_not_called()
                self.assertFalse(status["ok"], bad)

    def test_nothing_happens_when_not_configured(self):
        from . import backup
        with override_settings(BACKUP_REMOTE=""), mock.patch("licensing.backup.subprocess.run") as run:
            self.assertIsNone(backup.push_remote(test=True))
            run.assert_not_called()

    def test_command_and_developer_page_show_the_state(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with mock.patch("licensing.backup.subprocess.run"):
            call_command("backup_remote", "--test")
        with override_settings(BACKUP_REMOTE=""):
            with self.assertRaises(CommandError):
                call_command("backup_remote", "--test")
        with override_settings(DEPLOYMENT_MODE="platform", PLATFORM_DOMAIN="example.test", ALLOWED_HOSTS=["*"]):
            dev = User.objects.create_superuser("dev", "d@x.com", "dev-pass-12345")
            self.client.force_login(dev)
            html = self.client.get(reverse("developer:backups"), HTTP_HOST="example.test").content.decode()
        self.assertIn("backup@vault.example.com:/srv/cofferant", html)
        self.assertIn("connection works", html)


