from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils.decorators import method_decorator
from django.views.generic import ListView, CreateView, UpdateView
from django.urls import reverse_lazy
from django.http import JsonResponse, HttpResponseBadRequest

from management.models import Item, Table, Order
from .forms import VendorItemForm, VendorTableForm

# Dashboard
@login_required
@user_passes_test(lambda u: u.is_staff)
def dashboard(request):
    ctx = {
        "items_count": Item.objects.count(),
        "tables_count": Table.objects.count(),
        "orders_count": Order.objects.count(),
        "new_orders": Order.objects.filter(status="new").count(),
    }
    return render(request, "vendor/dashboard.html", ctx)


# Items
@method_decorator(login_required, name="dispatch")
class ItemListView(ListView):
    model = Item
    template_name = "vendor/items_list.html"
    context_object_name = "items"
    paginate_by = 50


@method_decorator(login_required, name="dispatch")
class ItemCreateView(CreateView):
    model = Item
    form_class = VendorItemForm
    template_name = "vendor/item_form.html"
    success_url = reverse_lazy("vendor:items")


@method_decorator(login_required, name="dispatch")
class ItemUpdateView(UpdateView):
    model = Item
    form_class = VendorItemForm
    template_name = "vendor/item_form.html"
    success_url = reverse_lazy("vendor:items")


# Tables
@method_decorator(login_required, name="dispatch")
class TableListView(ListView):
    model = Table
    template_name = "vendor/tables_list.html"
    context_object_name = "tables"


@method_decorator(login_required, name="dispatch")
class TableCreateView(CreateView):
    model = Table
    form_class = VendorTableForm
    template_name = "vendor/table_form.html"
    success_url = reverse_lazy("vendor:tables")


# Orders list and detail
@login_required
@user_passes_test(lambda u: u.is_staff)
def orders_list(request):
    # 1. Get filter and sort parameters from URL
    status_filter = request.GET.get('status', 'all')  # Default: 'all'
    sort_by = request.GET.get('sort', '-created_at')    # Default: Newest

    # 2. Start with all orders
    qs = Order.objects.all()

    # 3. Apply Status Filter
    if status_filter != 'all':
        # Apply filter based on the 'status' field in the model
        qs = qs.filter(status=status_filter)

    # 4. Apply Sorting
    # Only allow safe sorting fields to prevent security issues
    allowed_sorts = ['created_at', '-created_at'] 
    if sort_by in allowed_sorts:
        qs = qs.order_by(sort_by)
    else:
        # Fallback to default sorting if parameter is invalid/missing
        qs = qs.order_by('-created_at')

    # 5. Render the template
    return render(request, "vendor/orders_list.html", {"orders": qs})


@login_required
@user_passes_test(lambda u: u.is_staff)
def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk)
    return render(request, "vendor/order_detail.html", {"order": order})


# Mark order completed (expects POST via fetch; returns JSON)
@login_required
@user_passes_test(lambda u: u.is_staff)
def complete_order(request, pk):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    order = get_object_or_404(Order, pk=pk)
    # Only allow marking non-cancelled orders; keep others for history
    if order.status == "cancelled":
        return JsonResponse({"error": "Order cancelled"}, status=400)
    order.status = "delivered"  # or "ready" then "delivered" depending workflow; using 'delivered' as completed
    order.save()
    return JsonResponse({"ok": True, "order_id": order.id, "status": order.status})