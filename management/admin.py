from django.contrib import admin
from . import models
# Register your models here.


@admin.register(models.Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ("number", "qr_slug", "notes")

class OrderItemInline(admin.TabularInline):
    model = models.OrderItem
    readonly_fields = ("product", "quantity", "unit_price_cents", "note")
    extra = 0

@admin.register(models.Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "table", "created_at", "total_cents", "paid")
    list_filter = ("status","paid","created_at")
    readonly_fields = ("created_at",)
    inlines = [OrderItemInline]
    actions = ["mark_preparing", "mark_ready", "mark_delivered"]

    def mark_preparing(self, request, queryset):
        queryset.update(status="preparing")
    mark_preparing.short_description = "Mark selected orders as Preparing"

    def mark_ready(self, request, queryset):
        queryset.update(status="ready")
    mark_ready.short_description = "Mark selected orders as Ready"

    def mark_delivered(self, request, queryset):
        queryset.update(status="delivered")
    mark_delivered.short_description = "Mark selected orders as Delivered"

# register Item if not already
try:
    admin.site.register(models.Item)
except Exception:
    pass
