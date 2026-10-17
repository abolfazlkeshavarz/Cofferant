import json
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from management.services import throttled

from . import backup, services
from .forms import (CancelForm, LicenseCreateForm, OwnerPasswordForm, PricesForm,
                    PurgeForm, RenewForm)
from .models import PLAN_CHOICES, License


def developer_required(view):
    """The developer panel exists only on the platform's own domain and only for superusers."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if settings.DEPLOYMENT_MODE != "platform" or getattr(request, "tenant", None):
            raise Http404
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not (user.is_superuser and user.is_active):
            messages.error(request, "دسترسی به پنل توسعه‌دهنده فقط برای مدیر کل است.")
            return redirect("home")
        return view(request, *args, **kwargs)

    return wrapper


@developer_required
def dashboard(request):
    return render(request, "licensing/dashboard.html", {
        "stats": services.developer_stats(),
        "backups": backup.list_backups()[:1],
    })


@developer_required
def license_list(request):
    trash = request.GET.get("trash") == "1"
    qs = License.objects.filter(deleted_at__isnull=not trash)
    q = request.GET.get("q", "").strip()
    state = request.GET.get("state", "all")
    mode = request.GET.get("mode", "all")
    if q:
        qs = qs.filter(Q(business_name__icontains=q) | Q(contact_name__icontains=q) | Q(slug__icontains=q)
                       | Q(key__icontains=q) | Q(phone__icontains=q) | Q(domain__icontains=q))
    if mode in (License.HOSTED, License.SELF):
        qs = qs.filter(mode=mode)
    rows = list(qs)
    if state in ("active", "expired", "cancelled") and not trash:
        rows = [r for r in rows if r.state == state]
    page = Paginator(rows, 25).get_page(request.GET.get("page"))
    return render(request, "licensing/list.html", {
        "page": page, "q": q, "state": state, "mode": mode, "trash": trash,
        "trash_count": License.objects.filter(deleted_at__isnull=False).count(),
    })


@developer_required
def license_create(request):
    prices = services.get_prices()
    form = LicenseCreateForm(request.POST or None, initial={"price_paid": prices["1m"], "owner_username": "owner"})
    if request.method == "POST" and form.is_valid():
        lic, creds = services.create_customer(form, form.cleaned_data.get("owner_password", ""))
        if creds:
            request.session["flash_creds"] = creds
        messages.success(request, "مشتری و لایسنس ساخته شد.")
        return redirect("developer:detail", pk=lic.pk)
    return render(request, "licensing/create.html", {"form": form, "prices": prices})


@developer_required
def license_detail(request, pk):
    lic = get_object_or_404(License, pk=pk)
    prices = services.get_prices()
    return render(request, "licensing/detail.html", {
        "lic": lic, "events": lic.events.all()[:30],
        "creds": request.session.pop("flash_creds", None),
        "renew_form": RenewForm(initial={"plan": lic.plan if lic.plan != "forever" else "1y", "price": prices.get(lic.plan, 0)}),
        "cancel_form": CancelForm(),
        "password_form": OwnerPasswordForm(),
        "purge_form": PurgeForm(),
        "prices": prices,
        "server_url": f"https://{settings.PLATFORM_DOMAIN}",
        "plan_choices": PLAN_CHOICES,
    })


@developer_required
@require_POST
def license_renew(request, pk):
    lic = get_object_or_404(License, pk=pk, deleted_at__isnull=True)
    form = RenewForm(request.POST)
    if form.is_valid():
        services.apply_and_invalidate(lic, "extend", form.cleaned_data["plan"], form.cleaned_data["price"])
        messages.success(request, "اشتراک تمدید شد.")
    else:
        messages.error(request, "اطلاعات تمدید نامعتبر است.")
    return redirect("developer:detail", pk=pk)


@developer_required
@require_POST
def license_cancel(request, pk):
    lic = get_object_or_404(License, pk=pk, deleted_at__isnull=True)
    form = CancelForm(request.POST)
    services.apply_and_invalidate(lic, "cancel", form.cleaned_data.get("reason", "") if form.is_valid() else "")
    messages.warning(request, "اشتراک لغو شد؛ پنل مشتری از همین لحظه غیرفعال است.")
    return redirect("developer:detail", pk=pk)


@developer_required
@require_POST
def license_reactivate(request, pk):
    lic = get_object_or_404(License, pk=pk, deleted_at__isnull=True)
    services.apply_and_invalidate(lic, "reactivate")
    if lic.state == "expired":
        messages.warning(request, "اشتراک فعال شد ولی تاریخ انقضا گذشته است؛ لطفاً تمدید کنید.")
    else:
        messages.success(request, "اشتراک دوباره فعال شد.")
    return redirect("developer:detail", pk=pk)


@developer_required
@require_POST
def license_set_password(request, pk):
    """Developer chooses the vendor's password (or, with an empty box, gets a random one)."""
    lic = get_object_or_404(License, pk=pk, mode=License.HOSTED, deleted_at__isnull=True)
    raw = request.POST.get("password", "").strip()
    if raw:
        form = OwnerPasswordForm(request.POST)
        if not form.is_valid():
            messages.error(request, "رمز باید حداقل ۸ نویسه باشد.")
            return redirect("developer:detail", pk=pk)
        raw = form.cleaned_data["password"]
    request.session["flash_creds"] = services.set_owner_password(lic, raw or None)
    messages.success(request, "رمز مدیر مجموعه تعیین شد.")
    return redirect("developer:detail", pk=pk)


@developer_required
@require_POST
def license_trash(request, pk):
    lic = get_object_or_404(License, pk=pk, deleted_at__isnull=True)
    services.apply_and_invalidate(lic, "move_to_trash")
    messages.warning(request, "به سطل زباله منتقل شد؛ پنل و منوی مشتری از دسترس خارج شد. هر زمان می‌توانید برگردانید.")
    return redirect("developer:list")


@developer_required
@require_POST
def license_restore(request, pk):
    lic = get_object_or_404(License, pk=pk, deleted_at__isnull=False)
    services.apply_and_invalidate(lic, "restore")
    messages.success(request, "از سطل زباله برگردانده شد.")
    return redirect("developer:detail", pk=pk)


@developer_required
@require_POST
def license_purge(request, pk):
    """Irreversible: only for trashed customers, and only after typing the business name."""
    lic = get_object_or_404(License, pk=pk, deleted_at__isnull=False)
    form = PurgeForm(request.POST)
    if not form.is_valid() or form.cleaned_data["confirm"].strip() != lic.business_name:
        messages.error(request, "نام کسب‌وکار درست وارد نشد؛ حذف نهایی انجام نشد.")
        return redirect("developer:detail", pk=pk)
    services.purge_license(lic)
    messages.success(request, "مشتری و اطلاعات او برای همیشه حذف شد.")
    return redirect(reverse("developer:list") + "?trash=1")


@developer_required
def prices(request):
    form = PricesForm(request.POST or None, prices=services.get_prices())
    if request.method == "POST" and form.is_valid():
        services.save_prices(form.cleaned_data)
        messages.success(request, "قیمت‌ها ذخیره شد و در صفحه فروش و فرم مشتری اعمال می‌شود.")
        return redirect("developer:prices")
    return render(request, "licensing/prices.html", {"form": form})


@developer_required
def backups(request):
    items = backup.list_backups()
    for b in items:
        b["human"] = backup.human_size(b["size"])
    return render(request, "licensing/backups.html", {
        "items": items, "interval": settings.BACKUP_INTERVAL_HOURS, "keep": settings.BACKUP_KEEP,
    })


@developer_required
@require_POST
def backup_now(request):
    try:
        path, count = backup.create_backup()
        messages.success(request, f"پشتیبان ساخته شد: {path.name} ({count} پایگاه‌داده)")
    except Exception as exc:  # surfaced to the developer instead of a 500 page
        messages.error(request, f"ساخت پشتیبان ناموفق بود: {exc}")
    return redirect("developer:backups")


@developer_required
def backup_download(request, name):
    if not backup.NAME_RE.match(name):
        raise Http404
    path = backup.backup_dir() / name
    if not path.is_file():
        raise Http404
    return FileResponse(open(path, "rb"), as_attachment=True, filename=name)


@csrf_exempt
@require_POST
def verify_api(request):
    """Called by self-hosted installs to check their key. Reveals nothing beyond validity."""
    if settings.DEPLOYMENT_MODE != "platform" or getattr(request, "tenant", None):
        raise Http404
    if throttled(request, "verify", "x", limit=120, window=300):
        return JsonResponse({"valid": False, "status": "unknown"}, status=429)
    try:
        data = json.loads(request.body.decode())
        key = str(data.get("key", ""))[:60]
        host = str(data.get("host", ""))[:200]
    except (ValueError, UnicodeDecodeError, AttributeError):
        return JsonResponse({"valid": False, "status": "unknown"}, status=400)
    lic = License.objects.filter(key=key, mode=License.SELF).first()
    if not lic:
        return JsonResponse({"valid": False, "status": "unknown"})
    License.objects.filter(pk=lic.pk).update(last_check_at=timezone.now(), last_check_host=host)
    return JsonResponse({
        "valid": lic.is_valid, "status": lic.state, "plan": lic.plan, "business": lic.business_name,
        "expires_at": lic.expires_at.isoformat() if lic.expires_at else None, "days_left": lic.days_left,
    })


def healthz(request):
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        return HttpResponse("db error", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")
