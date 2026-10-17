from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from management.models import Item, Order, OrderItem, Table

User = get_user_model()

STAFF_GET = [
    "vendor:dashboard", "vendor:board", "vendor:board_feed", "vendor:orders", "vendor:orders_export",
    "vendor:items", "vendor:item_add", "vendor:tables", "vendor:table_add", "vendor:tables_print", "vendor:settings",
]


class AccessControlTests(TestCase):
    def setUp(self):
        cache.clear()
        self.customer = User.objects.create_user("cust", password="pw-12345-x")
        self.staff = User.objects.create_user("boss", password="pw-12345-x", is_staff=True)
        self.item = Item.objects.create(name="x", drink_type="cakes", price_cents=1)
        self.table = Table.objects.create(number="1")
        self.order = Order.objects.create(table=self.table)

    def test_anonymous_redirected_to_login(self):
        for name in STAFF_GET:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn("/users/login/", r["Location"], name)

    def test_regular_user_is_blocked_everywhere(self):
        """Regression: item/table views used to require only login, not staff."""
        self.client.force_login(self.customer)
        for name in STAFF_GET:
            self.assertEqual(self.client.get(reverse(name)).status_code, 302, name)
        for url in [reverse("vendor:item_edit", args=[self.item.id]), reverse("vendor:item_delete", args=[self.item.id]),
                    reverse("vendor:table_delete", args=[self.table.id]), reverse("vendor:order_detail", args=[self.order.id])]:
            self.assertEqual(self.client.get(url).status_code, 302, url)
        r = self.client.post(reverse("vendor:order_status", args=[self.order.id]), {"status": "preparing"})
        self.assertEqual(r.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "new")
        self.client.post(reverse("vendor:item_delete", args=[self.item.id]))
        self.assertTrue(Item.objects.filter(id=self.item.id).exists())

    def test_staff_can_open_all_pages(self):
        self.client.force_login(self.staff)
        for name in STAFF_GET:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse("vendor:table_qr", args=[self.table.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse("vendor:order_detail", args=[self.order.id])).status_code, 200)


class StaffActionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user("boss", password="pw-12345-x", is_staff=True)
        self.client.force_login(self.staff)
        self.table = Table.objects.create(number="1")
        self.item = Item.objects.create(name="لاته", drink_type="hot coffee", price_cents=5000)
        self.order = Order.objects.create(table=self.table, total_cents=10000)
        OrderItem.objects.create(order=self.order, product=self.item, product_name="لاته", quantity=2, unit_price_cents=5000)

    def test_status_progression_and_invalid(self):
        url = reverse("vendor:order_status", args=[self.order.id])
        self.assertEqual(self.client.post(url, {"status": "preparing"}).status_code, 200)
        self.assertEqual(self.client.post(url, {"status": "garbage"}).status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "preparing")

    def test_status_requires_post(self):
        self.assertEqual(self.client.get(reverse("vendor:order_status", args=[self.order.id])).status_code, 405)

    def test_paid_toggle(self):
        url = reverse("vendor:order_paid", args=[self.order.id])
        self.client.post(url, {"paid": "1"})
        self.order.refresh_from_db()
        self.assertTrue(self.order.paid)
        self.assertIsNotNone(self.order.paid_at)
        self.client.post(url, {"paid": "0"})
        self.order.refresh_from_db()
        self.assertFalse(self.order.paid)

    def test_item_toggle(self):
        r = self.client.post(reverse("vendor:item_toggle", args=[self.item.id]))
        self.assertFalse(r.json()["available"])

    def test_board_feed_shape(self):
        data = self.client.get(reverse("vendor:board_feed")).json()
        self.assertEqual(len(data["orders"]), 1)
        self.assertEqual(data["orders"][0]["items"][0]["name"], "لاته")

    def test_deleting_product_keeps_history(self):
        self.client.post(reverse("vendor:item_delete", args=[self.item.id]))
        oi = OrderItem.objects.get()
        self.assertIsNone(oi.product)
        self.assertEqual(oi.display_name, "لاته")

    def test_duplicate_table_number_rejected(self):
        r = self.client.post(reverse("vendor:table_add"), {"number": "1", "notes": ""})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Table.objects.count(), 1)

    def test_csv_export_and_search(self):
        r = self.client.get(reverse("vendor:orders_export"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])
        self.assertContains(self.client.get(reverse("vendor:orders"), {"q": str(self.order.id)}), "لاته")

    def test_dashboard_stats_with_data(self):
        self.order.set_status("delivered")
        r = self.client.get(reverse("vendor:dashboard"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["stats"]["today_orders"], 1)
        self.assertEqual(r.context["stats"]["top"][0]["name"], "لاته")
