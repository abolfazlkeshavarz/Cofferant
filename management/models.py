import secrets

from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

from licensing.tenancy import current_alias


# -----------------------------
# Venue (single-row branding / behaviour settings)
# -----------------------------
class Venue(models.Model):
    name = models.CharField("نام کافه / رستوران", max_length=100, default="کافیرانت")
    tagline = models.CharField("شعار", max_length=150, blank=True, default="بهترین قهوه، سریع‌ترین سرویس")
    accent_color = models.CharField(
        "رنگ اصلی",
        max_length=7,
        default="#059669",
        validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", "رنگ باید به شکل #RRGGBB باشد")],
    )
    secondary_color = models.CharField(
        "رنگ فرعی",
        max_length=7,
        default="#F97316",
        validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", "رنگ باید به شکل #RRGGBB باشد")],
    )
    logo = models.ImageField("لوگو", upload_to="branding", blank=True)
    phone = models.CharField("تلفن", max_length=30, blank=True)
    address = models.CharField("آدرس", max_length=250, blank=True)
    instagram = models.CharField("اینستاگرام", max_length=100, blank=True)
    wifi_name = models.CharField("نام وای‌فای", max_length=80, blank=True)
    wifi_password = models.CharField("رمز وای‌فای", max_length=80, blank=True)
    accepting_orders = models.BooleanField(
        "دریافت سفارش آنلاین", default=True,
        help_text="با خاموش کردن، مشتری‌ها فقط منو را می‌بینند و سفارش ثبت نمی‌شود.",
    )
    notice = models.CharField("اطلاعیه بالای منو", max_length=200, blank=True)

    # ---- money ----
    tax_percent = models.PositiveSmallIntegerField(
        "مالیات (٪)", default=0, validators=[MaxValueValidator(30)])
    service_percent = models.PositiveSmallIntegerField(
        "حق سرویس (٪)", default=0, validators=[MaxValueValidator(30)])
    tips_enabled = models.BooleanField("امکان انعام در سفارش", default=True)
    online_payment_enabled = models.BooleanField("پرداخت آنلاین (زرین‌پال)", default=False)
    zarinpal_merchant_id = models.CharField("مرچنت‌کد زرین‌پال", max_length=64, blank=True)
    zarinpal_sandbox = models.BooleanField("حالت آزمایشی زرین‌پال", default=False)

    class Meta:
        verbose_name = "تنظیمات کافه"
        verbose_name_plural = "تنظیمات کافه"

    def __str__(self):
        return self.name

    @staticmethod
    def _cache_key():
        return f"venue_singleton_v2:{current_alias()}"  # one entry per tenant database

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self._cache_key())

    @classmethod
    def load(cls):
        key = cls._cache_key()
        obj = cache.get(key)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(key, obj, 60)
        return obj

    @property
    def online_payment_ready(self):
        return self.online_payment_enabled and bool(self.zarinpal_merchant_id)


# -----------------------------
# Item (Product)
# -----------------------------
class Category(models.Model):
    """A menu section the vendor defines (Hot coffee, Breakfast, Kids…)."""
    name = models.CharField("نام دسته", max_length=60)
    emoji = models.CharField("شکلک (اختیاری)", max_length=8, blank=True)
    sort_order = models.PositiveIntegerField("ترتیب نمایش", default=0)
    is_active = models.BooleanField("نمایش در منو", default=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "دسته‌بندی"
        verbose_name_plural = "دسته‌بندی‌ها"

    def __str__(self):
        return self.name

    @property
    def label(self):
        return f"{self.emoji} {self.name}".strip()


# Suggested starter categories (offered with one click; vendors can rename, delete or add their own)
DEFAULT_CATEGORIES = [
    ("قهوه گرم", "☕"), ("قهوه سرد", "🧊"), ("نوشیدنی گرم", "🍵"),
    ("نوشیدنی سرد", "🥤"), ("کیک و دسر", "🍰"),
]


def create_default_categories():
    if Category.objects.exists():
        return 0
    Category.objects.bulk_create(
        [Category(name=n, emoji=e, sort_order=i) for i, (n, e) in enumerate(DEFAULT_CATEGORIES)])
    return len(DEFAULT_CATEGORIES)


class Item(models.Model):
    CHOICES = (
        ('hot coffee', 'قهوه گرم'),
        ('cold coffee', 'قهوه سرد'),
        ('hot drink', 'نوشیدنی گرم'),
        ('cold drink', 'نوشیدنی سرد'),
        ('cakes', 'کیک و دسر'),
    )

    name = models.CharField(max_length=100)
    category = models.ForeignKey(
        "management.Category", on_delete=models.SET_NULL, null=True, blank=True, related_name="items",
        verbose_name="دسته‌بندی")
    drink_type = models.CharField(max_length=100, choices=CHOICES, blank=True, default="")  # legacy, replaced by category
    specs = models.TextField(max_length=150, blank=True)
    price_cents = models.PositiveIntegerField(default=0)  # price in Toman
    customizable = models.BooleanField(
        default=False,
        help_text="Allow customer to add custom notes/details (e.g., 70/30, extra sugar)"
    )
    image = models.ImageField(upload_to='images', blank=True)

    is_available = models.BooleanField(
        default=True,
        help_text="Uncheck this if the item is temporarily unavailable (ناموجود)"
    )
    is_popular = models.BooleanField(default=False)
    prep_minutes = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(120)]
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


# -----------------------------
# Table (QR-enabled)
# -----------------------------
def make_qr_slug():
    return secrets.token_urlsafe(6)


class Table(models.Model):
    number = models.CharField(max_length=50)   # e.g., "T1", "A2"
    qr_slug = models.CharField(max_length=100, unique=True, default=make_qr_slug)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"Table {self.number}"


# -----------------------------
# Coupon (discount codes)
# -----------------------------
class Coupon(models.Model):
    code = models.CharField("کد", max_length=30, unique=True)
    percent = models.PositiveSmallIntegerField(
        "درصد تخفیف", default=0, validators=[MaxValueValidator(100)],
        help_text="یا درصد یا مبلغ ثابت را پر کنید.")
    amount = models.PositiveIntegerField("مبلغ ثابت (تومان)", default=0)
    min_order = models.PositiveIntegerField("حداقل سفارش (تومان)", default=0)
    max_uses = models.PositiveIntegerField("حداکثر دفعات استفاده", null=True, blank=True)
    used_count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField("تاریخ انقضا", null=True, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.code

    @property
    def label(self):
        return f"{self.percent}٪" if self.percent else f"{self.amount:,} تومان"

    def discount_for(self, subtotal):
        """Return the discount for this subtotal or raise ValueError(user message)."""
        if not self.is_active:
            raise ValueError("این کد تخفیف فعال نیست.")
        if self.expires_at and self.expires_at <= timezone.now():
            raise ValueError("این کد تخفیف منقضی شده است.")
        if self.max_uses is not None and self.used_count >= self.max_uses:
            raise ValueError("ظرفیت استفاده از این کد تمام شده است.")
        if subtotal < self.min_order:
            raise ValueError(f"حداقل مبلغ سفارش برای این کد {self.min_order:,} تومان است.")
        discount = subtotal * self.percent // 100 if self.percent else self.amount
        return min(discount, subtotal)


# -----------------------------
# Order (one per customer visit)
# -----------------------------
def make_public_token():
    return secrets.token_urlsafe(12)


class Order(models.Model):
    STATUS_CHOICES = [
        ("new", "جدید"),
        ("preparing", "در حال آماده‌سازی"),
        ("ready", "آماده تحویل"),
        ("delivered", "تحویل شده"),
        ("cancelled", "لغو شده"),
    ]
    # Forward-only workflow shown on the live board
    FLOW = ["new", "preparing", "ready", "delivered"]
    ACTIVE = ("new", "preparing", "ready")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    public_token = models.CharField(max_length=40, unique=True, default=make_public_token, editable=False)
    table = models.ForeignKey(
        Table,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new", db_index=True)
    total_cents = models.PositiveIntegerField(default=0)  # final amount payable
    subtotal_cents = models.PositiveIntegerField(default=0)
    discount_cents = models.PositiveIntegerField(default=0)
    service_cents = models.PositiveIntegerField(default=0)
    tax_cents = models.PositiveIntegerField(default=0)
    tip_cents = models.PositiveIntegerField(default=0)
    coupon_code = models.CharField(max_length=30, blank=True)
    payment_method = models.CharField(
        max_length=10, default="cash", choices=[("cash", "هنگام تحویل"), ("online", "آنلاین")])
    payment_ref = models.CharField(max_length=80, blank=True)  # gateway authority / ref id

    customer_name = models.CharField(max_length=150, blank=True)
    customer_phone = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True, max_length=500)

    paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)

    rating = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    feedback = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order #{self.id} - {self.get_status_display()}"

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def total_price(self):
        return sum(item.line_total() for item in self.items.all())

    @property
    def is_active(self):
        return self.status in self.ACTIVE

    @property
    def next_status(self):
        if self.status in self.FLOW[:-1]:
            return self.FLOW[self.FLOW.index(self.status) + 1]
        return None

    @property
    def minutes_waiting(self):
        return max(0, int((timezone.now() - self.created_at).total_seconds() // 60))

    def set_status(self, new_status):
        """Apply a status change. Returns True if something changed."""
        valid = {c for c, _ in self.STATUS_CHOICES}
        if new_status not in valid or new_status == self.status:
            return False
        if self.status in ("delivered", "cancelled") and new_status != "cancelled":
            return False  # finished orders only allow an explicit cancel
        self.status = new_status
        self.save(update_fields=["status", "updated_at"])
        return True

    def set_paid(self, paid=True):
        self.paid = paid
        self.paid_at = timezone.now() if paid else None
        self.save(update_fields=["paid", "paid_at", "updated_at"])


# -----------------------------
# OrderItem (product inside an order)
# -----------------------------
class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items"
    )
    product = models.ForeignKey(
        "management.Item",
        on_delete=models.SET_NULL,
        null=True
    )
    # Snapshot so history survives product edits/deletion
    product_name = models.CharField(max_length=100, blank=True)
    quantity = models.PositiveIntegerField(default=1)

    # Snapshot of price at time of order
    unit_price_cents = models.PositiveIntegerField(default=0)

    # Special customer note (e.g. 70/30 espresso)
    note = models.CharField(max_length=200, blank=True)

    def line_total(self):
        return self.unit_price_cents * self.quantity

    @property
    def display_name(self):
        if self.product_name:
            return self.product_name
        return self.product.name if self.product else "محصول حذف‌شده"

    def __str__(self):
        return f"{self.quantity} x {self.display_name}"


# -----------------------------
# ServiceRequest (call waiter / ask for the bill from the table)
# -----------------------------
class ServiceRequest(models.Model):
    KINDS = [
        ("waiter", "فراخوانی گارسون"),
        ("bill", "درخواست صورت‌حساب"),
        ("water", "درخواست آب"),
    ]
    table = models.ForeignKey(Table, on_delete=models.CASCADE, related_name="requests")
    kind = models.CharField(max_length=20, choices=KINDS)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} - {self.table}"

    @property
    def is_open(self):
        return self.resolved_at is None
