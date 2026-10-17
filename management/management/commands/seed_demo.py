import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from management.models import Category, Item, Order, OrderItem, Table, Venue, create_default_categories

MENU = [
    ("hot coffee", "اسپرسو", "دو شات قهوه عربیکا با کرمای غلیظ", 85000, True, True),
    ("hot coffee", "لاته", "اسپرسو با شیر بخار داده‌شده و فوم ابریشمی", 120000, False, True),
    ("hot coffee", "کاپوچینو", "یک سوم اسپرسو، یک سوم شیر، یک سوم فوم", 125000, False, False),
    ("cold coffee", "آیس آمریکانو", "اسپرسو دوبل روی یخ", 110000, False, True),
    ("cold coffee", "آیس لاته کارامل", "لاته سرد با سس کارامل خانگی", 145000, False, False),
    ("hot drink", "چای ماسالا", "چای ادویه‌دار هندی با شیر", 95000, False, False),
    ("hot drink", "هات چاکلت", "شکلات بلژیکی با خامه", 130000, False, False),
    ("cold drink", "لیموناد نعنا", "لیمو تازه، نعنا و عسل", 90000, False, False),
    ("cakes", "چیزکیک نیویورکی", "با سس توت‌فرنگی", 155000, False, True),
    ("cakes", "براونی", "براونی گرم با بستنی وانیل", 140000, False, False),
]


class Command(BaseCommand):
    help = "Fill the database with a demo menu, tables and sample orders (safe to re-run)."

    @transaction.atomic
    def handle(self, *args, **opts):
        Venue.load()
        create_default_categories()
        names = {"hot coffee": "قهوه گرم", "cold coffee": "قهوه سرد", "hot drink": "نوشیدنی گرم",
                 "cold drink": "نوشیدنی سرد", "cakes": "کیک و دسر"}
        items = []
        for i, (cat, name, specs, price, custom, popular) in enumerate(MENU):
            obj, _ = Item.objects.get_or_create(name=name, defaults=dict(
                category=Category.objects.filter(name=names[cat]).first(), specs=specs, price_cents=price, customizable=custom, is_popular=popular, sort_order=i))
            items.append(obj)
        tables = [Table.objects.get_or_create(number=str(n))[0] for n in range(1, 7)]

        if not Order.objects.exists():
            rnd = random.Random(7)
            now = timezone.now()
            for n in range(45):
                when = now - timedelta(days=rnd.randint(0, 6), hours=rnd.randint(0, 9), minutes=rnd.randint(0, 59))
                o = Order.objects.create(table=rnd.choice(tables), status="delivered", paid=True, paid_at=when,
                                         customer_name=rnd.choice(["علی", "سارا", "مینا", "رضا", ""]),
                                         rating=rnd.choice([None, 4, 5, 5]))
                total = 0
                for it in rnd.sample(items, rnd.randint(1, 3)):
                    q = rnd.randint(1, 2)
                    OrderItem.objects.create(order=o, product=it, product_name=it.name, quantity=q, unit_price_cents=it.price_cents)
                    total += q * it.price_cents
                Order.objects.filter(pk=o.pk).update(created_at=when, updated_at=when, total_cents=total)
            for st in ("new", "preparing", "ready"):
                o = Order.objects.create(table=rnd.choice(tables), status=st, customer_name="مشتری نمونه")
                it = rnd.choice(items)
                OrderItem.objects.create(order=o, product=it, product_name=it.name, quantity=2, unit_price_cents=it.price_cents)
                Order.objects.filter(pk=o.pk).update(total_cents=2 * it.price_cents)
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
