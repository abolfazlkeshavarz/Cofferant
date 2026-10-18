from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render

from . import checker, tenancy

# Paths that must keep working even when a license is cancelled/expired
OPEN_PREFIXES = ("/static/", "/media/", "/api/license/", "/developer/", "/healthz", "/favicon.ico")
# The vendor's "working" surface, locked when the license is not valid
LOCKED_PREFIXES = ("/vendor/", "/admin/")
LOCKED_API = ("/management/api/orders/create/", "/management/api/requests/create/", "/management/pay/")


LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


class TenantMiddleware:
    """Binds the request to a tenant database (platform mode).

    A request belongs to a customer when its Host is a sub-domain of the platform domain or a domain the
    developer registered for that customer. The platform's own domain (and loopback, for health checks)
    reaches the sales page and developer panel. Any other Host is refused with 404.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        slug = None
        request.tenant = None
        if settings.DEPLOYMENT_MODE == "platform":
            host = request._get_raw_host().split(":")[0].lower().rstrip(".")
            roots = [settings.PLATFORM_DOMAIN, *settings.PLATFORM_ALIAS_DOMAINS]
            if host in roots or host in [f"www.{r}" for r in roots] or host in LOOPBACK_HOSTS:
                pass
            else:
                root = next((r for r in roots if host.endswith("." + r)), None)
                if root:
                    slug = host[: -len(root) - 1]
                else:
                    slug = checker.slug_for_domain(host)
                if (not slug or not tenancy.valid_slug(slug) or not tenancy.tenant_db_exists(slug)
                        or checker.hosted_state(slug).status in ("deleted", "unknown")):
                    return render(request, "licensing/unknown_tenant.html", {"slug": host}, status=404)
                tenancy.register_tenant_db(slug)
                request.tenant = slug
        token = tenancy.current_tenant.set(slug)
        try:
            return self.get_response(request)
        finally:
            tenancy.current_tenant.reset(token)


class LicenseMiddleware:
    """Blocks the vendor panel and ordering when the venue's license is not valid."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        state = checker.current_state(request.get_host().split(":")[0])
        request.license = state
        if not state.valid and not path.startswith(OPEN_PREFIXES):
            wants_json = (
                request.headers.get("X-Requested-With") == "XMLHttpRequest"
                or "application/json" in request.headers.get("Accept", "")
                or request.content_type == "application/json"
            )
            if path.startswith(LOCKED_API) or (path.startswith(LOCKED_PREFIXES) and wants_json):
                return JsonResponse({"ok": False, "error": state.message or "سرویس غیرفعال است."}, status=402)
            if path.startswith(LOCKED_PREFIXES):
                return render(request, "licensing/blocked.html", {"state": state}, status=402)
        return self.get_response(request)
