"""Decides whether the current request's venue is allowed to run.

* platform mode, tenant sub-domain -> look the customer's license up locally
* standalone + LICENSE_ENFORCE=1   -> ask the developer's server (cached, with offline grace)
* everything else                  -> allowed
"""
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone as dt_tz
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .tenancy import current_tenant

log = logging.getLogger("cofferant")

MESSAGES = {
    "cancelled": "اشتراک این مجموعه توسط ارائه‌دهنده لغو شده است.",
    "expired": "اشتراک این مجموعه به پایان رسیده است.",
    "missing": "کلید لایسنس برای این نصب تنظیم نشده است.",
    "unknown": "لایسنس معتبر پیدا نشد.",
    "unreachable": "ارتباط با سرور لایسنس برقرار نیست و مهلت آفلاین به پایان رسیده است.",
}


@dataclass
class LicenseState:
    valid: bool
    status: str = "active"  # active | expired | cancelled | missing | unknown | unreachable | unenforced
    message: str = ""
    plan: str = ""
    business: str = ""
    expires_at: Optional[datetime] = None
    days_left: Optional[int] = None

    @property
    def expiring_soon(self):
        return self.valid and self.days_left is not None and self.days_left <= 7


def _from_license(lic):
    st = lic.state
    return LicenseState(
        valid=lic.is_valid, status=st, message="" if lic.is_valid else MESSAGES[st],
        plan=lic.plan, business=lic.business_name, expires_at=lic.expires_at, days_left=lic.days_left,
    )


def hosted_state(slug):
    from .models import License  # local import: apps must be ready

    key = f"lic:slug:{slug}"
    state = cache.get(key)
    if state is None:
        lic = License.objects.filter(mode=License.HOSTED, slug=slug).first()
        state = _from_license(lic) if lic else LicenseState(False, "unknown", MESSAGES["unknown"])
        cache.set(key, state, 15)  # short TTL: a cancellation bites within seconds
    return state


def invalidate(license_obj):
    if license_obj.slug:
        cache.delete(f"lic:slug:{license_obj.slug}")


def _remote_fetch(key, host):
    url = f"{settings.LICENSE_SERVER_URL}/api/license/verify/"
    req = urllib.request.Request(
        url, data=json.dumps({"key": key, "host": host}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "cofferant-license/1"},
    )
    with urllib.request.urlopen(req, timeout=6) as resp:
        return json.loads(resp.read().decode())


def remote_state(host=""):
    if not settings.LICENSE_KEY or not settings.LICENSE_SERVER_URL:
        return LicenseState(False, "missing", MESSAGES["missing"])
    fresh_key, good_key = "lic:remote:fresh", "lic:remote:lastgood"
    state = cache.get(fresh_key)
    if state is not None:
        return state
    try:
        data = _remote_fetch(settings.LICENSE_KEY, host)
        exp = data.get("expires_at")
        expires = datetime.fromisoformat(exp) if exp else None
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=dt_tz.utc)
        state = LicenseState(
            valid=bool(data.get("valid")), status=data.get("status", "unknown"),
            message="" if data.get("valid") else MESSAGES.get(data.get("status"), MESSAGES["unknown"]),
            plan=data.get("plan", ""), business=data.get("business", ""),
            expires_at=expires, days_left=data.get("days_left"),
        )
        cache.set(fresh_key, state, 300)
        if state.valid:
            cache.set(good_key, (timezone.now(), state), None)
        else:
            cache.delete(good_key)  # an explicit refusal ends any offline grace
        return state
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("license server unreachable: %s", exc)
        last = cache.get(good_key)
        if last and (timezone.now() - last[0]).total_seconds() < settings.LICENSE_GRACE_HOURS * 3600:
            cache.set(fresh_key, last[1], 60)  # retry soon
            return last[1]
        state = LicenseState(False, "unreachable", MESSAGES["unreachable"])
        cache.set(fresh_key, state, 30)
        return state


def current_state(host=""):
    slug = current_tenant.get()
    if settings.DEPLOYMENT_MODE == "platform":
        return hosted_state(slug) if slug else LicenseState(True, "unenforced")
    if settings.LICENSE_ENFORCE:
        return remote_state(host)
    return LicenseState(True, "unenforced")
