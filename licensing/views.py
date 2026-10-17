import json
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from management.services import throttled

from . import services
from .forms import CancelForm, LicenseCreateForm, RenewForm
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
    return render(request, "licensing/dashboard.html", {"stats": services.developer_stats()})


@developer_required
def license_list(request):
    qs = License.objects.all()
    q = request.GET.get("q", "").strip()
    state = request.GET.get("state", "all")
    mode = request.GET.get("mode", "all")
    if q:
        qs = qs.filter(Q(business_name__icontains=q) | Q(contact_name__icontains=q) | Q(slug__icontains=q)
                       | Q(key__icontains=q) | Q(phone__icontains=q) | Q(domain__icontains=q))
    if mode in (License.HOSTED, License.SELF):
        qs = qs.filter(mode=mode)
    rows = list(qs)
    if state in ("active", "expired", "cancelled"):
        rows = [r for r in rows if r.state == state]
    page = Paginator(rows, 25).get_page(request.GET.get("page"))
    return render(request, "licensing/list.html", {"page": page, "q": q, "state": state, "mode": mode})


@developer_required
def license_create(request):
    form = LicenseCreateForm(request.POST or None, initial={"price_paid": settings.PLAN_PRICES["1m"]})
    if request.method == "POST" and form.is_valid():
        lic, creds = services.create_customer(form)
        if creds:
            request.session["flash_creds"] = creds
        messages.success(request, "مشتری و لایسنس ساخته شد.")
        return redirect("developer:detail", pk=lic.pk)
    return render(request, "licensing/create.html", {"form": form, "prices": settings.PLAN_PRICES})


@developer_required
def license_detail(request, pk):
    lic = get_object_or_404(License, pk=pk)
    return render(request, "licensing/detail.html", {
        "lic": lic, "events": lic.events.all()[:30],
        "creds": request.session.pop("flash_creds", None),
        "renew_form": RenewForm(initial={"plan": lic.plan if lic.plan != "forever" else "1y", "price": settings.PLAN_PRICES.get(lic.plan, 0)}),
        "cancel_form": CancelForm(),
        "prices": settings.PLAN_PRICES,
        "server_url": f"https://{settings.PLATFORM_DOMAIN}",
        "plan_choices": PLAN_CHOICES,
    })


@developer_required
@require_POST
def license_renew(request, pk):
    lic = get_object_or_404(License, pk=pk)
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
    lic = get_object_or_404(License, pk=pk)
    form = CancelForm(request.POST)
    services.apply_and_invalidate(lic, "cancel", form.cleaned_data.get("reason", "") if form.is_valid() else "")
    messages.warning(request, "اشتراک لغو شد؛ پنل مشتری از همین لحظه غیرفعال است.")
    return redirect("developer:detail", pk=pk)


@developer_required
@require_POST
def license_reactivate(request, pk):
    lic = get_object_or_404(License, pk=pk)
    services.apply_and_invalidate(lic, "reactivate")
    if lic.state == "expired":
        messages.warning(request, "اشتراک فعال شد ولی تاریخ انقضا گذشته است؛ لطفاً تمدید کنید.")
    else:
        messages.success(request, "اشتراک دوباره فعال شد.")
    return redirect("developer:detail", pk=pk)


@developer_required
@require_POST
def license_reset_owner(request, pk):
    lic = get_object_or_404(License, pk=pk, mode=License.HOSTED)
    request.session["flash_creds"] = services.reset_owner_password(lic)
    return redirect("developer:detail", pk=pk)


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
