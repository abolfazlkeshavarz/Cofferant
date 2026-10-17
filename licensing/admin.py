from django.contrib import admin

from .models import License, LicenseEvent


class EventInline(admin.TabularInline):
    model = LicenseEvent
    extra = 0
    readonly_fields = ("kind", "detail", "amount", "created_at")
    can_delete = False


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    list_display = ("business_name", "mode", "slug", "plan", "status", "expires_at", "price_paid")
    list_filter = ("mode", "status", "plan")
    search_fields = ("business_name", "slug", "key")
    readonly_fields = ("key", "created_at", "last_check_at", "last_check_host")
    inlines = [EventInline]
