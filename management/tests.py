import json
from datetime import timedelta

from django.utils import timezone

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import Item, Order, ServiceRequest, Table, Venue


class OrderApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.table = Table.objects.create(number="1")
        self.latte = Item.objects.create(name="لاته", drink_type="hot coffee", price_cents=100000, customizable=True)
        self.cake = Item.objects.create(name="کیک", drink_type="cakes", price_cents=50000)
        self.off = Item.objects.create(name="ناموجود", drink_type="cakes", price_cents=1, is_available=False)
        self.url = reverse("create_order")

    def post(self, payload, **kw):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json", **kw)

    def payload(self, items, **extra):
        return {"table_qr": self.table.qr_slug, "items": items, **extra}

    def test_menu_renders(self):
        r = self.client.get(reverse("public_menu", args=[self.table.qr_slug]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "لاته")

    def test_creates_order_with_server_side_prices(self):
        r = self.post(self.payload([{"product_id": self.latte.id, "quantity": 2, "custom": "70/30", "price": 1}]))
        self.assertEqual(r.status_code, 200, r.content)
        o = Order.objects.get()
        self.assertEqual(o.total_cents, 200000)
        item = o.items.get()
        self.assertEqual(item.unit_price_cents, 100000)
        self.assertEqual(item.product_name, "لاته")
        self.assertEqual(item.note, "70/30")
        self.assertTrue(r.json()["token"])

    def test_note_dropped_for_non_customizable(self):
        self.post(self.payload([{"product_id": self.cake.id, "quantity": 1, "custom": "x"}]))
        self.assertEqual(Order.objects.get().items.get().note, "")

    def test_bad_quantity_is_400_not_500(self):
        for q in ["abc", 0, -1, 999, None]:
            r = self.post(self.payload([{"product_id": self.cake.id, "quantity": q}]))
            self.assertEqual(r.status_code, 400, q)
        self.assertEqual(Order.objects.count(), 0)

    def test_unavailable_only_rejected_and_rolled_back(self):
        r = self.post(self.payload([{"product_id": self.off.id, "quantity": 1}]))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_unavailable_items_skipped_but_reported(self):
        r = self.post(self.payload([{"product_id": self.off.id, "quantity": 1}, {"product_id": self.cake.id, "quantity": 1}]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["skipped"], ["ناموجود"])
        self.assertEqual(Order.objects.get().items.count(), 1)

    def test_invalid_table_and_json(self):
        r = self.post({"table_qr": "nope", "items": [{"product_id": self.cake.id}]})
        self.assertEqual(r.status_code, 404)
        r = self.client.post(self.url, "{{", content_type="application/json")
        self.assertEqual(r.status_code, 400)
        r = self.client.post(self.url, "[]", content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_empty_cart(self):
        self.assertEqual(self.post(self.payload([])).status_code, 400)

    def test_closed_venue_rejects_orders(self):
        v = Venue.load()
        v.accepting_orders = False
        v.save()
        r = self.post(self.payload([{"product_id": self.cake.id, "quantity": 1}]))
        self.assertEqual(r.status_code, 400)

    def test_rate_limit(self):
        with self.settings(ORDER_RATE_LIMIT=2):
            codes = [self.post(self.payload([{"product_id": self.cake.id, "quantity": 1}])).status_code for _ in range(4)]
        self.assertEqual(codes, [200, 200, 429, 429])

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


class TrackingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.table = Table.objects.create(number="2")
        item = Item.objects.create(name="چای", drink_type="hot drink", price_cents=30000)
        r = self.client.post(reverse("create_order"), json.dumps({
            "table_qr": self.table.qr_slug, "items": [{"product_id": item.id, "quantity": 1}]}),
            content_type="application/json")
        self.token = r.json()["token"]
        self.order = Order.objects.get()

    def test_track_page_and_status_api(self):
        self.assertEqual(self.client.get(reverse("order_track", args=[self.token])).status_code, 200)
        data = self.client.get(reverse("order_status", args=[self.token])).json()
        self.assertEqual(data["status"], "new")
        self.assertEqual(self.client.get(reverse("order_status", args=["bad"])).status_code, 404)

    def test_rating_only_after_delivery(self):
        url = reverse("order_rate", args=[self.token])
        post = lambda d: self.client.post(url, json.dumps(d), content_type="application/json")
        self.assertEqual(post({"rating": 5}).status_code, 400)
        self.order.set_status("delivered")
        self.assertEqual(post({"rating": 9}).status_code, 400)
        self.assertEqual(post({"rating": "x"}).status_code, 400)
        self.assertEqual(post({"rating": 4, "feedback": "عالی"}).status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.rating, 4)


class ServiceRequestTests(TestCase):
    def setUp(self):
        cache.clear()
        self.table = Table.objects.create(number="3")

    def test_dedupes_open_requests(self):
        url = reverse("create_request")
        body = json.dumps({"table_qr": self.table.qr_slug, "kind": "waiter"})
        a = self.client.post(url, body, content_type="application/json").json()
        b = self.client.post(url, body, content_type="application/json").json()
        self.assertTrue(a["new"])
        self.assertFalse(b["new"])
        self.assertEqual(ServiceRequest.objects.count(), 1)

    def test_rejects_unknown_kind(self):
        r = self.client.post(reverse("create_request"), json.dumps({"table_qr": self.table.qr_slug, "kind": "x"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)


class OrderModelTests(TestCase):
    def test_status_flow(self):
        o = Order.objects.create()
        self.assertEqual(o.next_status, "preparing")
        self.assertTrue(o.set_status("preparing"))
        self.assertFalse(o.set_status("preparing"))
        self.assertFalse(o.set_status("bogus"))
        o.set_status("delivered")
        self.assertFalse(o.set_status("new"))  # finished orders can't go back
        self.assertTrue(o.set_status("cancelled"))


class CsrfFlowTests(TestCase):
    """Real browsers enforce CSRF; the Django test client doesn't unless asked."""

    def test_menu_sets_cookie_and_order_post_succeeds_with_token(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        table = Table.objects.create(number="9")
        item = Item.objects.create(name="چای", drink_type="hot drink", price_cents=1000)
        c.get(reverse("public_menu", args=[table.qr_slug]))
        token = c.cookies["csrftoken"].value
        body = json.dumps({"table_qr": table.qr_slug, "items": [{"product_id": item.id, "quantity": 1}]})
        bad = c.post(reverse("create_order"), body, content_type="application/json")
        self.assertEqual(bad.status_code, 403)
        ok = c.post(reverse("create_order"), body, content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(ok.status_code, 200)


# ---------------------------------------------------------------------------
# Money: tax / service / tip / coupons / online payment / brand colours
# ---------------------------------------------------------------------------
from unittest import mock  # noqa: E402

from django.contrib.auth import get_user_model  # noqa: E402

from . import payments  # noqa: E402
from .models import Coupon  # noqa: E402


class MoneyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.table = Table.objects.create(number="1")
        self.item = Item.objects.create(name="لاته", drink_type="hot coffee", price_cents=100000)
        self.venue = Venue.load()

    def order(self, **extra):
        body = {"table_qr": self.table.qr_slug, "items": [{"product_id": self.item.id, "quantity": 2}], **extra}
        return self.client.post(reverse("create_order"), json.dumps(body), content_type="application/json")

    def test_tax_service_tip_and_coupon_math(self):
        self.venue.service_percent, self.venue.tax_percent = 10, 9
        self.venue.save()
        Coupon.objects.create(code="off10", percent=10)  # saved upper-case
        r = self.order(coupon="OFF10", tip=10)
        self.assertEqual(r.status_code, 200, r.content)
        o = Order.objects.get()
        self.assertEqual(o.subtotal_cents, 200000)
        self.assertEqual(o.discount_cents, 20000)       # 10% of 200,000
        self.assertEqual(o.service_cents, 18000)        # 10% of 180,000
        self.assertEqual(o.tax_cents, 17820)            # 9% of 198,000
        self.assertEqual(o.tip_cents, 18000)            # 10% of 180,000
        self.assertEqual(o.total_cents, 180000 + 18000 + 17820 + 18000)
        self.assertEqual(Coupon.objects.get().used_count, 1)

    def test_client_cannot_inject_amounts(self):
        r = self.order(total=1, tip=7)  # 7% isn't an allowed tip
        self.assertEqual(r.status_code, 400)
        r = self.order(total=1, subtotal=1, discount=999999)
        self.assertEqual(Order.objects.get().total_cents, 200000)

    def test_tips_can_be_disabled(self):
        self.venue.tips_enabled = False
        self.venue.save()
        self.order(tip=15)
        self.assertEqual(Order.objects.get().tip_cents, 0)

    def test_coupon_rules(self):
        Coupon.objects.create(code="ONCE", amount=5000, max_uses=1)
        Coupon.objects.create(code="BIG", percent=50, min_order=500000)
        Coupon.objects.create(code="OFF", percent=50, is_active=False)
        Coupon.objects.create(code="OLD", percent=50, expires_at=timezone.now() - timedelta(days=1))
        self.assertEqual(self.order(coupon="ONCE").status_code, 200)
        self.assertEqual(self.order(coupon="ONCE").status_code, 400)       # used up
        for code in ("BIG", "OFF", "OLD", "NOPE"):
            self.assertEqual(self.order(coupon=code).status_code, 400, code)
        self.assertEqual(Order.objects.count(), 1)

    def test_fixed_coupon_never_exceeds_subtotal(self):
        Coupon.objects.create(code="HUGE", amount=10**7)
        self.order(coupon="HUGE")
        o = Order.objects.get()
        self.assertEqual((o.discount_cents, o.total_cents), (200000, 0))

    def test_quote_endpoint_matches_order(self):
        self.venue.tax_percent = 10
        self.venue.save()
        body = {"items": [{"product_id": self.item.id, "quantity": 1}], "tip": 5}
        q = self.client.post(reverse("quote"), json.dumps(body), content_type="application/json").json()
        self.assertEqual((q["subtotal"], q["tax"], q["tip"], q["total"]), (100000, 10000, 5000, 115000))
        self.assertEqual(Order.objects.count(), 0)  # quoting never creates anything

    def test_money_rounding_is_integer(self):
        self.venue.tax_percent = 9
        self.venue.save()
        odd = Item.objects.create(name="x", drink_type="cakes", price_cents=12345)
        body = {"table_qr": self.table.qr_slug, "items": [{"product_id": odd.id, "quantity": 3}]}
        self.client.post(reverse("create_order"), json.dumps(body), content_type="application/json")
        o = Order.objects.get()
        self.assertIsInstance(o.tax_cents, int)
        self.assertEqual(o.total_cents, o.subtotal_cents + o.tax_cents)


class OnlinePaymentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.table = Table.objects.create(number="1")
        self.item = Item.objects.create(name="چای", drink_type="hot drink", price_cents=50000)
        v = Venue.load()
        v.online_payment_enabled, v.zarinpal_merchant_id, v.zarinpal_sandbox = True, "m-1", True
        v.save()
        r = self.client.post(reverse("create_order"), json.dumps({
            "table_qr": self.table.qr_slug, "payment": "online",
            "items": [{"product_id": self.item.id, "quantity": 1}]}), content_type="application/json")
        self.data = r.json()
        self.order = Order.objects.get()

    def test_order_marked_online_and_points_to_gateway_start(self):
        self.assertEqual(self.order.payment_method, "online")
        self.assertTrue(self.data["pay_url"].endswith(f"/pay/{self.order.public_token}/"))

    def test_start_sends_rial_amount_and_redirects(self):
        with mock.patch.object(payments, "_post", return_value={"data": {"code": 100, "authority": "A123"}}) as m:
            r = self.client.get(self.data["pay_url"])
        self.assertEqual(r.status_code, 302)
        self.assertIn("sandbox.zarinpal.com/pg/StartPay/A123", r["Location"])
        sent = m.call_args[0][1]
        self.assertEqual(sent["amount"], 500000)  # toman -> rial
        self.assertEqual(sent["merchant_id"], "m-1")
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_ref, "A123")

    def test_callback_verifies_and_marks_paid(self):
        Order.objects.filter(pk=self.order.pk).update(payment_ref="A123")
        url = reverse("pay_callback", args=[self.order.public_token])
        with mock.patch.object(payments, "_post", return_value={"data": {"code": 100, "ref_id": 777}}):
            r = self.client.get(url, {"Authority": "A123", "Status": "OK"})
        self.assertEqual(r.status_code, 302)
        self.order.refresh_from_db()
        self.assertTrue(self.order.paid)
        self.assertIn("777", self.order.payment_ref)

    def test_callback_rejects_foreign_authority_and_failed_status(self):
        Order.objects.filter(pk=self.order.pk).update(payment_ref="A123")
        url = reverse("pay_callback", args=[self.order.public_token])
        with mock.patch.object(payments, "_post") as m:
            self.client.get(url, {"Authority": "OTHER", "Status": "OK"})
            self.client.get(url, {"Authority": "A123", "Status": "NOK"})
            m.assert_not_called()
        self.order.refresh_from_db()
        self.assertFalse(self.order.paid)

    def test_unverified_payment_stays_unpaid(self):
        Order.objects.filter(pk=self.order.pk).update(payment_ref="A123")
        with mock.patch.object(payments, "_post", return_value={"data": {}, "errors": {"code": -51}}):
            self.client.get(reverse("pay_callback", args=[self.order.public_token]), {"Authority": "A123", "Status": "OK"})
        self.order.refresh_from_db()
        self.assertFalse(self.order.paid)

    def test_gateway_down_is_handled(self):
        with mock.patch.object(payments, "_post", side_effect=payments.PaymentError("down")):
            r = self.client.get(self.data["pay_url"])
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"/o/{self.order.public_token}/", r["Location"])

    def test_online_ignored_when_not_configured(self):
        v = Venue.load()
        v.online_payment_enabled = False
        v.save()
        cache.clear()
        r = self.client.post(reverse("create_order"), json.dumps({
            "table_qr": self.table.qr_slug, "payment": "online",
            "items": [{"product_id": self.item.id, "quantity": 1}]}), content_type="application/json").json()
        self.assertEqual(r["pay_url"], "")


class BrandColourTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.client.force_login(User.objects.create_user("boss", password="pw-12345-x", is_staff=True))

    def settings_post(self, **over):
        data = {"name": "کافه", "tagline": "", "accent_color": "#112233", "secondary_color": "#445566",
                "phone": "", "address": "", "instagram": "", "wifi_name": "", "wifi_password": "", "notice": "",
                "accepting_orders": "on", "tax_percent": 0, "service_percent": 0, "tips_enabled": "on", **over}
        return self.client.post(reverse("vendor:settings"), data)

    def test_primary_and_alternate_colours_are_saved_and_applied(self):
        self.assertEqual(self.settings_post().status_code, 302)
        v = Venue.objects.get()
        self.assertEqual((v.accent_color, v.secondary_color), ("#112233", "#445566"))
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn("--brand:#112233", html)
        self.assertIn("--alt:#445566", html)

    def test_invalid_colour_rejected(self):
        r = self.settings_post(secondary_color="red")
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(Venue.load().secondary_color, "red")

    def test_online_payment_requires_merchant_id(self):
        r = self.settings_post(online_payment_enabled="on", zarinpal_merchant_id="")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Venue.load().online_payment_enabled)

    def test_coupon_management(self):
        r = self.client.post(reverse("vendor:coupon_add"), {"code": "hi5", "percent": 5, "amount": 0, "min_order": 0, "is_active": "on"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Coupon.objects.filter(code="HI5").exists())
        both = self.client.post(reverse("vendor:coupon_add"), {"code": "BAD", "percent": 5, "amount": 100, "min_order": 0})
        self.assertEqual(both.status_code, 200)  # must pick percent OR amount
        self.assertEqual(self.client.get(reverse("vendor:coupons")).status_code, 200)

