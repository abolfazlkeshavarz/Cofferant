import csv
import io

import qrcode
import qrcode.image.svg
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.mixins import UserPassesTestMixin
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from management import services
from management.models import Category, Coupon, Item, Order, ServiceRequest, Table, Venue, create_default_categories
from users.decorators import staff_required

from .forms import (CategoryForm, CouponForm, VenueForm, VendorItemForm, VendorPasswordForm,
                    VendorTableForm)


class StaffRequiredMixin(UserPassesTestMixin):
    """Only active staff may use the vendor panel (login_required alone is NOT enough)."""
    raise_exception = False

    def test_func(self):
        u = self.request.user
        return u.is_authenticated and u.is_staff and u.is_active

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            messages.error(self.request, "شما به این بخش دسترسی ندارید.")
            return redirect("home")
        return redirect(f"{reverse('login')}?next={self.request.path}")


# ----------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------
@staff_required
def dashboard(request):
    venue = Venue.load()
    counts = {
        "items": Item.objects.count(),
        "tables": Table.objects.count(),
        "unavailable": Item.objects.filter(is_available=False).count(),
        "orders": Order.objects.count(),
    }
    checklist = [
        ("افزودن محصولات منو", counts["items"] > 0, "vendor:item_add"),
        ("ساخت میز و QR", counts["tables"] > 0, "vendor:table_add"),
        ("ثبت لوگو و رنگ برند", bool(venue.logo), "vendor:settings"),
        ("دریافت اولین سفارش", counts["orders"] > 0, "vendor:tables"),
        ("فعال‌سازی پرداخت آنلاین یا کد تخفیف", venue.online_payment_ready or Coupon.objects.exists(), "vendor:coupons"),
    ]
    done = sum(1 for _, ok, _ in checklist if ok)
    return render(request, "vendor/dashboard.html", {
        "stats": services.dashboard_stats(), "counts": counts,
        "checklist": checklist, "checklist_done": done, "checklist_pct": done * 100 // len(checklist),
    })


# ----------------------------------------------------------------
# Live board (kitchen display)
# ----------------------------------------------------------------
@staff_required
def board(request):
    return render(request, "vendor/board.html")


@staff_required
def board_feed(request):
    active = (
        Order.objects.filter(status__in=Order.ACTIVE)
        .select_related("table")
        .prefetch_related("items")
        .order_by("created_at")
    )
    reqs = ServiceRequest.objects.filter(resolved_at__isnull=True).select_related("table").order_by("created_at")
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    done_today = Order.objects.filter(status="delivered", updated_at__gte=start).count()
    return JsonResponse({
        "orders": [services.order_to_dict(o) for o in active],
        "requests": [services.request_to_dict(r) for r in reqs],
        "done_today": done_today,
        "server_time": timezone.localtime().strftime("%H:%M:%S"),
    })


# ----------------------------------------------------------------
# Orders
# ----------------------------------------------------------------
def _filtered_orders(request):
    status = request.GET.get("status", "all")
    sort = request.GET.get("sort", "-created_at")
    q = request.GET.get("q", "").strip()
    qs = Order.objects.select_related("table").prefetch_related("items")
    if status != "all" and status in {c for c, _ in Order.STATUS_CHOICES}:
        qs = qs.filter(status=status)
    elif status == "unpaid":
        qs = qs.filter(paid=False).exclude(status="cancelled")
    if q:
        cond = Q(customer_name__icontains=q) | Q(customer_phone__icontains=q) | Q(table__number__icontains=q)
        if q.isdigit():
            cond |= Q(id=int(q))
        qs = qs.filter(cond)
    return qs.order_by(sort if sort in ("created_at", "-created_at") else "-created_at"), status, sort, q


@staff_required
def orders_list(request):
    qs, status, sort, q = _filtered_orders(request)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    counts = dict(Order.objects.values_list("status").annotate(c=Count("id")))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "vendor/orders_list.html", {
        "page": page, "status": status, "sort": sort, "q": q,
        "counts": counts, "total_all": sum(counts.values()),
        "statuses": Order.STATUS_CHOICES, "qs": params.urlencode(),
    })


@staff_required
def orders_export(request):
    qs, *_ = _filtered_orders(request)
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel opens Persian text correctly
    w = csv.writer(buf)
    w.writerow(["شماره", "تاریخ", "میز", "وضعیت", "پرداخت", "مشتری", "تلفن", "اقلام", "مبلغ (تومان)"])
    for o in qs[:5000]:
        items = "؛ ".join(f"{i.quantity}×{i.display_name}" for i in o.items.all())
        w.writerow([
            o.id, timezone.localtime(o.created_at).strftime("%Y-%m-%d %H:%M"),
            o.table.number if o.table else "", o.get_status_display(),
            "پرداخت شده" if o.paid else "پرداخت نشده", o.customer_name,
            o.customer_phone, items, o.total_cents,
        ])
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="orders.csv"'
    return resp


@staff_required
def order_detail(request, pk):
    order = get_object_or_404(Order.objects.select_related("table").prefetch_related("items"), pk=pk)
    return render(request, "vendor/order_detail.html", {"order": order, "statuses": Order.FLOW})


@staff_required
@require_POST
def order_set_status(request, pk):
    order = get_object_or_404(Order, pk=pk)
    new = request.POST.get("status", "")
    if not order.set_status(new):
        return JsonResponse({"ok": False, "error": "این تغییر وضعیت مجاز نیست."}, status=400)
    return JsonResponse({"ok": True, "status": order.status, "label": order.get_status_display()})


@staff_required
@require_POST
def order_set_paid(request, pk):
    order = get_object_or_404(Order, pk=pk)
    order.set_paid(request.POST.get("paid", "1") == "1")
    return JsonResponse({"ok": True, "paid": order.paid})


@staff_required
@require_POST
def complete_order(request, pk):
    """Backward compatible endpoint: mark delivered."""
    order = get_object_or_404(Order, pk=pk)
    if order.status == "cancelled":
        return JsonResponse({"ok": False, "error": "سفارش لغو شده است."}, status=400)
    order.set_status("delivered")
    return JsonResponse({"ok": True, "order_id": order.id, "status": order.status})


@staff_required
@require_POST
def resolve_request(request, pk):
    sr = get_object_or_404(ServiceRequest, pk=pk)
    if sr.resolved_at is None:
        sr.resolved_at = timezone.now()
        sr.save(update_fields=["resolved_at"])
    return JsonResponse({"ok": True})


# ----------------------------------------------------------------
# Items
# ----------------------------------------------------------------
class ItemListView(StaffRequiredMixin, ListView):
    model = Item
    template_name = "vendor/items_list.html"
    context_object_name = "items"

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q", "").strip()
        cat = self.request.GET.get("cat", "")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(specs__icontains=q))
        if cat == "0":
            qs = qs.filter(category__isnull=True)
        elif cat.isdigit():
            qs = qs.filter(category_id=int(cat))
        return qs.select_related("category")

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.update(categories=Category.objects.all(), cat=self.request.GET.get("cat", ""), q=self.request.GET.get("q", ""))
        return ctx


class ItemCreateView(StaffRequiredMixin, CreateView):
    model = Item
    form_class = VendorItemForm
    template_name = "vendor/item_form.html"
    success_url = reverse_lazy("vendor:items")

    def form_valid(self, form):
        messages.success(self.request, "محصول اضافه شد.")
        return super().form_valid(form)


class ItemUpdateView(StaffRequiredMixin, UpdateView):
    model = Item
    form_class = VendorItemForm
    template_name = "vendor/item_form.html"
    success_url = reverse_lazy("vendor:items")

    def form_valid(self, form):
        messages.success(self.request, "تغییرات ذخیره شد.")
        return super().form_valid(form)


class ItemDeleteView(StaffRequiredMixin, DeleteView):
    model = Item
    template_name = "vendor/confirm_delete.html"
    success_url = reverse_lazy("vendor:items")

    def form_valid(self, form):
        messages.success(self.request, "محصول حذف شد. سفارش‌های قبلی حفظ می‌شوند.")
        return super().form_valid(form)


@staff_required
@require_POST
def item_toggle(request, pk):
    item = get_object_or_404(Item, pk=pk)
    item.is_available = not item.is_available
    item.save(update_fields=["is_available"])
    return JsonResponse({"ok": True, "available": item.is_available})


# ----------------------------------------------------------------
# Tables + QR
# ----------------------------------------------------------------
class TableListView(StaffRequiredMixin, ListView):
    model = Table
    template_name = "vendor/tables_list.html"
    context_object_name = "tables"


class TableCreateView(StaffRequiredMixin, CreateView):
    model = Table
    form_class = VendorTableForm
    template_name = "vendor/table_form.html"
    success_url = reverse_lazy("vendor:tables")

    def form_valid(self, form):
        messages.success(self.request, "میز اضافه شد.")
        return super().form_valid(form)


class TableUpdateView(StaffRequiredMixin, UpdateView):
    model = Table
    form_class = VendorTableForm
    template_name = "vendor/table_form.html"
    success_url = reverse_lazy("vendor:tables")


class TableDeleteView(StaffRequiredMixin, DeleteView):
    model = Table
    template_name = "vendor/confirm_delete.html"
    success_url = reverse_lazy("vendor:tables")


@staff_required
def table_qr(request, pk):
    table = get_object_or_404(Table, pk=pk)
    url = request.build_absolute_uri(reverse("public_menu", args=[table.qr_slug]))
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return HttpResponse(buf.getvalue(), content_type="image/svg+xml")


@staff_required
def tables_print(request):
    tables = Table.objects.all()
    return render(request, "vendor/tables_print.html", {"tables": tables})


# ----------------------------------------------------------------
# Venue settings
# ----------------------------------------------------------------
@staff_required
def venue_settings(request):
    venue = Venue.load()
    form = VenueForm(request.POST or None, request.FILES or None, instance=venue)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تنظیمات ذخیره شد.")
        return redirect("vendor:settings")
    return render(request, "vendor/settings.html", {"form": form, "password_form": VendorPasswordForm(request.user)})


@staff_required
@require_POST
def change_password(request):
    pform = VendorPasswordForm(request.user, request.POST)
    if pform.is_valid():
        user = pform.save()
        update_session_auth_hash(request, user)  # keep this device signed in
        messages.success(request, "رمز عبور شما تغییر کرد.")
        return redirect("vendor:settings")
    return render(request, "vendor/settings.html", {
        "form": VenueForm(instance=Venue.load()), "password_form": pform, "password_open": True,
    })


# ----------------------------------------------------------------
# Coupons
# ----------------------------------------------------------------
class CouponListView(StaffRequiredMixin, ListView):
    model = Coupon
    template_name = "vendor/coupons_list.html"
    context_object_name = "coupons"


class CouponCreateView(StaffRequiredMixin, CreateView):
    model = Coupon
    form_class = CouponForm
    template_name = "vendor/coupon_form.html"
    success_url = reverse_lazy("vendor:coupons")

    def form_valid(self, form):
        messages.success(self.request, "کد تخفیف ساخته شد.")
        return super().form_valid(form)


class CouponUpdateView(StaffRequiredMixin, UpdateView):
    model = Coupon
    form_class = CouponForm
    template_name = "vendor/coupon_form.html"
    success_url = reverse_lazy("vendor:coupons")


class CouponDeleteView(StaffRequiredMixin, DeleteView):
    model = Coupon
    template_name = "vendor/confirm_delete.html"
    success_url = reverse_lazy("vendor:coupons")


# ----------------------------------------------------------------
# Categories (defined by the vendor)
# ----------------------------------------------------------------
class CategoryListView(StaffRequiredMixin, ListView):
    model = Category
    template_name = "vendor/categories_list.html"
    context_object_name = "categories"

    def get_queryset(self):
        return Category.objects.annotate(item_count=Count("items"))


class CategoryCreateView(StaffRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = "vendor/category_form.html"
    success_url = reverse_lazy("vendor:categories")

    def get_initial(self):
        last = Category.objects.order_by("-sort_order").first()
        return {"sort_order": (last.sort_order + 1) if last else 0, "is_active": True}

    def form_valid(self, form):
        messages.success(self.request, "دسته‌بندی اضافه شد.")
        return super().form_valid(form)


class CategoryUpdateView(StaffRequiredMixin, UpdateView):
    model = Category
    form_class = CategoryForm
    template_name = "vendor/category_form.html"
    success_url = reverse_lazy("vendor:categories")

    def form_valid(self, form):
        messages.success(self.request, "تغییرات ذخیره شد.")
        return super().form_valid(form)


class CategoryDeleteView(StaffRequiredMixin, DeleteView):
    model = Category
    template_name = "vendor/confirm_delete.html"
    success_url = reverse_lazy("vendor:categories")

    def form_valid(self, form):
        messages.success(self.request, "دسته‌بندی حذف شد؛ محصولات آن در بخش «سایر» می‌مانند.")
        return super().form_valid(form)


@staff_required
@require_POST
def category_defaults(request):
    """One-click starter categories for an empty menu."""
    n = create_default_categories()
    messages.success(request, f"{n} دسته پیشنهادی ساخته شد." if n else "دسته‌بندی‌ها از قبل وجود دارند.")
    return redirect("vendor:categories")
