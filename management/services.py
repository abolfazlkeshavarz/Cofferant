"""Business logic shared by the customer and vendor sides."""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.db.models.functions import ExtractHour, TruncDate
from django.utils import timezone

from .models import Coupon, Item, Order, OrderItem, ServiceRequest, Venue

log = logging.getLogger("cofferant")

MAX_QTY_PER_LINE = 30
MAX_LINES = 40


class OrderError(Exception):
    """User-facing validation problem (message is shown to the customer)."""


def client_ip(request):
    if getattr(settings, "TRUST_PROXY_HEADERS", False):
        fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def throttled(request, scope, table_id, limit=None, window=None):
    """Return True when this client has exceeded the allowed request rate."""
    limit = limit or settings.ORDER_RATE_LIMIT
    window = window or settings.ORDER_RATE_WINDOW
    key = f"rl:{scope}:{client_ip(request)}:{table_id}"
    added = cache.add(key, 1, window)
    if added:
        return False
    try:
        return cache.incr(key) > limit
    except ValueError:  # key expired between add() and incr()
        cache.set(key, 1, window)
        return False


def _clean_text(value, max_len):
    if value is None:
        return ""
    return str(value).strip()[:max_len]


TIP_CHOICES = (0, 5, 10, 15)


def _pct(amount, percent):
    return (amount * percent + 50) // 100  # integer rounding, no float drift


def compute_quote(payload, venue=None):
    """Validate a cart and price it on the server. Never trusts client prices.

    Returns a dict with parsed `lines`, the money breakdown and the matched `coupon`.
    Raises OrderError with a customer-facing message.
    """
    venue = venue or Venue.load()
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise OrderError("سبد خرید خالی است.")
    if len(raw_items) > MAX_LINES:
        raise OrderError("تعداد اقلام سفارش بیش از حد مجاز است.")

    lines = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise OrderError("اطلاعات سفارش نامعتبر است.")
        try:
            product_id = int(raw.get("product_id"))
            qty = int(raw.get("quantity", 1))
        except (TypeError, ValueError):
            raise OrderError("اطلاعات سفارش نامعتبر است.")
        if not 1 <= qty <= MAX_QTY_PER_LINE:
            raise OrderError(f"تعداد هر آیتم باید بین ۱ تا {MAX_QTY_PER_LINE} باشد.")
        lines.append((product_id, qty, _clean_text(raw.get("custom"), 200)))

    products = Item.objects.in_bulk({pid for pid, _, _ in lines})
    priced, skipped, subtotal = [], [], 0
    for pid, qty, note in lines:
        product = products.get(pid)
        if product is None or not product.is_available:
            skipped.append(product.name if product else "نامشخص")
            continue
        priced.append((product, qty, note if product.customizable else ""))
        subtotal += product.price_cents * qty
    if not priced:
        raise OrderError("آیتم‌های انتخاب‌شده در حال حاضر موجود نیستند.")

    coupon, discount = None, 0
    code = _clean_text(payload.get("coupon"), 30).upper()
    if code:
        coupon = Coupon.objects.filter(code=code).first()
        if coupon is None:
            raise OrderError("کد تخفیف معتبر نیست.")
        try:
            discount = coupon.discount_for(subtotal)
        except ValueError as exc:
            raise OrderError(str(exc))

    base = subtotal - discount
    service = _pct(base, venue.service_percent)
    tax = _pct(base + service, venue.tax_percent)
    try:
        tip_pct = int(payload.get("tip", 0) or 0)
    except (TypeError, ValueError):
        raise OrderError("مقدار انعام نامعتبر است.")
    if tip_pct not in TIP_CHOICES:
        raise OrderError("مقدار انعام نامعتبر است.")
    tip = _pct(base, tip_pct) if venue.tips_enabled else 0

    return {
        "lines": priced, "skipped": skipped, "coupon": coupon,
        "subtotal": subtotal, "discount": discount, "service": service, "tax": tax, "tip": tip,
        "total": base + service + tax + tip,
    }


def quote_public(q):
    return {k: q[k] for k in ("subtotal", "discount", "service", "tax", "tip", "total")}


@transaction.atomic
def create_order(table, payload):
    """Validate a cart payload and persist it as an Order. Raises OrderError."""
    venue = Venue.load()
    if not venue.accepting_orders:
        raise OrderError("در حال حاضر سفارش آنلاین دریافت نمی‌شود. لطفاً به صندوق مراجعه کنید.")
    q = compute_quote(payload, venue)

    method = "online" if payload.get("payment") == "online" and venue.online_payment_ready else "cash"
    coupon = q["coupon"]
    if coupon is not None:
        # atomic usage counting so two customers can't both take the last use
        qs = Coupon.objects.filter(pk=coupon.pk, is_active=True)
        if coupon.max_uses is not None:
            qs = qs.filter(used_count__lt=coupon.max_uses)
        if not qs.update(used_count=F("used_count") + 1):
            raise OrderError("ظرفیت استفاده از این کد تخفیف تمام شده است.")

    order = Order.objects.create(
        table=table,
        customer_name=_clean_text(payload.get("customer_name"), 150),
        customer_phone=_clean_text(payload.get("customer_phone"), 30),
        notes=_clean_text(payload.get("notes"), 500),
        subtotal_cents=q["subtotal"], discount_cents=q["discount"], service_cents=q["service"],
        tax_cents=q["tax"], tip_cents=q["tip"], total_cents=q["total"],
        coupon_code=coupon.code if coupon else "", payment_method=method,
    )
    for product, qty, note in q["lines"]:
        OrderItem.objects.create(
            order=order, product=product, product_name=product.name, quantity=qty,
            unit_price_cents=product.price_cents,  # server-side price: never trust the client
            note=note,
        )
    log.info("order %s created table=%s total=%s", order.id, table.number, q["total"])
    return order, q["skipped"]


def open_service_request(table, kind):
    """Create a service request unless the same one is already open (de-duplicated)."""
    existing = ServiceRequest.objects.filter(table=table, kind=kind, resolved_at__isnull=True).first()
    if existing:
        return existing, False
    return ServiceRequest.objects.create(table=table, kind=kind), True


# ------------------------------------------------------------------
# Serialisation helpers used by JSON endpoints
# ------------------------------------------------------------------
def order_to_dict(order):
    return {
        "id": order.id,
        "status": order.status,
        "status_label": order.get_status_display(),
        "table": order.table.number if order.table else "—",
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "notes": order.notes,
        "total": order.total_cents,
        "paid": order.paid,
        "minutes": order.minutes_waiting,
        "created_at": timezone.localtime(order.created_at).strftime("%H:%M"),
        "next_status": order.next_status,
        "items": [
            {"name": i.display_name, "qty": i.quantity, "note": i.note, "total": i.line_total()}
            for i in order.items.all()
        ],
    }


def request_to_dict(sr):
    return {
        "id": sr.id,
        "kind": sr.kind,
        "label": sr.get_kind_display(),
        "table": sr.table.number,
        "created_at": timezone.localtime(sr.created_at).strftime("%H:%M"),
    }


# ------------------------------------------------------------------
# Analytics for the owner dashboard
# ------------------------------------------------------------------
def dashboard_stats():
    now = timezone.localtime()
    start_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_week = start_today - timedelta(days=6)
    start_month = start_today - timedelta(days=29)

    valid = Order.objects.exclude(status="cancelled")
    today_qs = valid.filter(created_at__gte=start_today)
    yesterday_qs = valid.filter(created_at__gte=start_today - timedelta(days=1), created_at__lt=start_today)

    today_rev = today_qs.aggregate(s=Sum("total_cents"))["s"] or 0
    yest_rev = yesterday_qs.aggregate(s=Sum("total_cents"))["s"] or 0
    today_count = today_qs.count()

    # revenue per day for last 7 days (fill gaps with zero)
    per_day = {
        r["d"]: r["rev"]
        for r in valid.filter(created_at__gte=start_week)
        .annotate(d=TruncDate("created_at"))
        .values("d")
        .annotate(rev=Sum("total_cents"))
    }
    week = []
    for i in range(7):
        d = (start_week + timedelta(days=i)).date()
        week.append({"date": d, "revenue": per_day.get(d, 0)})
    week_max = max([w["revenue"] for w in week] + [1])
    for w in week:
        w["pct"] = round(w["revenue"] * 100 / week_max)
        w["k"] = w["revenue"] // 1000

    # busiest hours (last 30 days)
    hours = {
        r["h"]: r["c"]
        for r in valid.filter(created_at__gte=start_month)
        .annotate(h=ExtractHour("created_at"))
        .values("h")
        .annotate(c=Count("id"))
    }
    hour_max = max(list(hours.values()) + [1])
    busy = [{"hour": h, "count": hours.get(h, 0), "pct": round(hours.get(h, 0) * 100 / hour_max)} for h in range(7, 24)]

    top = (
        OrderItem.objects.filter(order__created_at__gte=start_month)
        .exclude(order__status="cancelled")
        .values(name=F("product_name"))
        .annotate(qty=Sum("quantity"), revenue=Sum(F("quantity") * F("unit_price_cents")))
        .order_by("-qty")[:6]
    )
    top = list(top)
    top_max = max([t["qty"] for t in top] + [1])
    for t in top:
        t["pct"] = round(t["qty"] * 100 / top_max)

    rating = Order.objects.filter(rating__isnull=False).aggregate(a=Avg("rating"), c=Count("id"))

    money = valid.filter(created_at__gte=start_month).aggregate(
        tips=Sum("tip_cents"), discounts=Sum("discount_cents"), online=Sum("total_cents", filter=Q(payment_method="online", paid=True)),
        total=Sum("total_cents"),
    )

    delta = None
    if yest_rev:
        delta = round((today_rev - yest_rev) * 100 / yest_rev)

    return {
        "today_revenue": today_rev,
        "today_orders": today_count,
        "avg_ticket": int(today_rev / today_count) if today_count else 0,
        "revenue_delta": delta,
        "active_orders": Order.objects.filter(status__in=Order.ACTIVE).count(),
        "open_requests": ServiceRequest.objects.filter(resolved_at__isnull=True).count(),
        "unpaid_total": valid.filter(paid=False, status="delivered").aggregate(s=Sum("total_cents"))["s"] or 0,
        "week": week,
        "week_total": sum(w["revenue"] for w in week),
        "busy": busy,
        "top": top,
        "rating_avg": round(rating["a"], 1) if rating["a"] else None,
        "rating_count": rating["c"],
        "tips_month": money["tips"] or 0,
        "discounts_month": money["discounts"] or 0,
        "online_share": round((money["online"] or 0) * 100 / money["total"]) if money["total"] else 0,
        "month_revenue": valid.filter(created_at__gte=start_month).aggregate(s=Sum("total_cents"))["s"] or 0,
    }
