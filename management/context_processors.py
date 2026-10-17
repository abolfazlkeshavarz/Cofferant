from .models import Order, ServiceRequest, Venue


def venue(request):
    ctx = {"venue": Venue.load()}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_staff and request.path.startswith("/vendor"):
        ctx["nav_active_orders"] = Order.objects.filter(status__in=Order.ACTIVE).count()
        ctx["nav_open_requests"] = ServiceRequest.objects.filter(resolved_at__isnull=True).count()
    return ctx
