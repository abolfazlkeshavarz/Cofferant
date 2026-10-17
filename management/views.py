import json

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from . import payments, services
from .models import Category, Item, Order, ServiceRequest, Table, Venue


def _json_body(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _error(message, status=400, **extra):
    return JsonResponse({"ok": False, "error": message, **extra}, status=status)


# =============================
# Public Menu (customer QR page)
# =============================
@ensure_csrf_cookie  # the page posts orders via fetch(); make sure the CSRF cookie exists
def public_menu(request, qr_slug):
    table = get_object_or_404(Table, qr_slug=qr_slug)
    categories = list(Category.objects.filter(is_active=True))
    visible = {c.id for c in categories}
    rank = {c.id: i for i, c in enumerate(categories)}
    # items of a hidden category stay out of the menu; items without a category go to the end
    products = sorted(
        (p for p in Item.objects.all() if p.category_id is None or p.category_id in visible),
        key=lambda p: (rank.get(p.category_id, len(rank)), p.sort_order, p.name),
    )
    counts = {}
    for p in products:
        counts[p.category_id] = counts.get(p.category_id, 0) + 1
    types = [{"code": str(c.id), "label": c.label, "count": counts[c.id]} for c in categories if c.id in counts]
    if counts.get(None):
        types.append({"code": "0", "label": "سایر", "count": counts[None]})

    return render(
        request,
        "management/public_menu.html",
        {
            "table": table,
            "products": products,
            "types": types,
            "popular": [p for p in products if p.is_popular and p.is_available][:8],
            "accepting": Venue.load().accepting_orders and request.license.valid,
            "tip_choices": services.TIP_CHOICES if Venue.load().tips_enabled else (),
        },
    )


# =============================
# Create Order (AJAX POST)
# =============================
@require_POST
def create_order(request):
    data = _json_body(request)
    if data is None:
        return _error("درخواست نامعتبر است.")

    table = Table.objects.filter(qr_slug=str(data.get("table_qr", ""))).first()
    if not table:
        return _error("کد QR میز معتبر نیست.", status=404)

    if services.throttled(request, "order", table.id):
        return _error("تعداد درخواست‌ها زیاد است. چند دقیقه بعد دوباره تلاش کنید.", status=429)

    try:
        order, unavailable = services.create_order(table, data)
    except services.OrderError as exc:
        return _error(str(exc))

    return JsonResponse({
        "ok": True,
        "order_id": order.id,
        "status": order.status,
        "token": order.public_token,
        "track_url": request.build_absolute_uri(f"/management/o/{order.public_token}/"),
        "pay_url": reverse("pay_start", args=[order.public_token]) if order.payment_method == "online" else "",
        "total": order.total_cents,
        "skipped": unavailable,
    })


@require_POST
def quote(request):
    """Price a cart without creating anything (drives the live total in the checkout sheet)."""
    data = _json_body(request)
    if data is None:
        return _error("درخواست نامعتبر است.")
    if services.throttled(request, "quote", "all", limit=120, window=300):
        return _error("درخواست‌ها زیاد است.", status=429)
    try:
        q = services.compute_quote(data)
    except services.OrderError as exc:
        return _error(str(exc))
    return JsonResponse({"ok": True, **services.quote_public(q),
                         "coupon": q["coupon"].code if q["coupon"] else "", "skipped": q["skipped"]})


# =============================
# Order tracking (customer, by unguessable token)
# =============================
def _track_payload(order):
    steps = [
        {"code": "new", "label": "ثبت شد"},
        {"code": "preparing", "label": "در حال آماده‌سازی"},
        {"code": "ready", "label": "آماده تحویل"},
        {"code": "delivered", "label": "تحویل شد"},
    ]
    return {
        "ok": True,
        "id": order.id,
        "status": order.status,
        "status_label": order.get_status_display(),
        "steps": steps,
        "total": order.total_cents,
        "paid": order.paid,
        "rated": order.rating is not None,
        "payable": (not order.paid) and order.status != "cancelled" and Venue.load().online_payment_ready,
        "pay_url": reverse("pay_start", args=[order.public_token]),
        "items": [{"name": i.display_name, "qty": i.quantity, "note": i.note} for i in order.items.all()],
    }


@ensure_csrf_cookie
def order_track(request, token):
    order = get_object_or_404(Order.objects.select_related("table").prefetch_related("items"), public_token=token)
    return render(request, "management/order_track.html", {"order": order, "payload": _track_payload(order)})


@require_GET
def order_status(request, token):
    try:
        order = Order.objects.prefetch_related("items").get(public_token=token)
    except Order.DoesNotExist:
        raise Http404
    return JsonResponse(_track_payload(order))


@require_POST
def order_rate(request, token):
    order = get_object_or_404(Order, public_token=token)
    data = _json_body(request) or {}
    try:
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        return _error("امتیاز نامعتبر است.")
    if not 1 <= rating <= 5:
        return _error("امتیاز باید بین ۱ تا ۵ باشد.")
    if order.status != "delivered":
        return _error("پس از تحویل سفارش می‌توانید امتیاز دهید.")
    order.rating = rating
    order.feedback = str(data.get("feedback", "")).strip()[:300]
    order.save(update_fields=["rating", "feedback", "updated_at"])
    return JsonResponse({"ok": True})


# =============================
# Service requests (call waiter / bill / water)
# =============================
@require_POST
def create_request(request):
    data = _json_body(request)
    if data is None:
        return _error("درخواست نامعتبر است.")
    table = Table.objects.filter(qr_slug=str(data.get("table_qr", ""))).first()
    if not table:
        return _error("کد QR میز معتبر نیست.", status=404)
    kind = data.get("kind")
    if kind not in {k for k, _ in ServiceRequest.KINDS}:
        return _error("نوع درخواست نامعتبر است.")
    if services.throttled(request, "svc", table.id, limit=10, window=300):
        return _error("درخواست‌های زیادی ارسال شده است. کمی صبر کنید.", status=429)
    sr, created = services.open_service_request(table, kind)
    return JsonResponse({"ok": True, "new": created, "label": sr.get_kind_display()})


# =============================
# Online payment (Zarinpal)
# =============================
def pay_start(request, token):
    order = get_object_or_404(Order, public_token=token)
    venue = Venue.load()
    back = reverse("order_track", args=[token])
    if order.paid or order.status == "cancelled":
        return redirect(back)
    if not venue.online_payment_ready:
        messages.error(request, "پرداخت آنلاین فعال نیست.")
        return redirect(back)
    if services.throttled(request, "pay", order.id, limit=8, window=600):
        messages.error(request, "تلاش‌های زیاد؛ چند دقیقه دیگر دوباره امتحان کنید.")
        return redirect(back)
    try:
        authority, url = payments.start(venue, order, request.build_absolute_uri(reverse("pay_callback", args=[token])))
    except payments.PaymentError as exc:
        messages.error(request, str(exc))
        return redirect(back)
    order.payment_ref = authority
    order.save(update_fields=["payment_ref", "updated_at"])
    return redirect(url)


def pay_callback(request, token):
    order = get_object_or_404(Order, public_token=token)
    back = reverse("order_track", args=[token])
    authority = request.GET.get("Authority", "")
    if order.paid:
        return redirect(back)
    # the authority must be the one we issued for THIS order, so a callback can't be replayed on another order
    if request.GET.get("Status") != "OK" or not authority or authority != order.payment_ref:
        messages.error(request, "پرداخت انجام نشد یا لغو شد. می‌توانید دوباره تلاش کنید یا هنگام تحویل بپردازید.")
        return redirect(back)
    try:
        ref = payments.verify(Venue.load(), order, authority)
    except payments.PaymentError as exc:
        messages.error(request, str(exc))
        return redirect(back)
    if ref is None:
        messages.error(request, "پرداخت تایید نشد. اگر مبلغ از حساب شما کسر شده، تا ۷۲ ساعت برگشت می‌خورد.")
        return redirect(back)
    order.payment_method = "online"
    order.payment_ref = f"{authority}|{ref}"
    order.set_paid(True)
    order.save(update_fields=["payment_method", "payment_ref"])
    messages.success(request, "پرداخت با موفقیت انجام شد ✓")
    return redirect(back)
