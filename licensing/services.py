import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from . import checker, tenancy
from .models import PLAN_DAYS, License, LicenseEvent

OWNER_USERNAME = "owner"


def new_password():
    return secrets.token_urlsafe(9)


def create_customer(form):
    """Create the License (+ the tenant database and owner login for hosted customers).

    Returns (license, credentials_or_None).
    """
    lic = form.save(commit=False)
    days = PLAN_DAYS[lic.plan]
    lic.starts_at = timezone.now()
    lic.expires_at = None if days is None else lic.starts_at + timedelta(days=days)
    creds = None
    with transaction.atomic():
        lic.save()
        lic.log("created", lic.get_plan_display(), amount=lic.price_paid)
        if lic.mode == License.HOSTED:
            password = new_password()
            tenancy.provision_tenant(lic.slug, lic.business_name, OWNER_USERNAME, password, lic.email)
            creds = {"url": f"https://{lic.hostname}", "username": OWNER_USERNAME, "password": password}
    return lic, creds


def reset_owner_password(lic):
    password = new_password()
    with tenancy.use_tenant(lic.slug):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user, _ = User.objects.get_or_create(username=OWNER_USERNAME, defaults={"is_staff": True})
        user.is_staff = True
        user.set_password(password)
        user.save()
    lic.log("password_reset", "رمز مدیر مجموعه بازنشانی شد")
    return {"url": f"https://{lic.hostname}", "username": OWNER_USERNAME, "password": password}


def apply_and_invalidate(lic, action, *args, **kw):
    getattr(lic, action)(*args, **kw)
    checker.invalidate(lic)


def developer_stats():
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    qs = License.objects.all()
    active = [lic for lic in qs if lic.is_valid]
    soon = sorted([lic for lic in active if lic.days_left is not None and lic.days_left <= 14], key=lambda x: x.expires_at)
    revenue_month = LicenseEvent.objects.filter(created_at__gte=month_start).aggregate(s=Sum("amount"))["s"] or 0
    revenue_total = LicenseEvent.objects.aggregate(s=Sum("amount"))["s"] or 0
    # last 6 months revenue bars
    bars = []
    cursor = month_start
    months = []
    for _ in range(6):
        months.append(cursor)
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    months.reverse()
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
        "total": qs.count(),
        "active": len(active),
        "cancelled": qs.filter(status=License.CANCELLED).count(),
        "expired": sum(1 for lic in qs if lic.state == "expired"),
        "soon": soon,
        "revenue_month": revenue_month,
        "revenue_total": revenue_total,
        "bars": bars,
        "hosted": by_mode.get(License.HOSTED, 0),
        "self": by_mode.get(License.SELF, 0),
        "prices": settings.PLAN_PRICES,
    }
