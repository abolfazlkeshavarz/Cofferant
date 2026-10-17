from django.contrib import admin

from . import models


@admin.register(models.Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "accepting_orders")

    def has_add_permission(self, request):
        return not models.Venue.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ("number", "qr_slug", "notes")
    search_fields = ("number",)


class OrderItemInline(admin.TabularInline):
    model = models.OrderItem
    readonly_fields = ("product", "product_name", "quantity", "unit_price_cents", "note")
    extra = 0
    can_delete = False


@admin.register(models.Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "table", "created_at", "total_cents", "paid", "rating")
    list_filter = ("status", "paid", "created_at")
    search_fields = ("customer_name", "customer_phone", "id")
    readonly_fields = ("created_at", "updated_at", "public_token")
    inlines = [OrderItemInline]
    actions = ["mark_preparing", "mark_ready", "mark_delivered"]

    @admin.action(description="علامت‌گذاری: در حال آماده‌سازی")
    def mark_preparing(self, request, queryset):
        queryset.update(status="preparing")

    @admin.action(description="علامت‌گذاری: آماده تحویل")
    def mark_ready(self, request, queryset):
        queryset.update(status="ready")

    @admin.action(description="علامت‌گذاری: تحویل شده")
    def mark_delivered(self, request, queryset):
        queryset.update(status="delivered")


@admin.register(models.Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price_cents", "is_available", "is_popular", "sort_order")
    list_filter = ("category", "is_available")
    list_editable = ("is_available", "sort_order")
    search_fields = ("name",)


@admin.register(models.ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ("table", "kind", "created_at", "resolved_at")
    list_filter = ("kind",)


@admin.register(models.Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "emoji", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
