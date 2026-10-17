import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from . import checker, tenancy
from .models import PLAN_DAYS, License, LicenseEvent, PlanPrice

DEFAULT_OWNER = "owner"
MIN_PASSWORD = 8


def new_password():
    return secrets.token_urlsafe(9)


# ---------------------------------------------------------------- prices
def get_prices():
    """Plan prices in toman: the developer's saved values, falling back to the defaults in settings."""
    prices = dict(settings.PLAN_PRICES)
    prices.update({p.code: p.price for p in PlanPrice.objects.all()})
    return prices


def save_prices(values):
    for code, price in values.items():
        if code in PLAN_DAYS:
            PlanPrice.objects.update_or_create(code=code, defaults={"price": int(price)})


# ---------------------------------------------------------------- customers
def create_customer(form, owner_password=""):
    """Create the License (+ the tenant database and owner login for hosted customers).

    Returns (license, credentials_or_None). A blank password is generated.
    """
    lic = form.save(commit=False)
    days = PLAN_DAYS[lic.plan]
    lic.starts_at = timezone.now()
    lic.expires_at = None if days is None else lic.starts_at + timedelta(days=days)
    lic.owner_username = (lic.owner_username or DEFAULT_OWNER).strip()
    creds = None
    with transaction.atomic():
        lic.save()
        lic.log("created", lic.get_plan_display(), amount=lic.price_paid)
        if lic.mode == License.HOSTED:
            password = owner_password or new_password()
            tenancy.provision_tenant(lic.slug, lic.business_name, lic.owner_username, password, lic.email)
            creds = {"url": f"https://{lic.hostname}", "username": lic.owner_username, "password": password}
    return lic, creds


def set_owner_password(lic, password=None):
    """Set (or, with no argument, randomise) the vendor's panel password. Returns the credentials."""
    password = password or new_password()
    with tenancy.use_tenant(lic.slug):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user, _ = User.objects.get_or_create(username=lic.owner_username, defaults={"is_staff": True})
        user.is_staff = True
        user.is_active = True
        user.set_password(password)
        user.save()
    lic.log("password_set", "رمز مدیر مجموعه تعیین شد")
    return {"url": f"https://{lic.hostname}", "username": lic.owner_username, "password": password}


def reset_owner_password(lic):
    return set_owner_password(lic)


def apply_and_invalidate(lic, action, *args, **kw):
    getattr(lic, action)(*args, **kw)
    checker.invalidate(lic)


def purge_license(lic):
    """Irreversibly delete a trashed customer: tenant database, photos and the license record."""
    if not lic.in_trash:
        raise ValueError("only trashed licenses can be purged")
    slug = lic.slug
    checker.invalidate(lic)
    if lic.mode == License.HOSTED and slug:
        tenancy.drop_tenant(slug)
    lic.delete()
    if slug:
        checker.invalidate(License(slug=slug))


# ---------------------------------------------------------------- stats
def developer_stats():
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    qs = License.objects.filter(deleted_at__isnull=True)
    rows = list(qs)
    active = [lic for lic in rows if lic.is_valid]
    soon = sorted([lic for lic in active if lic.days_left is not None and lic.days_left <= 14], key=lambda x: x.expires_at)
    revenue_month = LicenseEvent.objects.filter(created_at__gte=month_start).aggregate(s=Sum("amount"))["s"] or 0
    revenue_total = LicenseEvent.objects.aggregate(s=Sum("amount"))["s"] or 0
    months, cursor = [], month_start
    for _ in range(6):
        months.append(cursor)
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    months.reverse()
    bars = []
    for i, start in enumerate(months):
        end = months[i + 1] if i + 1 < len(months) else (month_start + timedelta(days=32)).replace(day=1)
        amount = LicenseEvent.objects.filter(created_at__gte=start, created_at__lt=end).aggregate(s=Sum("amount"))["s"] or 0
        bars.append({"date": start, "amount": amount})
    mx = max([b["amount"] for b in bars] + [1])
    for b in bars:
        b["pct"] = round(b["amount"] * 100 / mx)
        b["k"] = b["amount"] // 1000
    by_mode = dict(qs.values_list("mode").annotate(c=Count("id")))
    return {
        "total": len(rows),
        "active": len(active),
        "cancelled": sum(1 for lic in rows if lic.state == "cancelled"),
        "expired": sum(1 for lic in rows if lic.state == "expired"),
        "trash": License.objects.filter(deleted_at__isnull=False).count(),
        "soon": soon,
        "revenue_month": revenue_month,
        "revenue_total": revenue_total,
        "bars": bars,
        "hosted": by_mode.get(License.HOSTED, 0),
        "self": by_mode.get(License.SELF, 0),
    }
