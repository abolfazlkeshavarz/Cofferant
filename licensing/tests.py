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

    @override_settings(LICENSE_ENFORCE=True, LICENSE_KEY="K", LICENSE_SERVER_URL="https://dev.example")
    def test_menu_stays_viewable_but_ordering_disabled(self):
        from management.models import Table
        t = Table.objects.create(number="1")
        with self._remote(valid=False, status="expired"):
            r = self.client.get(reverse("public_menu", args=[t.qr_slug]))
            self.assertEqual(r.status_code, 200)
            self.assertNotContains(r, 'id="cart-bar"')


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
        self.assertEqual(owner_client.get("/", HTTP_HOST=self.host("alpha")).status_code, 200)  # public site still up

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
