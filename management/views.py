# management/views.py
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponseBadRequest
from .models import Table, Order, OrderItem, Item 
import json


# =============================
# Public Menu (customer QR page)
# =============================
def public_menu(request, qr_slug):
    table = get_object_or_404(Table, qr_slug=qr_slug)
    products = Item.objects.all()

    # build category tabs (only categories that have products)
    types = []
    for code, label in Item.CHOICES:
        # Note: We count all products, including out-of-stock, as the requirement is to *show* them.
        count = products.filter(drink_type=code).count() 
        if count:
            types.append({"code": code, "label": label, "count": count})

    return render(
        request,
        "management/public_menu.html",
        {"table": table, "products": products, "types": types},
    )


# =============================
# Create Order (AJAX POST)
# =============================
@require_POST
def create_order(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("Invalid JSON")

    # ---- Table ----
    table_slug = data.get("table_qr")
    table = Table.objects.filter(qr_slug=table_slug).first()
    if not table:
        return HttpResponseBadRequest("Invalid table QR")

    # ---- Order ----
    order = Order.objects.create(
        table=table,
        customer_name=data.get("customer_name", ""),
        customer_phone=data.get("customer_phone", ""),
        notes=data.get("notes", ""),
    )

    total = 0
    items_data = data.get("items", [])

    if not items_data:
        order.delete() # اگر سبد خالی بود، آبجکت سفارش را حذف کن
        return HttpResponseBadRequest("Empty order")

    valid_items_count = 0 
    
    # ---- Order Items ----
    for it in items_data:
        product_id = it.get("product_id")
        qty = int(it.get("quantity", 1))
        custom_note = it.get("custom", "") 

        # find product
        try:
            product = Item.objects.get(id=product_id)
            
            # 1. SERVER-SIDE VALIDATION: اگر محصول ناموجود است، از افزودن آن صرف نظر کن
            if not product.is_available:
                continue 
                
        except Item.DoesNotExist:
            continue  # محصول نامعتبر، رد کردن

        unit_price = product.price_cents

        order_item = OrderItem.objects.create(
            order=order,
            product=product,
            quantity=qty,
            unit_price_cents=unit_price,
            note=custom_note,
        )

        total += order_item.line_total()
        valid_items_count += 1 

    # ---- Final total ----
    # 2. اگر تمام آیتم‌های سبد ناموجود بودند و هیچ آیتم معتبری ثبت نشد:
    if valid_items_count == 0:
        order.delete()
        return HttpResponseBadRequest("No valid items in the order")
        
    order.total_cents = total
    order.save()

    return JsonResponse({
        "order_id": order.id,
        "status": order.status
    })