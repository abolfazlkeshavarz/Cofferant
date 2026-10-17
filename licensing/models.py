import secrets
from datetime import timedelta

from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

# (code, label, days) - days=None means forever
PLANS = [
    ("1m", "۱ ماهه", 30),
    ("3m", "۳ ماهه", 91),
    ("6m", "۶ ماهه", 183),
    ("1y", "۱ ساله", 365),
    ("2y", "۲ ساله", 730),
    ("forever", "دائمی", None),
]
PLAN_CHOICES = [(c, label) for c, label, _ in PLANS]
PLAN_DAYS = {c: d for c, _, d in PLANS}


def make_key():
    raw = secrets.token_hex(8).upper()
    return "CFR-" + "-".join(raw[i:i + 4] for i in range(0, 16, 4))


class License(models.Model):
    HOSTED = "hosted"
    SELF = "self"
    MODES = [(HOSTED, "پنل روی دامنه ما (SaaS)"), (SELF, "نصب روی دامنه مشتری")]

    ACTIVE = "active"
    CANCELLED = "cancelled"

    key = models.CharField(max_length=40, unique=True, default=make_key, editable=False)
    business_name = models.CharField("نام کسب‌وکار", max_length=120)
    contact_name = models.CharField("نام مسئول", max_length=120, blank=True)
    phone = models.CharField("تلفن", max_length=30, blank=True)
    email = models.EmailField("ایمیل", blank=True)
    notes = models.TextField("یادداشت", blank=True)

    mode = models.CharField("روش راه‌اندازی", max_length=10, choices=MODES, default=HOSTED)
    slug = models.CharField(
        "زیردامنه", max_length=30, unique=True, null=True, blank=True,
        validators=[RegexValidator(r"^[a-z0-9][a-z0-9-]{1,28}[a-z0-9]$", "فقط حروف کوچک انگلیسی، عدد و خط تیره")],
    )
    domain = models.CharField("دامنه مشتری", max_length=120, blank=True)

    plan = models.CharField("اشتراک", max_length=10, choices=PLAN_CHOICES, default="1m")
    starts_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField("تاریخ انقضا", null=True, blank=True)  # NULL = forever
    price_paid = models.PositiveIntegerField("مبلغ دریافتی (تومان)", default=0)

    status = models.CharField(max_length=10, default=ACTIVE, choices=[(ACTIVE, "فعال"), (CANCELLED, "لغو شده")], db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)

    owner_username = models.CharField("نام کاربری مدیر مجموعه", max_length=150, default="owner")
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)  # set = in the trash

    created_at = models.DateTimeField(auto_now_add=True)
    last_check_at = models.DateTimeField(null=True, blank=True)
    last_check_host = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.business_name} ({self.key})"

    # ---- state ----
    @property
    def in_trash(self):
        return self.deleted_at is not None

    @property
    def state(self):
        if self.deleted_at is not None:
            return "deleted"
        if self.status == self.CANCELLED:
            return "cancelled"
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return "expired"
        return "active"

    @property
    def is_valid(self):
        return self.state == "active"

    @property
    def is_forever(self):
        return self.expires_at is None

    @property
    def days_left(self):
        if self.expires_at is None:
            return None
        return max(0, (self.expires_at - timezone.now()).days)

    @property
    def subdomain_host(self):
        from django.conf import settings
        return f"{self.slug}.{settings.PLATFORM_DOMAIN}" if self.slug else ""

    @property
    def hostname(self):
        """The address customers use: their own domain when set, else our sub-domain."""
        if self.mode == self.HOSTED:
            return self.domain or self.subdomain_host
        return self.domain

    # ---- actions ----
    def log(self, kind, detail="", amount=0):
        return LicenseEvent.objects.create(license=self, kind=kind, detail=detail[:300], amount=amount)

    def extend(self, plan, price=0):
        """Add a subscription period. Extends from the current expiry when still running."""
        if plan not in PLAN_DAYS:
            raise ValueError("unknown plan")
        now = timezone.now()
        days = PLAN_DAYS[plan]
        keep_forever = (
            days is not None and self.expires_at is None
            and self.status == self.ACTIVE and self.plan == "forever" and self.pk
        )
        if days is None:
            self.expires_at = None
        elif not keep_forever:
            running = self.expires_at and self.expires_at > now and self.status == self.ACTIVE
            self.expires_at = (self.expires_at if running else now) + timedelta(days=days)
        if not keep_forever:
            self.plan = plan
        self.status = self.ACTIVE
        self.cancelled_at = None
        self.cancel_reason = ""
        self.price_paid += int(price or 0)
        self.save()
        self.log("renewed", dict(PLAN_CHOICES)[plan], amount=int(price or 0))

    def cancel(self, reason=""):
        self.status = self.CANCELLED
        self.cancelled_at = timezone.now()
        self.cancel_reason = reason[:200]
        self.save(update_fields=["status", "cancelled_at", "cancel_reason"])
        self.log("cancelled", reason)

    def move_to_trash(self):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])
        self.log("trashed", "به سطل زباله منتقل شد")

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])
        self.log("restored", "از سطل زباله برگشت")

    def reactivate(self):
        self.status = self.ACTIVE
        self.cancelled_at = None
        self.cancel_reason = ""
        self.save(update_fields=["status", "cancelled_at", "cancel_reason"])
        self.log("reactivated")


class LicenseEvent(models.Model):
    license = models.ForeignKey(License, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=20)
    detail = models.CharField(max_length=300, blank=True)
    amount = models.PositiveIntegerField(default=0)  # money received with this event (toman)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class PlanPrice(models.Model):
    """Subscription prices the developer edits in the panel (toman). Missing rows fall back to settings."""
    code = models.CharField(max_length=10, unique=True, choices=PLAN_CHOICES)
    price = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.code}: {self.price}"
